# -*- coding: utf-8 -*-
import logging
import re
import time
import zlib
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from urllib.parse import urlparse

from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import UserError

from .prestashop_client import PrestaShopClient, PrestaShopAPIError, USER_AGENT
from . import consent_rules
import requests

_logger = logging.getLogger(__name__)

DT_FMT = "%Y-%m-%d %H:%M:%S"

class PrestashopBackend(models.Model):
    _name = "prestashop.backend"
    _description = "PrestaShop Backend"
    _rec_name = "name"

    name = fields.Char(required=True, default="PrestaShop")
    base_url = fields.Char(required=True, help="Example: https://shop.example.com")
    api_key = fields.Char(required=True, help="PrestaShop Webservice key")
    webhook_secret = fields.Char(
        string="Webhook Secret",
        help="Shared secret used to validate PrestaShop webhook signatures."
    )
    webhook_url = fields.Char(
        string="Webhook URL",
        help="Public Odoo webhook base URL (e.g. https://odoo.example.com/prestashop/webhook). Endpoints /consents and /addresses are added automatically."
    )
    webhook_url_auto = fields.Char(
        string="Webhook URL (auto)",
        compute="_compute_webhook_url_auto",
        store=False,
        help="Auto-generated webhook URL including db=... for this Odoo instance."
    )

    verify_tls = fields.Boolean(default=True, help="Disable only for testing with self-signed certificates.")
    timeout = fields.Integer(default=30)

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    @api.model
    def _default_pricelist_id(self):
        """Return a default pricelist.

        For the connector's first steps (e.g., customer import), a pricelist is not critical.
        We therefore choose the first available pricelist for the current company (or global).
        """
        company = self.env.company
        pl = self.env["product.pricelist"].search([("company_id", "in", [company.id, False])], limit=1)
        return pl.id if pl else False

    pricelist_id = fields.Many2one(
        "product.pricelist",
        required=False,
        default=_default_pricelist_id,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        required=True,
        default=lambda self: self.env["stock.warehouse"].search([("company_id", "=", self.env.company.id)], limit=1),
    )
    team_id = fields.Many2one("crm.team", string="Sales Team")

    shipping_product_id = fields.Many2one(
        "product.product",
        help="Product used to create the shipping line on imported orders."
    )

    last_order_sync = fields.Datetime(string="Last Order Sync", default=lambda self: fields.Datetime.now() - timedelta(days=7))
    order_sync_window_days = fields.Integer(default=30, help="Safety window: re-check orders created in the last N days.")

    # PrestaShop Webservice instances often do not allow filtering orders by date_add.
    # We therefore provide an id-based incremental sync mechanism.
    last_order_presta_id = fields.Integer(
        string="Last imported Presta order ID",
        default=0,
        help="Used for incremental order sync using filter[id]. Set it manually to skip older orders."
    )
    order_batch_size = fields.Integer(
        default=200,
        help="Number of orders fetched per API call during import."
    )
    order_max_per_run = fields.Integer(
        default=500,
        help="Safety limit: maximum orders processed per import run. Run the import again to continue."
    )
    create_missing_products = fields.Boolean(default=True, help="If a product is missing, create it as a consumable product using SKU/reference.")
    confirm_order_on_import = fields.Boolean(default=False, help="If enabled, confirms Sale Orders after import (use carefully).")

    order_import_enabled = fields.Boolean(
        string="Enable Order Import",
        compute="_compute_order_import_enabled",
        store=False,
        help="When disabled, the 'Import Orders' button is greyed out and order import is blocked."
    )

    @api.depends()
    def _compute_order_import_enabled(self):
        """Feature toggle for order import.

        You asked to focus on the newsletter for now, so order import stays disabled.
        Keeping this as a non-stored computed field avoids database schema churn.
        """
        for rec in self:
            rec.order_import_enabled = False

    @api.depends()
    def _compute_webhook_url_auto(self):
        """Compute webhook URL based on web.base.url configuration.

        Recommended setup for multi-DB with webhooks:
        1. Set dbfilter = ^%d$ in odoo.conf
        2. Set web.base.url to the subdomain for each database:
           - DB 'mydb' -> https://mydb.odoo17.example.com
           - DB 'prod' -> https://prod.odoo17.example.com
        3. The webhook URL will be automatically correct.
        """
        for rec in self:
            base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
            base_url = base_url.strip()

            if not base_url:
                rec.webhook_url_auto = False
                continue

            # Base webhook URL (without /consents or /addresses suffix)
            webhook_url = f"{base_url.rstrip('/')}/prestashop/webhook"
            rec.webhook_url_auto = webhook_url

    paid_state_ids = fields.Char(
        string="Paid state IDs (optional)",
        help="Comma-separated PrestaShop 'current_state' IDs considered paid/validated. If empty, no paid-state logic is applied."
    )


    # Customers
    last_customer_sync = fields.Datetime(
        string="Last Customer Sync",
        default=lambda self: fields.Datetime.now() - timedelta(days=30),
        help="Last time customers were synced from PrestaShop."
    )
    customer_sync_window_days = fields.Integer(
        default=30,
        help="Safety window: re-check customers created in the last N days."
    )
    customer_tag_id = fields.Many2one(
        "res.partner.category",
        string="Imported Customer Tag",
        help="Tag automatically applied to customers imported from PrestaShop."
    )
    site_tag_id = fields.Many2one(
        "res.partner.category",
        string="Site Tag",
        help="Tag identifying which PrestaShop site the customer comes from (e.g. 'PS: Mon Site FR'). Auto-created from the backend name."
    )
    newsletter_tag_id = fields.Many2one(
        "res.partner.category",
        string="Newsletter Tag",
        help="Tag automatically applied to PrestaShop customers who are subscribed to the newsletter."
    )

    partner_offers_tag_id = fields.Many2one(
        "res.partner.category",
        string="Partner Offers Tag",
        help="Tag automatically applied to PrestaShop customers who accepted partner offers (optin)."
    )

    newsletter_revoked_tag_id = fields.Many2one(
        "res.partner.category",
        string="Newsletter Revoked Tag (Odoo)",
        help=(
            "If this tag is set on a contact, Odoo will treat the Newsletter consent as revoked "
            "(even if PrestaShop still shows newsletter=1). During Odoo -> Presta consent sync, "
            "we will push newsletter=0."
        ),
    )

    partner_offers_revoked_tag_id = fields.Many2one(
        "res.partner.category",
        string="Partner Offers Revoked Tag (Odoo)",
        help=(
            "If this tag is set on a contact, Odoo will treat the Partner Offers consent as revoked "
            "(even if PrestaShop still shows optin=1). During Odoo -> Presta consent sync, "
            "we will push optin=0."
        ),
    )

    # Marketing consent governance
    last_consents_sync = fields.Datetime(
        string="Last Consents Sync",
        help="Last time newsletter/optin consents were synchronized (tags + Email Marketing lists)."
    )
    respect_odoo_opt_out = fields.Boolean(
        string="Respect Odoo opt-out",
        default=True,
        help="If enabled, recipients who opted out in Odoo will never be re-subscribed automatically."
    )

    opt_out_push_max_per_run = fields.Integer(
        string="Max revocations per automatic push",
        default=25,
        help="Safety limit for the automatic Odoo -> PrestaShop push (cron and real-time hooks): "
             "if more consents than this would be revoked in one run, nothing is sent and an error is logged. "
             "The 'Odoo → Presta' button is not limited. 0 = no limit.",
    )

    include_guest_customers = fields.Boolean(
        default=True,
        help="If enabled, guest checkout customers are also imported."
    )

    last_customer_presta_id = fields.Integer(
        string="Last imported Presta customer ID",
        default=0,
        help="Used for incremental customer sync when date filters are not available in the PrestaShop Webservice."
    )
    customer_batch_size = fields.Integer(
        default=200,
        help="Number of customers fetched per API call during import."
    )
    customer_max_per_run = fields.Integer(
        default=5000,
        help="Safety limit: maximum customers processed per import run. Run the import again to continue."
    )

    # Addresses
    last_address_sync = fields.Datetime(
        string="Last Address Sync",
        help="Last time customer addresses were synchronized from PrestaShop."
    )
    address_max_customers_per_run = fields.Integer(
        default=500,
        help="Safety limit: maximum customers whose addresses are processed per run."
    )
    address_max_addresses_per_run = fields.Integer(
        default=2000,
        help="Safety limit: maximum addresses processed per run."
    )
    address_customer_chunk_size = fields.Integer(
        default=50,
        help="When supported by the PrestaShop API, fetch addresses in batches for this many customers per call." 
    )
    address_deduplicate = fields.Boolean(
        default=True,
        help="If enabled, re-use an existing child address when the same address already exists for the customer (avoid duplicates)."
    )

    # Address sync cursor
    address_sync_cursor_map_id = fields.Integer(
        string="Address Sync Cursor (map id)",
        default=0,
        help=(
            "Internal cursor used by address synchronization to continue where it stopped. "
            "This prevents always processing the first N customers when you run the sync multiple times."
        ),
    )
    address_full_scan_next_run = fields.Datetime(
        string="Next Weekly Address Full Scan",
        readonly=True,
        help="Informational: next planned weekly full scan run (computed by cron).",
    )

    def _client(self):
        self.ensure_one()
        return PrestaShopClient(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            verify_tls=self.verify_tls,
        )

    def _log(self, operation, status, message, details=None, prestashop_id=None, duration_sec=None):
        vals = {
            "backend_id": self.id,
            "operation": operation,
            "status": status,
            "message": message,
            "details": details or "",
            "prestashop_id": prestashop_id or "",
        }
        if duration_sec is not None:
            vals["duration_sec"] = float(duration_sec)
        self.env["prestashop.sync.log"].sudo().create(vals)

    def _log_outside_tx(self, operation, status, message, details=None, prestashop_id=None):
        """Create a log entry that survives the current transaction rollback."""
        self.ensure_one()
        vals = {
            "backend_id": self.id,
            "operation": operation,
            "status": status,
            "message": message,
            "details": details or "",
            "prestashop_id": prestashop_id or "",
        }
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["prestashop.sync.log"].sudo().create(vals)
            cr.commit()

    def _lock_key(self, operation: str) -> int:
        """Return a stable 32-bit advisory lock key for this backend + operation."""
        self.ensure_one()
        token = f"prestashop_connector_basic:{self.id}:{operation}".encode("utf-8")
        return int(zlib.crc32(token))

    def _try_acquire_lock(self, operation: str) -> int:
        """Try to acquire a Postgres advisory lock. Returns the lock key if acquired, 0 otherwise."""
        self.ensure_one()
        key = self._lock_key(operation)
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (key,))
        got = self.env.cr.fetchone()[0]
        return key if got else 0

    def _release_lock(self, key: int):
        self.ensure_one()
        if key:
            try:
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", (int(key),))
            except Exception:
                # Best-effort unlock
                pass

    def _run_locked(self, operation: str, func):
        """Run a callable under an advisory lock."""
        self.ensure_one()
        lock_key = self._try_acquire_lock(operation)
        if not lock_key:
            raise UserError(_("This operation is already running for this backend: %s") % operation)
        try:
            return func()
        finally:
            self._release_lock(lock_key)

    def _notification(self, message, title=None, notif_type=None):
        """Client action showing a toast to the user."""
        params = {"title": title or _("PrestaShop"), "message": message, "sticky": False}
        if notif_type:
            params["type"] = notif_type
        return {"type": "ir.actions.client", "tag": "display_notification", "params": params}

    def action_purge_logs(self):
        """Delete all sync logs for this backend."""
        self.ensure_one()
        count = self.env["prestashop.sync.log"].sudo().search_count([("backend_id", "=", self.id)])
        self.env["prestashop.sync.log"].sudo().search([("backend_id", "=", self.id)]).unlink()
        return self._notification(_("%d logs deleted.") % count)

    def action_test_connection(self):
        self.ensure_one()
        client = self._client()
        try:
            client.get_xml("languages", params={"display": "[id,name]"})
        except PrestaShopAPIError as e:
            raise UserError(_("Connection failed: %s") % e)
        return self._notification(_("Connection successful."))

    def action_test_webhook(self):
        """Complete bidirectional webhook test.

        This test validates:
        1. PrestaShop API is accessible
        2. PrestaShop module has webhook configured
        3. PrestaShop webhook URL matches Odoo URL
        4. PrestaShop webhook secret matches Odoo secret
        5. PrestaShop can send webhooks to Odoo
        6. Odoo can receive and validate webhooks
        """
        self.ensure_one()
        self._log_outside_tx("sync_consents", "warning", "Webhook test started")

        if not self.webhook_secret:
            raise UserError(_("Please set the Webhook Secret first."))

        # 1. Verify PrestaShop connection
        if not self.base_url or not self.api_key:
            raise UserError(_("Please configure PrestaShop connection (URL + API key) before testing webhook."))

        client = self._client()
        try:
            client.get_xml("languages", params={"display": "[id]"})
        except PrestaShopAPIError as e:
            self._log_outside_tx("sync_consents", "error", "Webhook test aborted: PrestaShop connection failed", details=str(e))
            raise UserError(_("PrestaShop connection failed. Fix this before testing webhook:\n\n%s") % e)

        # 2. Get expected Odoo webhook URL
        self.invalidate_recordset(['webhook_url_auto'])
        odoo_webhook_url = (self.webhook_url or self.webhook_url_auto or "").strip()

        if not odoo_webhook_url:
            raise UserError(_("Please configure web.base.url in System Parameters or set the Webhook URL manually."))

        # 3. Read PrestaShop module webhook configuration
        prestashop_config_url = f"{self.base_url.rstrip('/')}/module/prestashopodoo/webhookconfig?ws_key={self.api_key}"

        try:
            config_resp = requests.get(
                prestashop_config_url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout or 30,
                verify=bool(self.verify_tls),
            )
        except Exception as e:
            e = client._redact(e)
            self._log_outside_tx("sync_consents", "error", "Failed to read PrestaShop webhook config", details=e)
            raise UserError(_(
                "Could not read PrestaShop webhook configuration.\n\n"
                "Make sure the PrestaShop module has the webhook config endpoint installed.\n\n"
                "Error: %s"
            ) % e)

        if config_resp.status_code != 200:
            self._log_outside_tx("sync_consents", "error", f"PrestaShop webhook config endpoint returned {config_resp.status_code}", details=config_resp.text[:500])
            raise UserError(_(
                "PrestaShop webhook config endpoint failed (HTTP %s).\n\n"
                "Make sure the PrestaShop module webhook endpoints are installed.\n\n"
                "Response: %s"
            ) % (config_resp.status_code, config_resp.text[:200]))

        try:
            presta_config = config_resp.json()
        except Exception as e:
            raise UserError(_("Invalid JSON response from PrestaShop webhook config: %s") % e)

        presta_webhook_url = (presta_config.get('webhook_url') or '').strip()
        presta_webhook_secret = (presta_config.get('webhook_secret') or '').strip()
        presta_backend_id = presta_config.get('backend_id')

        # 4. Validate configuration matches
        issues = []

        # Normalize URLs: strip trailing slashes and known endpoint suffixes
        def _normalize_webhook_url(url):
            url = url.rstrip('/')
            for suffix in ('/consents', '/addresses'):
                if url.endswith(suffix):
                    url = url[:-len(suffix)]
            return url.rstrip('/')

        if not presta_webhook_url:
            issues.append("❌ PrestaShop webhook URL is not configured")
        elif _normalize_webhook_url(presta_webhook_url) != _normalize_webhook_url(odoo_webhook_url):
            issues.append(f"❌ Webhook URL mismatch:\n  • Odoo:       {odoo_webhook_url}\n  • PrestaShop: {presta_webhook_url}")

        if not presta_webhook_secret:
            issues.append("❌ PrestaShop webhook secret is not configured")
        elif presta_webhook_secret != self.webhook_secret:
            issues.append("❌ Webhook secret mismatch between Odoo and PrestaShop")

        if presta_backend_id and str(presta_backend_id) != str(self.id):
            issues.append(f"⚠️  Backend ID mismatch: Odoo={self.id}, PrestaShop={presta_backend_id}")

        if issues:
            error_msg = "Webhook configuration issues found:\n\n" + "\n\n".join(issues)
            error_msg += "\n\n📋 Expected configuration in PrestaShop module:\n"
            error_msg += f"  • URL:        {odoo_webhook_url}\n"
            error_msg += f"  • Secret:     {self.webhook_secret[:8]}... ({len(self.webhook_secret)} chars)\n"
            error_msg += f"  • Backend ID: {self.id}"

            self._log_outside_tx("sync_consents", "error", "Webhook config validation failed", details=error_msg)
            raise UserError(error_msg)

        # 5. Trigger webhook test from PrestaShop
        prestashop_test_url = f"{self.base_url.rstrip('/')}/module/prestashopodoo/webhooktest?ws_key={self.api_key}"

        try:
            test_resp = requests.post(
                prestashop_test_url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout or 30,
                verify=bool(self.verify_tls),
            )
        except Exception as e:
            e = client._redact(e)
            self._log_outside_tx("sync_consents", "error", "Failed to trigger PrestaShop webhook test", details=e)
            raise UserError(_(
                "Could not trigger webhook test from PrestaShop.\n\n"
                "Make sure the PrestaShop module has the webhook test endpoint installed.\n\n"
                "Error: %s"
            ) % e)

        if test_resp.status_code != 200:
            self._log_outside_tx("sync_consents", "error", f"PrestaShop webhook test endpoint returned {test_resp.status_code}", details=test_resp.text[:500])
            raise UserError(_(
                "PrestaShop webhook test failed (HTTP %s).\n\n"
                "Response: %s"
            ) % (test_resp.status_code, test_resp.text[:500]))

        try:
            test_result = test_resp.json()
        except Exception as e:
            raise UserError(_("Invalid JSON response from PrestaShop webhook test: %s") % e)

        # 6. Validate test result
        if test_result.get('status') != 'success':
            error_details = f"HTTP {test_result.get('http_code')}: {test_result.get('error') or test_result.get('response', '')}"
            self._log_outside_tx("sync_consents", "error", "PrestaShop → Odoo webhook test failed", details=error_details)
            raise UserError(_(
                "Webhook test from PrestaShop to Odoo failed.\n\n"
                "PrestaShop could not send webhook to Odoo.\n\n"
                "Details: %s"
            ) % error_details)

        # Success!
        success_msg = (
            "✅ Complete webhook test successful!\n\n"
            "Validated:\n"
            "  • PrestaShop API connection\n"
            f"  • Webhook URL matches: {odoo_webhook_url}\n"
            "  • Webhook secret matches\n"
            "  • PrestaShop → Odoo webhook delivery\n"
            "  • Odoo webhook signature validation"
        )

        self._log_outside_tx("sync_consents", "ok", "Complete webhook test successful", details=success_msg)

        return self._notification(success_msg, title=_("PrestaShop Webhook Test"), notif_type="success")


    def action_import_orders(self):
        for backend in self:
            if not backend.order_import_enabled:
                raise UserError(_("Order import is disabled on this backend (focus: newsletter)."))
            backend._import_orders()

    @api.model
    def cron_import_orders(self):
        """Cron entry point for order import.

        Order import is intentionally disabled for now (feature toggle), therefore this cron
        will effectively do nothing unless order_import_enabled becomes True in a future version.
        """
        for backend in self.search([]):
            if not backend.order_import_enabled:
                continue
            try:
                backend._run_locked("import_orders", lambda: backend._import_orders())
            except Exception as e:
                backend._log("import_orders", "error", "Cron: failed to import orders", details=str(e))

    @api.model
    def cron_import_customers(self):
        for backend in self.search([]):
            try:
                backend._run_locked("import_customers", lambda: backend._import_customers())
            except Exception as e:
                backend._log("import_customers", "error", "Cron: failed to import customers", details=str(e))

    @api.model
    def cron_sync_addresses(self):
        for backend in self.search([]):
            try:
                backend._run_locked("sync_addresses", lambda: backend._sync_addresses())
            except Exception as e:
                backend._log("sync_addresses", "error", "Cron: failed to sync addresses", details=str(e))

    @api.model
    def cron_sync_consents(self):
        for backend in self.search([]):
            try:
                def run():
                    client = backend._client()
                    backend._sync_email_marketing_lists(client=client, preview=False)
                    backend.last_consents_sync = fields.Datetime.now()
                backend._run_locked("sync_consents", run)
            except Exception as e:
                backend._log("sync_consents", "error", "Cron: failed to sync consents", details=str(e))

    @api.model
    def cron_push_opt_outs_to_prestashop(self):
        for backend in self.search([]):
            try:
                def run():
                    client = backend._client()
                    backend._push_opt_outs_to_prestashop(client)
                backend._run_locked("sync_consents_odoo_to_prestashop", run)
            except Exception as e:
                backend._log("sync_consents_odoo_to_prestashop", "error", "Cron: failed to sync consents (Odoo -> PrestaShop)", details=str(e))

    def _ensure_customer_tag(self):
        """Ensure the 'Client Prestashop' partner tag exists and return it.

        Migration note:
        - If an older tag named 'Client Presta' exists, we rename it in-place so existing
          partners keep their category link.
        """
        self.ensure_one()
        if self.customer_tag_id:
            return self.customer_tag_id

        Cat = self.env["res.partner.category"].sudo()
        tag = Cat.search([("name", "=", "Client Prestashop")], limit=1)
        if not tag:
            legacy = Cat.search([("name", "=", "Client Presta")], limit=1)
            if legacy:
                legacy.write({"name": "Client Prestashop"})
                tag = legacy
            else:
                tag = Cat.create({"name": "Client Prestashop"})

        self.customer_tag_id = tag.id
        return tag

    def _ensure_site_tag(self):
        """Ensure a per-site partner tag exists (e.g. 'PS: Mon Site FR')."""
        self.ensure_one()
        if self.site_tag_id:
            return self.site_tag_id

        # Use hostname from base_url (e.g. "PS: debug.mcdavidian.com")
        host = self.base_url or self.name
        try:
            from urllib.parse import urlparse
            host = urlparse(host).netloc or host
        except Exception:
            pass
        tag_name = f"PS: {host}"
        Cat = self.env["res.partner.category"].sudo()
        tag = Cat.search([("name", "=", tag_name)], limit=1)
        if not tag:
            tag = Cat.create({"name": tag_name})

        self.site_tag_id = tag.id
        return tag

    @staticmethod
    def _norm_email(email: str) -> str:
        return (email or "").strip().lower()


    def _discover_subscription_field(self, model_or_record):
        """Return the One2many subscription field name on mailing.contact, or None."""
        for fname in ("subscription_list_ids", "list_contact_list_ids", "subscription_ids"):
            if fname in model_or_record._fields:
                return fname
        return None

    def _list_subscription(self, mc, list_rec):
        """Return the subscription record linking a mailing contact to a list, or None."""
        fname = self._discover_subscription_field(mc)
        for sub in (mc[fname] if fname else []):
            if sub.list_id.id == list_rec.id:
                return sub
        return None

    def _blacklisted_emails(self, emails):
        """Return set of normalized emails that are blacklisted in Odoo (mail.blacklist)."""
        blacklisted = set()
        try:
            Blacklist = self.env["mail.blacklist"].sudo()
            if emails:
                if "email_normalized" in Blacklist._fields:
                    recs = Blacklist.search([("email_normalized", "in", list(emails))])
                    for r in recs:
                        blacklisted.add(self._norm_email(getattr(r, "email_normalized", None) or r.email))
                else:
                    recs = Blacklist.search([("email", "in", list(emails))])
                    for r in recs:
                        if r.email:
                            blacklisted.add(self._norm_email(r.email))
        except KeyError:
            pass
        return blacklisted

    def _website_label(self) -> str:
        """Return a stable label for this backend's website, based on base_url."""
        self.ensure_one()
        host = ""
        try:
            parsed = urlparse((self.base_url or "").strip())
            host = (parsed.netloc or "").strip().lower()
            if host:
                host = host.split(":", 1)[0]
        except Exception:
            host = ""
        if not host:
            raw = (self.base_url or "").strip().lower()
            raw = raw.replace("https://", "").replace("http://", "")
            host = raw.strip("/")
        return host or (self.name or "PrestaShop")

    def _mailing_list_name(self, consent_type: str) -> str:
        """One Email Marketing list per consent type AND per website/backend."""
        self.ensure_one()
        website = self._website_label()
        if consent_type == "newsletter":
            prefix = "Newsletter Prestashop"
        elif consent_type == "offers":
            prefix = "Offres partenaires Prestashop"
        else:
            prefix = "PrestaShop"
        return f"{prefix} - {website}"

    def _ensure_mailing_list(self, consent_type: str):
        self.ensure_one()
        list_name = self._mailing_list_name(consent_type)

        try:
            MailingList = self.env["mailing.list"].sudo()
        except KeyError:
            raise UserError(_("Email Marketing (mass_mailing) is not installed."))

        domain = [("name", "=", list_name)]
        if "company_id" in MailingList._fields:
            domain = [("name", "=", list_name), ("company_id", "in", [self.company_id.id, False])]

        mlist = MailingList.search(domain, limit=1)
        if not mlist:
            vals = {"name": list_name}
            if "company_id" in MailingList._fields:
                vals["company_id"] = self.company_id.id
            mlist = MailingList.create(vals)
        return mlist

    def _sync_email_marketing_lists(self, client=None, preview=False):
        """Synchronize both consent lists (Newsletter + Partner offers) to Odoo Email Marketing.

        Source of truth: PrestaShop customer flags
        - customers.newsletter == 1  -> subscribed to Newsletter list
        - customers.optin == 1       -> subscribed to Partner Offers list

        Governance / safety:
        - If respect_odoo_opt_out is enabled, we do NOT re-subscribe an email that is globally
          opted-out (mailing.contact.opt_out=True) or globally blacklisted (mail.blacklist).
        - We do remove them from the lists if Presta says they should not be subscribed.
        - We also respect per-list unsubscription in Odoo (the "Désinscription" checkbox on a list line).

        Email-only subscribers (ps_emailsubscription, no customer account) follow the Newsletter list:
        active rows are subscribed, rows deactivated in PrestaShop (active=0) are opted out.
        Rows deleted from PrestaShop are left untouched.
        """
        self.ensure_one()

        # Ensure lists exist
        list_news = self._ensure_mailing_list("newsletter")
        list_offers = self._ensure_mailing_list("offers")

        maps = self.env["prestashop.customer.map"].sudo().search([("backend_id", "=", self.id)])
        partners = maps.mapped("partner_id")
        if not partners:
            return {
                "newsletter": {"subscribe": 0, "unsubscribe": 0, "skipped": 0, "opt_out_skipped": 0, "list_opt_out_skipped": 0},
                "offers": {"subscribe": 0, "unsubscribe": 0, "skipped": 0, "opt_out_skipped": 0, "list_opt_out_skipped": 0},
            }

        if client is None:
            client = self._client()

        # PrestaShop IDs -> partner IDs
        presta_to_partner = {str(m.prestashop_id): m.partner_id.id for m in maps if m.prestashop_id and m.partner_id}

        # news_ok / offers_ok guard against mass unsubscribe when the PS API
        # fetch fails: an empty desired set would opt-out every mapped contact.
        desired_news = set()
        desired_offers = set()
        news_ok = False
        offers_ok = False

        try:
            ids_news = set(client.list_newsletter_customer_ids(
                batch_size=int(self.customer_batch_size or 200),
                include_guests=bool(self.include_guest_customers),
                max_total=int(self.customer_max_per_run or 5000),
            ))
            desired_news = {presta_to_partner[i] for i in ids_news if i in presta_to_partner}
            news_ok = True
        except Exception as e:
            self._log("sync_email_marketing", "error",
                      "Failed to compute Newsletter audience from PrestaShop. Skipping newsletter sync to avoid mass unsubscribe.",
                      details=str(e))

        try:
            ids_off = set(client.list_optin_customer_ids(
                batch_size=int(self.customer_batch_size or 200),
                include_guests=bool(self.include_guest_customers),
                max_total=int(self.customer_max_per_run or 5000),
            ))
            desired_offers = {presta_to_partner[i] for i in ids_off if i in presta_to_partner}
            offers_ok = True
        except Exception as e:
            self._log("sync_email_marketing", "error",
                      "Failed to compute Partner Offers audience from PrestaShop. Skipping offers sync to avoid mass unsubscribe.",
                      details=str(e))

        try:
            MailingContact = self.env["mailing.contact"].sudo()
        except KeyError:
            raise UserError(_("Email Marketing (mass_mailing) is not installed."))
        if "list_ids" not in MailingContact._fields:
            raise UserError(_("Unsupported Email Marketing model: mailing.contact has no list_ids field."))

        # Build deterministic emails we care about
        p_by_email = {}
        for p in partners:
            email = self._norm_email(p.email)
            if email and email not in p_by_email:
                p_by_email[email] = p

        emails = list(p_by_email.keys())

        # Fetch mailing contacts (exact match), then case-insensitive fallback
        existing_mc = MailingContact.search([("email", "in", emails)]) if emails else MailingContact.browse()
        mc_by_email = {self._norm_email(mc.email): mc for mc in existing_mc if mc.email}

        def get_or_create_mc(email: str, partner):
            mc = mc_by_email.get(email)
            if not mc:
                mc = MailingContact.search([("email", "=ilike", email)], limit=1)
                if mc:
                    mc_by_email[email] = mc
            if not mc and not preview:
                name = (partner.name if partner else None) or email
                mc = MailingContact.create({"name": name, "email": email})
                mc_by_email[email] = mc
            return mc

        # ── Email-only subscribers (ps_emailsubscription) ──────────────
        # These are visitors who subscribed via the newsletter footer block
        # without creating a customer account.
        desired_news_emails = set()  # emails (not partner IDs) for email-only subs
        # Rows explicitly deactivated in PS (active=0). Unlike rows that merely
        # vanished, this is a positive signal, so it is safe to act on.
        deactivated_news_emails = set()
        try:
            active_emails, inactive_emails = set(), set()
            for sub in client.list_email_only_subscribers(active_only=False):
                sub_email = self._norm_email(sub.get("email"))
                if sub_email:
                    (active_emails if str(sub.get("active")) == "1" else inactive_emails).add(sub_email)
            # Customer consent is governed by the customer flag, never by this
            # table, so emails of mapped partners are left out of both sets.
            deactivated_news_emails = inactive_emails - active_emails - set(p_by_email)
            desired_news_emails = active_emails - set(p_by_email)
            for sub_email in desired_news_emails:
                p_by_email[sub_email] = None  # No partner for these
            if active_emails:
                self._log("sync_email_marketing", "ok",
                          f"Found {len(active_emails)} email-only subscribers from ps_emailsubscription")
        except Exception as e:
            self._log("sync_email_marketing", "warning",
                      "Failed to fetch email-only subscribers", details=str(e))
        # Update emails list after adding email-only subscribers
        emails = list(p_by_email.keys())
        # ──────────────────────────────────────────────────────────────

        blacklisted_emails = self._blacklisted_emails(emails)
        sub_field_name = self._discover_subscription_field(MailingContact)

        def _is_list_opted_out(mc_rec, list_rec):
            """Check if contact has opt_out=True for a specific list."""
            sub = self._list_subscription(mc_rec, list_rec)
            return sub is not None and bool(getattr(sub, "opt_out", False))

        def is_globally_blocked(email: str, mc_rec=None):
            if email in blacklisted_emails:
                return True
            if mc_rec is not None and self.respect_odoo_opt_out and ("opt_out" in mc_rec._fields) and bool(mc_rec.opt_out):
                return True
            return False

        def sync_one_list(list_rec, desired_partner_ids: set, desired_emails: set = None):
            subscribe_actions = 0
            unsubscribe_actions = 0
            skipped = 0
            opt_out_skipped = 0
            list_opt_out_skipped = 0
            desired_emails = desired_emails or set()

            for email, partner in p_by_email.items():
                want = (partner is not None and partner.id in desired_partner_ids) or (email in desired_emails)
                mc = mc_by_email.get(email)

                if want:
                    mc = get_or_create_mc(email, partner)
                    if not mc:
                        # Preview never creates mc; classify as the real sync would.
                        if preview:
                            if email in blacklisted_emails:
                                opt_out_skipped += 1
                            else:
                                subscribe_actions += 1
                        else:
                            skipped += 1
                        continue

                    if is_globally_blocked(email, mc):
                        opt_out_skipped += 1
                        # Enforce: ensure not subscribed
                        if list_rec in mc.list_ids:
                            if not preview:
                                mc.write({"list_ids": [(3, list_rec.id)]})
                            unsubscribe_actions += 1
                        continue

                    # Respect per-list unsubscription
                    if self.respect_odoo_opt_out and _is_list_opted_out(mc, list_rec):
                        list_opt_out_skipped += 1
                        continue

                    if list_rec not in mc.list_ids:
                        if not preview:
                            mc.write({"list_ids": [(4, list_rec.id)]})
                        subscribe_actions += 1
                    else:
                        skipped += 1

                else:
                    # Ensure unsubscribed
                    if not mc:
                        mc = MailingContact.search([("email", "=ilike", email)], limit=1)
                        if mc:
                            mc_by_email[email] = mc
                    if not mc:
                        continue

                    # Set opt_out on subscription record, or remove from list
                    sub = self._list_subscription(mc, list_rec)
                    if sub is not None and hasattr(sub, "opt_out"):
                        if not sub.opt_out:
                            if not preview:
                                sub.write({"opt_out": True})
                            unsubscribe_actions += 1
                    elif list_rec in mc.list_ids:
                        if not preview:
                            mc.write({"list_ids": [(3, list_rec.id)]})
                        unsubscribe_actions += 1

            return {
                "subscribe": subscribe_actions,
                "unsubscribe": unsubscribe_actions,
                "skipped": skipped,
                "opt_out_skipped": opt_out_skipped,
                "list_opt_out_skipped": list_opt_out_skipped,
            }

        def opt_out_deactivated_email_only():
            """Opt out of the Newsletter list the email-only subs deactivated in PS."""
            if not deactivated_news_emails or not sub_field_name:
                return 0
            contacts = MailingContact.search([("email_normalized", "in", list(deactivated_news_emails))])
            Subscription = self.env[MailingContact._fields[sub_field_name].comodel_name].sudo()
            subs = Subscription.search([
                ("contact_id", "in", contacts.ids),
                ("list_id", "=", list_news.id),
                ("opt_out", "=", False),
            ])
            if subs and not preview:
                subs.write({"opt_out": True})
                self._log("sync_email_marketing", "ok",
                          f"Opted out {len(subs)} email-only subscribers deactivated in PrestaShop")
            return len(subs)

        empty_result = {"subscribe": 0, "unsubscribe": 0, "skipped": 0,
                        "opt_out_skipped": 0, "list_opt_out_skipped": 0, "aborted": True}
        res_news = sync_one_list(list_news, desired_news, desired_news_emails) if news_ok else dict(empty_result)
        res_news["email_only_deactivated"] = opt_out_deactivated_email_only()
        return {
            "newsletter": res_news,
            "offers": sync_one_list(list_offers, desired_offers) if offers_ok else dict(empty_result),
        }

    def _upsert_partner_from_customer_node(self, client, node, prestashop_id, tag, site_tag):
        """Create or update the partner (and its mapping) of a PrestaShop <customer> node.

        Matching: existing mapping first, then email (archived partners included,
        and reactivated). Returns (partner, created).
        """
        self.ensure_one()
        email = client._text(node.find("email"))
        firstname = client._text(node.find("firstname"))
        lastname = client._text(node.find("lastname"))
        active = client._text(node.find("active"))

        CustomerMap = self.env["prestashop.customer.map"].sudo()
        Partner = self.env["res.partner"].sudo().with_context(tracking_disable=True)

        map_rec = CustomerMap.search([
            ("backend_id", "=", self.id),
            ("prestashop_id", "=", prestashop_id),
        ], limit=1)

        partner = map_rec.partner_id if map_rec else False
        if (not partner) and email:
            partner = Partner.with_context(active_test=False).search([("email", "=", email)], limit=1)
            if partner and not partner.active:
                partner.write({"active": True})

        vals = {
            "name": (" ".join([firstname, lastname])).strip() or email or f"PrestaShop Customer {prestashop_id}",
            "email": email or False,
            "active": False if active == "0" else True,
            "customer_rank": 1,
        }

        created = not partner
        if partner:
            partner.write(vals)
            partner.write({"category_id": [(4, tag.id), (4, site_tag.id)]})
        else:
            vals["category_id"] = [(6, 0, [tag.id, site_tag.id])]
            partner = Partner.create(vals)
        if not map_rec:
            CustomerMap.create({
                "backend_id": self.id,
                "prestashop_id": prestashop_id,
                "partner_id": partner.id,
            })
        return partner, created

    def _fetch_and_create_customer_from_webhook(self, prestashop_id: str):
        """Fetch customer from PrestaShop and create/update in Odoo.

        This is a lightweight version of _reimport_customer_by_presta_id()
        optimized for webhook calls (doesn't sync Email Marketing lists,
        returns partner or None instead of raising errors).

        Returns:
            res.partner or None
        """
        self.ensure_one()

        try:
            client = self._client()
            tag = self._ensure_customer_tag()
            site_tag = self._ensure_site_tag()

            node = client.get_customer(str(prestashop_id))
            if node is None:
                self._log("webhook_create_customer", "warning", f"Customer {prestashop_id} not found in PrestaShop")
                return None

            prestashop_id = client._text(node.find("id")) or str(prestashop_id)

            if (not self.include_guest_customers) and client._text(node.find("is_guest")) == "1":
                self._log("webhook_create_customer", "info", f"Customer {prestashop_id} is a guest; skipped")
                return None

            partner, created = self._upsert_partner_from_customer_node(client, node, prestashop_id, tag, site_tag)
            self._log("webhook_create_customer", "ok",
                      f"Customer {prestashop_id} {'created' if created else 'updated'} via webhook")

            return partner

        except Exception as e:
            self._log("webhook_create_customer", "error", f"Failed to create customer {prestashop_id}: {str(e)}")
            return None

    def _apply_webhook_consents(self, payload: dict):
        """Apply consent changes received from a PrestaShop webhook."""
        self.ensure_one()

        email = (payload.get("email") or "").strip().lower()
        if not email:
            self._log("sync_consents", "warning", "Webhook: missing email", details=str(payload))
            return {"status": "error", "message": "missing email"}

        def to_bool(val):
            return str(val).strip().lower() in ("1", "true", "yes", "y")

        newsletter = 1 if to_bool(payload.get("newsletter")) else 0
        optin = 1 if to_bool(payload.get("optin")) else 0

        email_only = payload.get("email_only", False)
        customer_id = (payload.get("customer_id") or "").strip()
        raw_email = payload.get("email") or ""

        Partner = self.env["res.partner"].sudo().with_context(tracking_disable=True, active_test=False)
        partner = None
        renamed_mc = None  # mailing.contact already relocated from old_email to new email

        # Prefer map lookup so a PS-side email change doesn't orphan the partner.
        if customer_id and customer_id != "0":
            map_rec = self.env["prestashop.customer.map"].sudo().search([
                ("backend_id", "=", self.id),
                ("prestashop_id", "=", customer_id),
            ], limit=1)
            if map_rec and map_rec.partner_id:
                partner = map_rec.partner_id
                if not partner.active:
                    partner.write({"active": True})
                old_email = (partner.email or "").strip().lower()
                if old_email and old_email != email:
                    partner.write({"email": raw_email})
                    renamed_mc = self.env["mailing.contact"].sudo().search(
                        [("email", "=", old_email)], limit=1,
                    )
                    if renamed_mc:
                        renamed_mc.write({"email": raw_email})
                    self._log(
                        "sync_consents", "info",
                        f"Partner email updated from PrestaShop: {old_email} -> {email}",
                        details=f"presta_id={customer_id}",
                    )

        if not partner:
            partner = Partner.search([("email", "=ilike", email)], limit=1)
            if partner and not partner.active:
                partner.write({"active": True})

        if not partner and customer_id and customer_id != "0":
            try:
                partner = self._fetch_and_create_customer_from_webhook(customer_id)
            except Exception as e:
                self._log("sync_consents", "error", f"Webhook: failed to create customer {customer_id}", details=str(e))

        if not partner and not email_only:
            self._log("sync_consents", "warning", "Webhook: partner not found and could not be created", details=email)
            return {"status": "skipped", "message": "partner not found"}

        if partner:
            def update_tag(tag, enabled):
                if not tag:
                    return
                if enabled:
                    partner.write({"category_id": [(4, tag.id)]})
                else:
                    partner.write({"category_id": [(3, tag.id)]})

            update_tag(self.newsletter_tag_id, bool(newsletter))
            # The newsletter block only speaks about the newsletter: its webhook
            # carries optin=0 by construction, which is not a revocation.
            if not email_only:
                update_tag(self.partner_offers_tag_id, bool(optin))

            if newsletter and self.newsletter_revoked_tag_id:
                partner.write({"category_id": [(3, self.newsletter_revoked_tag_id.id)]})
            if optin and self.partner_offers_revoked_tag_id:
                partner.write({"category_id": [(3, self.partner_offers_revoked_tag_id.id)]})

        try:
            MailingContact = self.env["mailing.contact"].sudo()
        except KeyError:
            return {"status": "ok", "message": "mailing not installed"}

        if "list_ids" not in MailingContact._fields:
            return {"status": "ok", "message": "mailing model unsupported"}

        list_news = self._ensure_mailing_list("newsletter")
        list_offers = self._ensure_mailing_list("offers")

        mc = renamed_mc or MailingContact.search([("email", "=ilike", email)], limit=1)
        if not mc:
            name = (partner.name if partner else None) or email
            mc = MailingContact.create({"name": name, "email": email})

        globally_blocked = bool(self._blacklisted_emails([email]))
        if self.respect_odoo_opt_out and ("opt_out" in mc._fields) and bool(mc.opt_out):
            globally_blocked = True

        def set_subscription(list_rec, subscribe: bool):
            sub = self._list_subscription(mc, list_rec)
            if subscribe:
                if sub is not None and hasattr(sub, "opt_out") and sub.opt_out:
                    sub.write({"opt_out": False})
                if list_rec not in mc.list_ids:
                    mc.write({"list_ids": [(4, list_rec.id)]})
            else:
                if sub is not None and hasattr(sub, "opt_out"):
                    if not sub.opt_out:
                        sub.write({"opt_out": True})
                elif list_rec in mc.list_ids:
                    mc.write({"list_ids": [(3, list_rec.id)]})


        if globally_blocked:
            set_subscription(list_news, False)
            set_subscription(list_offers, False)
            self._log("sync_consents", "warning", "Webhook blocked by opt-out/blacklist", details=email)
            return {"status": "blocked", "message": "opt-out or blacklist"}

        set_subscription(list_news, bool(newsletter))
        if not email_only:
            set_subscription(list_offers, bool(optin))

        self._log(
            "sync_consents",
            "ok",
            "Webhook consents applied",
            details=f"email={email}, newsletter={newsletter}, optin={optin}",
        )
        return {"status": "ok"}

    def _apply_webhook_address(self, payload):
        """Handle address webhook from PrestaShop.

        Actions:
        - create: Fetch address from PrestaShop and create child partner in Odoo
        - update: Fetch address from PrestaShop and update child partner in Odoo
        - delete: Delete child partner from Odoo via address mapping
        """
        self = self.with_context(tracking_disable=True)
        self.ensure_one()

        action = str(payload.get("action", "")).strip().lower()
        customer_id = str(payload.get("customer_id", "")).strip()
        address_id = str(payload.get("address_id", "")).strip()

        if not customer_id or not address_id:
            self._log("sync_addresses", "warning", "Webhook address: missing customer_id or address_id", details=str(payload))
            return {"status": "error", "message": "missing customer_id or address_id"}

        # For test webhooks with address_id="0", skip processing
        if address_id == "0":
            self._log("sync_addresses", "info", "Webhook address: skipped test address_id=0")
            return {"status": "ok", "message": "test webhook"}

        # Find customer mapping to get parent partner
        customer_map = self.env["prestashop.customer.map"].sudo().search([
            ("backend_id", "=", self.id),
            ("prestashop_id", "=", customer_id),
        ], limit=1)

        if not customer_map:
            self._log("sync_addresses", "warning", f"Webhook address: customer mapping not found for customer_id={customer_id}")
            return {"status": "skipped", "message": "customer not found in mappings"}

        parent_partner = customer_map.partner_id
        if not parent_partner:
            self._log("sync_addresses", "warning", f"Webhook address: parent partner not found for customer_id={customer_id}")
            return {"status": "skipped", "message": "parent partner not found"}

        # Handle delete action
        if action == "delete":
            address_map = self.env["prestashop.address.map"].sudo().search([
                ("backend_id", "=", self.id),
                ("prestashop_id", "=", address_id),
            ], limit=1)

            if address_map:
                address_partner = address_map.address_partner_id
                address_map.sudo().unlink()
                if address_partner:
                    address_partner.sudo().unlink()
                self._log("sync_addresses", "ok", f"Webhook address deleted: address_id={address_id}")
                return {"status": "ok", "message": "address deleted"}
            else:
                self._log("sync_addresses", "info", f"Webhook address: address_id={address_id} not found for deletion")
                return {"status": "ok", "message": "address not found"}

        # Handle create/update actions
        if action in ("create", "update"):
            try:
                client = self._client()

                # Fetch address from PrestaShop
                addr_node = client.get_address(address_id)
                if addr_node is None:
                    self._log("sync_addresses", "warning", f"Webhook address: address_id={address_id} not found in PrestaShop")
                    return {"status": "skipped", "message": "address not found in PrestaShop"}

                # Build country/state cache for this single address
                country_cache = {}
                state_cache = {}

                # Process the address
                vals = self._vals_from_presta_address(client, addr_node, parent_partner, country_cache, state_cache)
                if not vals:
                    self._log("sync_addresses", "warning", f"Webhook address: could not build vals for address_id={address_id}")
                    return {"status": "error", "message": "could not build address values"}

                # Check if address mapping exists
                address_map = self.env["prestashop.address.map"].sudo().search([
                    ("backend_id", "=", self.id),
                    ("prestashop_id", "=", address_id),
                ], limit=1)

                if address_map:
                    # Update existing address
                    address_partner = address_map.address_partner_id
                    if address_partner:
                        address_partner.sudo().with_context(tracking_disable=True).write(vals)
                        self._log("sync_addresses", "ok", f"Webhook address updated: address_id={address_id}")
                        return {"status": "ok", "message": "address updated"}
                    else:
                        # Mapping exists but partner was deleted - recreate
                        address_partner = self.env["res.partner"].sudo().with_context(tracking_disable=True).create(vals)
                        address_map.sudo().write({"address_partner_id": address_partner.id})
                        self._log("sync_addresses", "ok", f"Webhook address recreated: address_id={address_id}")
                        return {"status": "ok", "message": "address recreated"}
                else:
                    # No mapping yet — try to find an existing child address to update
                    # instead of creating a duplicate.
                    sig = self._address_signature(vals)
                    existing_children = self.env["res.partner"].sudo().search([
                        ("parent_id", "=", parent_partner.id),
                        ("type", "=", "delivery"),
                    ])
                    matched_child = False
                    for child in existing_children:
                        if self._address_signature_of_partner(child) == sig:
                            matched_child = child
                            break

                    if matched_child:
                        # Found matching child — link and update
                        matched_child.sudo().with_context(tracking_disable=True).write(vals)
                        self.env["prestashop.address.map"].sudo().create({
                            "backend_id": self.id,
                            "prestashop_id": address_id,
                            "address_partner_id": matched_child.id,
                            "parent_partner_id": parent_partner.id,
                        })
                        self._log("sync_addresses", "ok", f"Webhook address linked to existing child: address_id={address_id}")
                        return {"status": "ok", "message": "address linked and updated"}

                    # No match found — create new address
                    address_partner = self.env["res.partner"].sudo().with_context(tracking_disable=True).create(vals)
                    self.env["prestashop.address.map"].sudo().create({
                        "backend_id": self.id,
                        "prestashop_id": address_id,
                        "address_partner_id": address_partner.id,
                        "parent_partner_id": parent_partner.id,
                    })
                    self._log("sync_addresses", "ok", f"Webhook address created: address_id={address_id}")
                    return {"status": "ok", "message": "address created"}

            except Exception as e:
                self._log("sync_addresses", "error", f"Webhook address failed for address_id={address_id}", details=str(e))
                return {"status": "error", "message": str(e)}

        # Unknown action
        self._log("sync_addresses", "warning", f"Webhook address: unknown action={action}")
        return {"status": "error", "message": f"unknown action: {action}"}

    def _opted_out_emails(self, list_rec, emails):
        """Return the normalized emails explicitly opted out of a mailing list."""
        MailingContact = self.env["mailing.contact"].sudo()
        fname = self._discover_subscription_field(MailingContact)
        if not fname or not emails:
            return set()
        Subscription = self.env[MailingContact._fields[fname].comodel_name].sudo()
        subs = Subscription.search([
            ("list_id", "=", list_rec.id),
            ("opt_out", "=", True),
            ("contact_id.email_normalized", "in", list(emails)),
        ])
        return {self._norm_email(sub.contact_id.email_normalized) for sub in subs}

    def _push_opt_outs_to_prestashop(self, client, preview=False, enforce_cap=True):
        """Push Odoo-side consent revocations to PrestaShop.

        Revocation-only, and only on a positive signal (see consent_rules):
        - email blacklisted in Odoo (mail.blacklist) -> newsletter=0 and optin=0
        - subscription to the Newsletter list opted out -> newsletter=0
        - subscription to the Partner Offers list opted out -> optin=0
        A contact merely absent from an Odoo list is never unsubscribed, and nothing
        is sent for a consent PrestaShop already has at 0.

        Email-only subscribers (ps_emailsubscription) are deactivated through the
        prestashopodoo module endpoint under the same rules.

        preview: compute the plan without calling PrestaShop.
        enforce_cap: refuse to apply more than opt_out_push_max_per_run revocations
        (automatic runs); the manual button passes False.

        Returns a dict: customers / email_only (planned revocations), updated /
        email_only_unsub (applied), errors, aborted.
        """
        self.ensure_one()
        operation = "sync_consents_odoo_to_prestashop"
        stats = {"customers": 0, "email_only": 0, "updated": 0, "email_only_unsub": 0, "errors": 0, "aborted": False}

        if "mailing.contact" not in self.env:
            raise UserError(_("Email Marketing (mass_mailing) is not installed."))

        maps = self.env["prestashop.customer.map"].sudo().search([("backend_id", "=", self.id)])
        customer_emails = {}
        for m in maps:
            email = self._norm_email(m.partner_id.email)
            if email:
                customer_emails[str(m.prestashop_id)] = email

        # Current PrestaShop state. A failed fetch leaves the set empty, so nothing
        # is pushed for that consent in this run.
        presta_news_ids = set()
        presta_offers_ids = set()
        if customer_emails:
            fetch_args = dict(
                batch_size=int(self.customer_batch_size or 200),
                include_guests=bool(self.include_guest_customers),
                max_total=int(self.customer_max_per_run or 5000),
            )
            try:
                presta_news_ids = set(client.list_newsletter_customer_ids(**fetch_args))
            except Exception as e:
                self._log(operation, "warning", "Failed to fetch newsletter subscribers from PrestaShop", details=str(e))
            try:
                presta_offers_ids = set(client.list_optin_customer_ids(**fetch_args))
            except Exception as e:
                self._log(operation, "warning", "Failed to fetch optin subscribers from PrestaShop", details=str(e))

        # Email-only subscribers live in ps_emailsubscription (no customer account).
        email_only_active = {
            self._norm_email(sub.get("email"))
            for sub in client.list_email_only_subscribers()
            if sub.get("email")
        }

        emails = set(customer_emails.values()) | email_only_active
        if not emails:
            return stats

        revoked_news = self._opted_out_emails(self._ensure_mailing_list("newsletter"), emails)
        revoked_offers = self._opted_out_emails(self._ensure_mailing_list("offers"), emails)
        blacklisted = self._blacklisted_emails(list(emails))

        customer_plan = consent_rules.plan_customer_revocations(
            customer_emails, presta_news_ids, presta_offers_ids, revoked_news, revoked_offers, blacklisted)
        email_only_plan = consent_rules.plan_email_only_revocations(email_only_active, revoked_news, blacklisted)
        stats["customers"] = len(customer_plan)
        stats["email_only"] = len(email_only_plan)
        total = consent_rules.count_revocations(customer_plan, email_only_plan)

        if preview or not total:
            return stats

        cap = int(self.opt_out_push_max_per_run or 0)
        if enforce_cap and consent_rules.exceeds_cap(total, cap):
            stats["aborted"] = True
            self._log(
                operation, "error",
                f"Odoo->PrestaShop push aborted: {total} revocations exceed the limit of {cap} per automatic run.",
                details="Check the volume with the Preview button, then apply with the 'Odoo → Presta' button "
                        f"(not limited). customers={len(customer_plan)}; email_only={len(email_only_plan)}",
            )
            return stats

        for customer_id, (newsletter, optin) in customer_plan.items():
            try:
                client.update_customer_consents(customer_id, newsletter=newsletter, optin=optin)
                stats["updated"] += 1
            except Exception as e:
                stats["errors"] += 1
                self._log(operation, "error", "Failed to sync consents to PrestaShop.",
                          details=str(e), prestashop_id=customer_id)

        for email in email_only_plan:
            result = client.unsubscribe_email_only_subscriber(email)
            if result and result.get("status") == "ok":
                stats["email_only_unsub"] += 1
            elif result and result.get("status") == "noop":
                # Already inactive — fine
                pass
            else:
                stats["errors"] += 1
                self._log(operation, "error", "Failed to unsubscribe email-only subscriber.",
                          details=f"email={email} result={result!r}")

        self._log(
            operation,
            "ok" if stats["errors"] == 0 else "warning",
            (
                f"Odoo->PrestaShop consents sync done. updated_customers={stats['updated']}; "
                f"email_only_unsub={stats['email_only_unsub']}; errors={stats['errors']}"
            ),
        )
        return stats

    def action_preview_consents(self):
        for backend in self:
            def run():
                client = backend._client()
                res = backend._sync_email_marketing_lists(client=client, preview=True)
                msg = (
                    f"Preview: Newsletter subscribe={res['newsletter']['subscribe']}, unsubscribe={res['newsletter']['unsubscribe']}, "
                    f"email_only_deactivated={res['newsletter'].get('email_only_deactivated', 0)}, "
                    f"opt_out_skipped={res['newsletter']['opt_out_skipped']}, list_opt_out_skipped={res['newsletter'].get('list_opt_out_skipped', 0)} | "
                    f"Offers subscribe={res['offers']['subscribe']}, unsubscribe={res['offers']['unsubscribe']}, "
                    f"opt_out_skipped={res['offers']['opt_out_skipped']}, list_opt_out_skipped={res['offers'].get('list_opt_out_skipped', 0)}"
                )
                push = backend._push_opt_outs_to_prestashop(client, preview=True)
                msg += f" | Odoo → Presta would revoke: customers={push['customers']}, email_only={push['email_only']}"
                backend._log("preview_consents", "ok", msg)
                return msg
            msg = backend._run_locked("preview_consents", run)
        return self._notification(msg)

    def action_sync_consents(self):
        for backend in self:
            def run():
                start = time.perf_counter()
                client = backend._client()
                res = backend._sync_email_marketing_lists(client=client, preview=False)
                backend.last_consents_sync = fields.Datetime.now()
                dur = time.perf_counter() - start
                msg = (
                    f"Consents synced. Newsletter subscribe={res['newsletter']['subscribe']}, unsubscribe={res['newsletter']['unsubscribe']}, "
                    f"email_only_deactivated={res['newsletter'].get('email_only_deactivated', 0)} "
                    f"(opt_out_skipped={res['newsletter']['opt_out_skipped']}, list_opt_out_skipped={res['newsletter'].get('list_opt_out_skipped', 0)}) | "
                    f"Offers subscribe={res['offers']['subscribe']}, unsubscribe={res['offers']['unsubscribe']} "
                    f"(opt_out_skipped={res['offers']['opt_out_skipped']}, list_opt_out_skipped={res['offers'].get('list_opt_out_skipped', 0)})"
                )
                backend._log("sync_consents", "ok", msg, duration_sec=dur)
                return msg
            msg = backend._run_locked("sync_consents", run)
        return self._notification(msg)

    def action_push_opt_outs_to_prestashop(self):
        """Sync consents from Odoo to PrestaShop (revocation-only).

        This is the complementary action to the 'Sync Consents PrestaShop -> Odoo' button.
        We never push a subscription (0 -> 1) to PrestaShop from Odoo; only revocations.
        """
        msg = ""
        for backend in self:
            def run():
                client = backend._client()
                stats = backend._push_opt_outs_to_prestashop(client, enforce_cap=False)
                return (
                    f"Consents synced to PrestaShop: updated={stats['updated']}, "
                    f"email_only_unsub={stats['email_only_unsub']}, errors={stats['errors']}"
                )
            msg = backend._run_locked("sync_consents_odoo_to_prestashop", run)

        return self._notification(msg)

    def action_import_customers(self):
        msg = ""
        for backend in self:
            def run():
                start = time.perf_counter()
                result = backend._import_customers()
                dur = time.perf_counter() - start
                stats = result if isinstance(result, dict) else {}
                created = stats.get("created", 0)
                updated = stats.get("updated", 0)
                errors = stats.get("errors", 0)
                retagged = stats.get("retagged", 0)
                backend._log("import_customers", "ok", "Customer import finished.", duration_sec=dur)
                parts = []
                if created:
                    parts.append(f"{created} created")
                if updated:
                    parts.append(f"{updated} updated")
                if retagged:
                    parts.append(f"{retagged} retagged")
                if errors:
                    parts.append(f"{errors} errors")
                if not parts:
                    return _("Customer import finished. No new customers.")
                return _("Customer import finished: %s.") % ", ".join(parts)
            msg = backend._run_locked("import_customers", run)
        return self._notification(msg or _("Customer import finished."))

    def action_open_reimport_customer_wizard(self):
        """Open a small wizard that reimports a single customer by PrestaShop ID.

        This is useful when a user deleted a partner in Odoo (or the mapping was lost) and
        wants to bring that customer back without resetting the incremental cursor.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reimport Customer by Presta ID"),
            "res_model": "prestashop.reimport.customer.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_backend_id": self.id},
        }

    def action_sync_addresses(self):
        msg = ""
        for backend in self:
            def run():
                stats = backend._sync_addresses_batch(reset_cursor=False)
                # _sync_addresses_batch already logs; here we only craft a user-facing message.
                if stats.get("completed"):
                    return _("Addresses synced (full scan complete).")
                return _(
                    "Address sync batch done. Click 'Sync Addresses' again to continue (cursor: %(cursor)s)."
                ) % {"cursor": stats.get("cursor_map_id") or 0}
            msg = backend._run_locked("sync_addresses", run)
        return self._notification(msg)

    @api.model
    def _cron_full_scan_addresses_weekly(self):
        """Weekly full scan of addresses.

        This resets the address cursor and runs address sync batches until completion
        (or until a safety number of batches is reached).
        """
        backends = self.search([])
        for backend in backends:
            try:
                def run():
                    backend.address_sync_cursor_map_id = 0
                    batches = 0
                    last_stats = {}
                    # Safety cap: avoid very long cron runs.
                    while batches < 25:
                        last_stats = backend._sync_addresses_batch(reset_cursor=False)
                        batches += 1
                        if last_stats.get("completed"):
                            break
                        # If nothing processed, stop to avoid an infinite loop.
                        if not last_stats.get("processed_customers") and not last_stats.get("processed_addresses"):
                            break
                    backend.address_full_scan_next_run = fields.Datetime.now() + relativedelta(weeks=1)
                    backend._log(
                        "sync_addresses",
                        "ok",
                        f"Weekly address full scan run. batches={batches}, completed={bool(last_stats.get('completed'))}",
                    )
                    return True
                backend._run_locked("sync_addresses", run)
            except UserError:
                # Another run is already in progress; skip silently.
                continue

    def _country_id_from_presta(self, client, presta_country_id, cache):
        if not presta_country_id:
            return False
        if presta_country_id in cache:
            return cache[presta_country_id]
        country_id = False
        try:
            country = client.get_country(presta_country_id)
            if country is not None:
                iso = client._text(country.find("iso_code"))
                if iso:
                    rec = self.env["res.country"].sudo().search([("code", "=", iso.upper())], limit=1)
                    country_id = rec.id if rec else False
                    if not country_id:
                        _logger.warning(f"Country ISO {iso} not found in Odoo for PrestaShop country_id={presta_country_id}")
                else:
                    _logger.warning(f"No iso_code in PrestaShop country_id={presta_country_id}")
            else:
                _logger.warning(f"PrestaShop country_id={presta_country_id} returned None")
        except Exception as e:
            _logger.error(f"Error fetching country {presta_country_id}: {e}", exc_info=True)
            country_id = False
        cache[presta_country_id] = country_id
        return country_id

    def _state_id_from_presta(self, client, presta_state_id, country_id, cache):
        """Map PrestaShop state id to res.country.state.

        Best effort: try iso_code first, then name.
        """
        if not presta_state_id or not country_id:
            return False
        key = (str(prestashop_id := presta_state_id), int(country_id))
        if key in cache:
            return cache[key]
        state_rec_id = False
        try:
            st = client.get_state(str(prestashop_id))
            if st is not None:
                iso = (client._text(st.find("iso_code")) or "").strip()
                name = (client._text(st.find("name")) or "").strip()
                State = self.env["res.country.state"].sudo()
                if iso:
                    rec = State.search([("country_id", "=", country_id), ("code", "=", iso.upper())], limit=1)
                    if rec:
                        state_rec_id = rec.id
                if not state_rec_id and name:
                    rec = State.search([("country_id", "=", country_id), ("name", "=ilike", name)], limit=1)
                    state_rec_id = rec.id if rec else False
                if not state_rec_id:
                    _logger.warning(f"State not found in Odoo: iso={iso}, name={name}, country_id={country_id}, presta_state_id={presta_state_id}")
            else:
                _logger.warning(f"PrestaShop state_id={presta_state_id} returned None")
        except Exception as e:
            _logger.error(f"Error fetching state {presta_state_id}: {e}", exc_info=True)
            state_rec_id = False
        cache[key] = state_rec_id
        return state_rec_id

    def _clean_str(self, s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    def _normalize_phone(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        # Keep '+' and digits; drop separators
        keep = "+" if s.startswith("+") else ""
        digits = re.sub(r"\D", "", s)
        return keep + digits

    def _address_signature(self, vals: dict) -> tuple:
        """Signature used to deduplicate identical child addresses under the same parent."""
        return (
            self._clean_str(vals.get("street")),
            self._clean_str(vals.get("street2")),
            self._clean_str(vals.get("zip")),
            self._clean_str(vals.get("city")),
            int(vals.get("country_id") or 0),
            int(vals.get("state_id") or 0),
            self._normalize_phone(vals.get("phone")),
            self._normalize_phone(vals.get("mobile")),
            self._clean_str(vals.get("company")),
        )

    def _address_signature_of_partner(self, partner) -> tuple:
        """Signature of an existing child address, comparable with _address_signature(vals)."""
        return self._address_signature({
            "street": partner.street,
            "street2": partner.street2,
            "zip": partner.zip,
            "city": partner.city,
            "country_id": partner.country_id.id if partner.country_id else False,
            "state_id": partner.state_id.id if partner.state_id else False,
            "phone": partner.phone,
            "mobile": partner.mobile,
            "company": partner.commercial_company_name or partner.company_name or partner.name,
        })

    def _vals_from_presta_address(self, client, addr_node, parent_partner, country_cache, state_cache):
        firstname = client._text(addr_node.find("firstname"))
        lastname = client._text(addr_node.find("lastname"))
        company = client._text(addr_node.find("company"))
        alias = client._text(addr_node.find("alias"))

        street = client._text(addr_node.find("address1"))
        street2 = client._text(addr_node.find("address2"))
        zip_code = client._text(addr_node.find("postcode"))
        city = client._text(addr_node.find("city"))
        phone = client._text(addr_node.find("phone"))
        mobile = client._text(addr_node.find("phone_mobile"))
        presta_country_id = client._text(addr_node.find("id_country"))
        presta_state_id = client._text(addr_node.find("id_state"))

        country_id = self._country_id_from_presta(client, presta_country_id, country_cache)
        state_id = self._state_id_from_presta(client, presta_state_id, country_id, state_cache) if country_id else False

        # We purposely do NOT force invoice/delivery types yet; we will assign later based on orders.
        name_parts = []
        if alias:
            name_parts.append(alias)
        if company:
            name_parts.append(company)
        full_name = (" ".join([firstname, lastname])).strip()
        if full_name and full_name not in name_parts:
            name_parts.append(full_name)
        if not name_parts:
            name_parts.append(parent_partner.name or "Address")

        vals = {
            "name": " - ".join([p for p in name_parts if p])[:255],
            "type": "delivery",
            "parent_id": parent_partner.id,
            "street": street or False,
            "street2": street2 or False,
            "zip": zip_code or False,
            "city": city or False,
            "phone": self._normalize_phone(phone) or False,
            "mobile": self._normalize_phone(mobile) or False,
        }
        if country_id:
            vals["country_id"] = country_id
        if state_id:
            vals["state_id"] = state_id
        # Keep company alignment if the field exists.
        if "company_id" in self.env["res.partner"]._fields:
            vals["company_id"] = self.company_id.id
        return vals

    def _sync_addresses(self):
        """Backward compatible wrapper."""
        self.ensure_one()
        self._sync_addresses_batch(reset_cursor=False)
        return True

    def _sync_addresses_batch(self, reset_cursor: bool = False):
        """Import/sync customer addresses as child partners in batches.

        Key point: this method uses a cursor (address_sync_cursor_map_id) so repeated runs
        continue where the previous run stopped.

        Returns a dict with statistics, including whether the full scan is completed.
        """
        self = self.with_context(tracking_disable=True)
        self.ensure_one()
        client = self._client()

        CustomerMap = self.env["prestashop.customer.map"].sudo()
        if reset_cursor:
            self.address_sync_cursor_map_id = 0

        max_customers = int(self.address_max_customers_per_run or 0) or 500
        max_addresses = int(self.address_max_addresses_per_run or 0) or 2000

        cursor = int(self.address_sync_cursor_map_id or 0)

        domain = [("backend_id", "=", self.id)]
        if cursor:
            domain.append(("id", ">", cursor))
        maps = CustomerMap.search(domain, order="id asc", limit=max_customers)

        # If we reached the end, finalize the full scan.
        if not maps:
            self.address_sync_cursor_map_id = 0
            self.last_address_sync = fields.Datetime.now()
            self._log("sync_addresses", "ok", "Addresses synced. Full scan complete.")
            return {
                "completed": True,
                "cursor_map_id": 0,
                "processed_customers": 0,
                "processed_addresses": 0,
            }

        AddressMap = self.env["prestashop.address.map"].sudo()
        Partner = self.env["res.partner"].sudo().with_context(tracking_disable=True)
        chunk_size = int(self.address_customer_chunk_size or 0) or 50

        created = 0
        updated = 0
        linked = 0
        skipped = 0
        errors = 0
        processed_customers = 0
        processed_addresses = 0

        # Track the last fully processed customer map id to avoid skipping customers
        # when we hit max_addresses in the middle of a batch.
        last_completed_map_id = 0

        country_cache = {}
        state_cache = {}
        child_sig_cache_by_parent = {}

        maps_by_customer_id = {str(m.prestashop_id): m for m in maps}
        customer_ids = list(maps_by_customer_id.keys())

        def chunks(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]

        def get_sig_cache(parent_partner_id):
            if parent_partner_id in child_sig_cache_by_parent:
                return child_sig_cache_by_parent[parent_partner_id]
            sig_map = {}
            children = Partner.search([("parent_id", "=", parent_partner_id)])
            for c in children:
                sig_map[self._address_signature_of_partner(c)] = c
            child_sig_cache_by_parent[parent_partner_id] = sig_map
            return sig_map

        def process_one_address(cm, addr_node):
            nonlocal created, updated, linked, skipped, errors, processed_addresses
            aid = ""
            try:
                aid = client._text(addr_node.find("id")) or (addr_node.get("id") or "").strip()
                if not aid:
                    href = addr_node.get("{http://www.w3.org/1999/xlink}href") or addr_node.get("xlink:href") or ""
                    href = (href or "").strip()
                    if href:
                        aid = href.rstrip("/").split("/")[-1]

                addr = addr_node
                if addr is None or addr.find("address1") is None:
                    addr = client.get_address(aid)
                if addr is None:
                    skipped += 1
                    return
                if client._text(addr.find("deleted")) == "1":
                    skipped += 1
                    return

                existing = AddressMap.search([
                    ("backend_id", "=", self.id),
                    ("prestashop_id", "=", str(aid)),
                ], limit=1)

                vals = self._vals_from_presta_address(client, addr, cm.partner_id, country_cache, state_cache)
                sig = self._address_signature(vals)

                if existing and existing.address_partner_id:
                    existing.address_partner_id.sudo().with_context(tracking_disable=True).write(vals)
                    if existing.parent_partner_id != cm.partner_id:
                        existing.sudo().with_context(tracking_disable=True).write({"parent_partner_id": cm.partner_id.id})
                    updated += 1
                    processed_addresses += 1
                    return

                # No existing mapping: optionally deduplicate under parent
                if self.address_deduplicate:
                    sig_cache = get_sig_cache(cm.partner_id.id)
                    child = sig_cache.get(sig)
                    if child:
                        # Link mapping to existing identical child
                        AddressMap.create({
                            "backend_id": self.id,
                            "prestashop_id": str(aid),
                            "address_partner_id": child.id,
                            "parent_partner_id": cm.partner_id.id,
                        })
                        linked += 1
                        processed_addresses += 1
                        return

                child = Partner.create(vals)
                AddressMap.create({
                    "backend_id": self.id,
                    "prestashop_id": str(aid),
                    "address_partner_id": child.id,
                    "parent_partner_id": cm.partner_id.id,
                })
                if self.address_deduplicate:
                    get_sig_cache(cm.partner_id.id)[sig] = child
                created += 1
                processed_addresses += 1
            except Exception as e:
                errors += 1
                self._log("sync_addresses", "error", "Failed to sync address", details=str(e), prestashop_id=str(aid))

        # Try batch fetch addresses for multiple customers (fast path). If unsupported, fallback to per customer.
        batch_supported = True
        for cid_chunk in chunks(customer_ids, chunk_size):
            if processed_addresses >= max_addresses:
                break
            # We'll increment processed_customers as we effectively process customers.

            addresses_by_customer = {}
            if batch_supported:
                try:
                    addresses_by_customer = client.list_addresses_for_customers(cid_chunk, batch_size=500, max_total=0)
                except Exception:
                    batch_supported = False
                    addresses_by_customer = {}

            if batch_supported and addresses_by_customer:
                for cid in cid_chunk:
                    if processed_addresses >= max_addresses:
                        break
                    cm = maps_by_customer_id.get(str(cid))
                    if not cm:
                        continue
                    processed_customers += 1
                    for addr_node in addresses_by_customer.get(str(cid), []):
                        if processed_addresses >= max_addresses:
                            break
                        process_one_address(cm, addr_node)
                    # Mark customer as completed for cursor advancement.
                    last_completed_map_id = cm.id
            else:
                # Fallback: one API call per customer
                for cid in cid_chunk:
                    if processed_addresses >= max_addresses:
                        break
                    cm = maps_by_customer_id.get(str(cid))
                    if not cm:
                        continue
                    processed_customers += 1
                    try:
                        addr_nodes = client.list_addresses_for_customer(cm.prestashop_id, batch_size=200, max_total=max_addresses)
                        for addr_node in (addr_nodes or []):
                            if processed_addresses >= max_addresses:
                                break
                            process_one_address(cm, addr_node)
                        last_completed_map_id = cm.id
                    except Exception as e:
                        errors += 1
                        self._log("sync_addresses", "error", "Failed to sync customer addresses", details=str(e), prestashop_id=str(cm.prestashop_id))

        # Move cursor forward to the last completed customer.
        # IMPORTANT: do NOT jump to maps[-1] when we stopped early due to max_addresses.
        if last_completed_map_id:
            self.address_sync_cursor_map_id = last_completed_map_id
        else:
            # Nothing processed (e.g., max_addresses is 0) -> keep cursor unchanged.
            last_completed_map_id = cursor

        # Are there more customers after this batch?
        has_more = bool(CustomerMap.search_count([("backend_id", "=", self.id), ("id", ">", last_completed_map_id)]))
        completed = not has_more
        if completed:
            self.address_sync_cursor_map_id = 0
            self.last_address_sync = fields.Datetime.now()

        status = "ok" if errors == 0 else ("warning" if (created or updated or linked) else "error")
        self._log(
            "sync_addresses",
            status,
            (
                f"Addresses synced (batch). customers={processed_customers}, addresses={processed_addresses}, "
                f"created={created}, linked={linked}, updated={updated}, skipped={skipped}, errors={errors}, "
                f"cursor_map_id={0 if completed else last_completed_map_id}, completed={completed}"
            ),
        )

        return {
            "completed": completed,
            "cursor_map_id": 0 if completed else last_completed_map_id,
            "processed_customers": processed_customers,
            "processed_addresses": processed_addresses,
            "created": created,
            "linked": linked,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    def _reimport_customer_by_presta_id(self, prestashop_customer_id: int) -> str:
        """Reimport a single customer by PrestaShop ID.

        Unlike the regular customer import (incremental by last_customer_presta_id),
        this function targets a specific customer and will recreate the mapping/partner
        if it was deleted.

        Note: We only manage the partner tag 'Client Prestashop'. Marketing consents are
        handled via Email Marketing lists (Newsletter + Partner Offers).

        Returns a human-readable message.
        """
        self.ensure_one()

        prestashop_customer_id = int(prestashop_customer_id or 0)
        if prestashop_customer_id <= 0:
            raise UserError(_("Invalid PrestaShop customer ID."))

        client = self._client()
        tag = self._ensure_customer_tag()
        site_tag = self._ensure_site_tag()

        node = client.get_customer(str(prestashop_customer_id))
        if node is None:
            raise UserError(_("PrestaShop customer %s not found.") % prestashop_customer_id)

        prestashop_id = client._text(node.find("id")) or str(prestashop_customer_id)
        if (not self.include_guest_customers) and client._text(node.find("is_guest")) == "1":
            self._log(
                "import_customers",
                "warning",
                f"Customer {prestashop_id} is a guest; skipped (include_guest_customers=False).",
                prestashop_id=prestashop_id,
            )
            return _("Customer %s is a guest; skipped.") % prestashop_id

        partner, was_created = self._upsert_partner_from_customer_node(client, node, prestashop_id, tag, site_tag)
        created = int(was_created)
        updated = int(not was_created)

        self._log(
            "import_customers",
            "ok",
            f"Customer reimported by ID. created={created}, updated={updated}",
            prestashop_id=prestashop_id,
        )

        # Refresh Email Marketing lists (optional, but keeps Odoo aligned)
        try:
            self._sync_email_marketing_lists(client=client, preview=False)
        except Exception:
            pass

        return _("Customer %(id)s reimported. created=%(created)s, updated=%(updated)s.") % {
            "id": prestashop_id, "created": created, "updated": updated,
        }

    def _import_customers(self):
        self = self.with_context(tracking_disable=True)
        self.ensure_one()
        client = self._client()
        tag = self._ensure_customer_tag()
        site_tag = self._ensure_site_tag()

        # Use id-based incremental import (most compatible with PrestaShop 1.7 Webservice).
        try:
            customers = client.list_customers_incremental(
                after_id=self.last_customer_presta_id or 0,
                batch_size=self.customer_batch_size or 200,
                include_guests=self.include_guest_customers,
                max_total=self.customer_max_per_run or 5000,
            )
        except PrestaShopAPIError as e:
            self._log("import_customers", "error", "Failed to list customers", details=str(e))
            raise UserError(_("PrestaShop customer import failed: %s") % e)

        created = 0
        updated = 0
        skipped = 0
        errors = 0

        max_seen_id = int(self.last_customer_presta_id or 0)

        for node in customers:
            prestashop_id = None
            try:
                prestashop_id = client._text(node.find("id"))
                try:
                    max_seen_id = max(max_seen_id, int(prestashop_id or 0))
                except Exception:
                    pass
                if (not self.include_guest_customers) and client._text(node.find("is_guest")) == "1":
                    skipped += 1
                    continue

                _partner, was_created = self._upsert_partner_from_customer_node(client, node, prestashop_id, tag, site_tag)
                if was_created:
                    created += 1
                else:
                    updated += 1

            except Exception as e:
                errors += 1
                self._log(
                    "import_customers",
                    "error",
                    "Failed to import customer",
                    details=str(e),
                    prestashop_id=prestashop_id,
                )

        self.last_customer_sync = fields.Datetime.now()
        if max_seen_id > int(self.last_customer_presta_id or 0):
            self.last_customer_presta_id = max_seen_id

        # Ensure ALL mapped customers have the tag (fixes missing tags after tag recreation,
        # or customers imported before tag feature existed).
        retagged = 0
        if tag:
            try:
                all_maps = self.env["prestashop.customer.map"].sudo().search([("backend_id", "=", self.id)])
                for m in all_maps:
                    if m.partner_id and tag.id not in m.partner_id.category_id.ids:
                        m.partner_id.sudo().write({"category_id": [(4, tag.id)]})
                        retagged += 1
            except Exception as e:
                self._log("import_customers", "warning", "Failed to re-tag existing customers", details=str(e))

        # Push audiences into Email Marketing (2 lists: newsletter + partner offers)
        try:
            self._sync_email_marketing_lists(client=client, preview=False)
        except Exception as e:
            # Never block customer import because of Email Marketing sync.
            self._log("sync_email_marketing", "warning", "Failed to sync Email Marketing", details=str(e))

        self._log(
            "import_customers",
            "ok",
            f"Customers synced. created={created}, updated={updated}, skipped={skipped}, errors={errors}, retagged={retagged}",
        )
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "retagged": retagged,
        }


    def _parse_paid_state_ids(self):
        self.ensure_one()
        if not self.paid_state_ids:
            return set()
        return {s.strip() for s in self.paid_state_ids.split(",") if s.strip()}

    def _get_pricelist(self, partner):
        """Return a pricelist to use for sale order creation."""
        self.ensure_one()
        if self.pricelist_id:
            return self.pricelist_id
        # In Odoo 17, the default pricelist is typically stored on the partner.
        pl = getattr(partner, "property_product_pricelist", False)
        if pl:
            return pl
        return self.env["product.pricelist"].search(
            [("company_id", "in", [self.company_id.id, False])],
            limit=1,
        )

    def _import_orders(self):
        self.ensure_one()
        client = self._client()

        # Many PrestaShop 1.7 shops do NOT allow filtering orders by date_add via Webservice.
        # We therefore use an id-based incremental strategy.
        start_id = int(self.last_order_presta_id or 0)
        batch_size = int(self.order_batch_size or 200)
        max_total = int(self.order_max_per_run or 500)
        max_total = max(1, max_total)

        try:
            if start_id > 0:
                orders = client.list_orders_incremental(after_id=start_id, batch_size=batch_size, max_total=max_total)
                mode_details = f"incremental id>{start_id}"
            else:
                # First run: import the latest N orders (by id) as a sensible default.
                # This approximates a "recent orders" sync without requiring date filters.
                orders = client.list_orders_latest(limit=max_total)
                orders = list(reversed(orders))
                mode_details = f"latest {max_total} orders"
        except PrestaShopAPIError as e:
            self._log("import_orders", "error", "Failed to list orders", details=str(e))
            raise UserError(_("PrestaShop order import failed: %s") % e)

        paid_state_ids = self._parse_paid_state_ids()
        imported = 0
        skipped = 0
        errors = 0

        max_seen_id = start_id

        for order_node in orders:
            prestashop_id = None
            try:
                prestashop_id = client._text(order_node.find("id"))
                try:
                    max_seen_id = max(max_seen_id, int(prestashop_id or 0))
                except Exception:
                    pass
                prestashop_ref = client._text(order_node.find("reference"))
                date_add = client._text(order_node.find("date_add"))
                current_state = client._text(order_node.find("current_state"))
                id_customer = client._text(order_node.find("id_customer"))
                id_address_delivery = client._text(order_node.find("id_address_delivery"))

                if not prestashop_id:
                    continue

                existing_map = self.env["prestashop.order.map"].search([
                    ("backend_id", "=", self.id),
                    ("prestashop_id", "=", prestashop_id),
                ], limit=1)
                if existing_map:
                    skipped += 1
                    continue

                partner = self._get_or_create_partner(client, id_customer, id_address_delivery, prestashop_id)
                pricelist = self._get_pricelist(partner)

                order_lines = []
                assoc = order_node.find("associations")
                rows_parent = assoc.find("order_rows") if assoc is not None else None
                if rows_parent is not None:
                    for row in rows_parent.findall("order_row"):
                        order_lines.append(self._map_order_row_to_line(client, row, prestashop_id))

                total_shipping = client._text(order_node.find("total_shipping_tax_incl"))
                try:
                    total_shipping_val = float(total_shipping) if total_shipping else 0.0
                except Exception:
                    total_shipping_val = 0.0

                if total_shipping_val and self.shipping_product_id:
                    order_lines.append((0, 0, {
                        "product_id": self.shipping_product_id.id,
                        "name": self.shipping_product_id.display_name,
                        "product_uom_qty": 1.0,
                        "price_unit": total_shipping_val,
                    }))

                # Use Odoo's address_get to resolve delivery/invoice addresses from child contacts
                addr = partner.address_get(["delivery", "invoice"])
                sale_vals = {
                    "company_id": self.company_id.id,
                    "partner_id": partner.id,
                    "partner_invoice_id": addr.get("invoice", partner.id),
                    "partner_shipping_id": addr.get("delivery", partner.id),
                    "pricelist_id": pricelist.id if pricelist else False,
                    "warehouse_id": self.warehouse_id.id,
                    "team_id": self.team_id.id if self.team_id else False,
                    "client_order_ref": prestashop_ref or prestashop_id,
                    "origin": f"PrestaShop #{prestashop_id}",
                    "note": f"Imported from PrestaShop.\nPresta order id: {prestashop_id}\nReference: {prestashop_ref}\nState: {current_state}\nDate: {date_add}",
                    "order_line": order_lines,
                }

                so = self.env["sale.order"].create(sale_vals)

                self.env["prestashop.order.map"].create({
                    "backend_id": self.id,
                    "prestashop_id": prestashop_id,
                    "sale_order_id": so.id,
                    "prestashop_reference": prestashop_ref,
                })

                if self.confirm_order_on_import:
                    if not paid_state_ids or current_state in paid_state_ids:
                        so.action_confirm()

                imported += 1
            except Exception as e:
                errors += 1
                self._log("import_orders", "error", "Failed to import order", details=str(e), prestashop_id=prestashop_id)
                continue

        self.last_order_sync = fields.Datetime.now()
        if max_seen_id > int(self.last_order_presta_id or 0):
            self.last_order_presta_id = max_seen_id

        status = "ok" if errors == 0 else ("warning" if imported else "error")
        self._log(
            "import_orders",
            status,
            f"Import finished: {imported} imported, {skipped} skipped, {errors} errors",
            details=mode_details,
        )

    def _get_or_create_partner(self, client, id_customer, id_address_delivery, prestashop_order_id):
        tag = self._ensure_customer_tag()

        customer_map = self.env["prestashop.customer.map"].search([
            ("backend_id", "=", self.id),
            ("prestashop_id", "=", id_customer),
        ], limit=1)
        if customer_map:
            partner = customer_map.partner_id
            if tag and tag.id not in partner.category_id.ids:
                partner.sudo().write({"category_id": [(4, tag.id)]})
        else:
            cust = client.get_customer(id_customer) if id_customer else None
            if cust is None:
                partner = self.env["res.partner"].search([("name", "=", "PrestaShop Guest")], limit=1)
                if not partner:
                    partner = self.env["res.partner"].create({"name": "PrestaShop Guest"})
                return partner

            email = client._text(cust.find("email"))
            firstname = client._text(cust.find("firstname"))
            lastname = client._text(cust.find("lastname"))
            name = (firstname + " " + lastname).strip() or email or f"PrestaShop Customer {id_customer}"

            partner = self.env["res.partner"].search([("email", "=", email)], limit=1) if email else False
            if not partner:
                vals = {
                    "name": name,
                    "email": email,
                    "company_id": self.company_id.id,
                }
                if tag:
                    vals["category_id"] = [(6, 0, [tag.id])]
                partner = self.env["res.partner"].create(vals)
            else:
                if tag and tag.id not in partner.category_id.ids:
                    partner.sudo().write({"category_id": [(4, tag.id)]})
            self.env["prestashop.customer.map"].create({
                "backend_id": self.id,
                "prestashop_id": id_customer,
                "partner_id": partner.id,
            })

        # Only update phone on main contact - addresses are managed via child contacts (sync_addresses)
        if id_address_delivery:
            try:
                addr = client.get_address(id_address_delivery)
                if addr is not None:
                    phone = client._text(addr.find("phone")) or client._text(addr.find("phone_mobile"))
                    if phone and not partner.phone:
                        partner.write({"phone": phone})
            except Exception as e:
                self._log("import_orders", "warning", "Failed to update partner phone", details=str(e), prestashop_id=prestashop_order_id)

        return partner

    def _map_order_row_to_line(self, client, row, prestashop_order_id):
        product_reference = client._text(row.find("product_reference"))
        product_name = client._text(row.find("product_name"))
        qty = client._text(row.find("product_quantity"))
        price_unit = client._text(row.find("unit_price_tax_incl")) or client._text(row.find("unit_price_tax_excl"))
        prestashop_product_id = client._text(row.find("product_id"))

        try:
            qty_val = float(qty) if qty else 1.0
        except Exception:
            qty_val = 1.0
        try:
            price_val = float(price_unit) if price_unit else 0.0
        except Exception:
            price_val = 0.0

        product = False

        if prestashop_product_id:
            pmap = self.env["prestashop.product.map"].search([
                ("backend_id", "=", self.id),
                ("prestashop_id", "=", prestashop_product_id),
            ], limit=1)
            product = pmap.product_id if pmap else False

        if not product and product_reference:
            product = self.env["product.product"].search([("default_code", "=", product_reference)], limit=1)

        if not product and self.create_missing_products and (product_reference or product_name):
            tmpl = self.env["product.template"].create({
                "name": product_name or product_reference,
                "type": "consu",
                "default_code": product_reference,
                "sale_ok": True,
                "purchase_ok": False,
                "company_id": self.company_id.id,
            })
            product = tmpl.product_variant_id

            if prestashop_product_id:
                self.env["prestashop.product.map"].create({
                    "backend_id": self.id,
                    "prestashop_id": prestashop_product_id,
                    "product_id": product.id,
                })

        if not product:
            raise UserError(_("Product not found for line '%s' (SKU: %s). Enable 'Create missing products' or map products.") % (product_name, product_reference))

        return (0, 0, {
            "product_id": product.id,
            "name": product_name or product.display_name,
            "product_uom_qty": qty_val,
            "price_unit": price_val,
        })
