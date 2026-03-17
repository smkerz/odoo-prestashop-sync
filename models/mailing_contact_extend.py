"""Real-time propagation of Odoo consent revocations to PrestaShop.

When a mailing contact opts out (via subscription), is removed from a list,
or an email is blacklisted in Odoo, we immediately push opt-outs to all
PrestaShop backends. This avoids waiting for the hourly cron.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


def _push_opt_outs_to_all_backends(env):
    """Push opt-outs to all PrestaShop backends."""
    try:
        backends = env["prestashop.backend"].sudo().search([
            ("api_key", "!=", False),
        ])
        for backend in backends:
            try:
                client = backend._client()
                backend._push_opt_outs_to_prestashop(client)
            except Exception as e:
                _logger.warning(
                    "Failed to push opt-out to PrestaShop backend %s: %s",
                    backend.name, e,
                )
    except Exception as e:
        _logger.warning("Failed to trigger PrestaShop opt-out push: %s", e)


class MailingContact(models.Model):
    _inherit = "mailing.contact"

    def write(self, vals):
        res = super().write(vals)
        # Trigger when opt_out is set on the contact itself (older Odoo versions)
        if vals.get("opt_out"):
            _push_opt_outs_to_all_backends(self.env)
        # Trigger when a contact is removed from a list (list_ids with unlink command)
        if "list_ids" in vals:
            for cmd in vals["list_ids"]:
                if isinstance(cmd, (list, tuple)) and cmd[0] in (2, 3):
                    # 2 = delete, 3 = unlink
                    _push_opt_outs_to_all_backends(self.env)
                    break
        return res


class MailingContactSubscription(models.Model):
    _inherit = "mailing.contact.subscription"

    def write(self, vals):
        res = super().write(vals)
        if vals.get("opt_out"):
            _push_opt_outs_to_all_backends(self.env)
        return res


class MailBlacklist(models.Model):
    _inherit = "mail.blacklist"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records:
            _push_opt_outs_to_all_backends(self.env)
        return records
