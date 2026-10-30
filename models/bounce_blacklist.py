# -*- coding: utf-8 -*-
"""Set aside an address on the first report saying it no longer exists.

Odoo blocklists an address only after 5 bounces over more than a week in 13 weeks: a list
mailed once or twice a year never gets there, and keeps writing to dead addresses.

Off by default: set the system parameter below to "1" to enable it.
Never applied to PrestaShop customers or internal users, nor to a report that does not
match a mail we really sent to that address (a forged report must not block anyone).
"""
import logging

from odoo import api, models

from . import bounce_rules

_logger = logging.getLogger(__name__)

ENABLED_PARAM = "prestashop_connector.blacklist_dead_bounces"
CUSTOMER_TAG = "Client Prestashop"


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    @api.model
    def _routing_handle_bounce(self, email_message, message_dict):
        super()._routing_handle_bounce(email_message, message_dict)
        if self.env["ir.config_parameter"].sudo().get_param(ENABLED_PARAM) != "1":
            return
        # A failure here must never stop the mail gateway from reading the next mails.
        try:
            with self.env.cr.savepoint():
                self._blacklist_dead_bounce(email_message, message_dict)
        except Exception as e:
            _logger.warning("Bounce: could not set the address aside: %s", e)

    @api.model
    def _blacklist_dead_bounce(self, email_message, message_dict):
        email = message_dict.get("bounced_email")
        if not email:
            return
        action, status, diagnostic = bounce_rules.read_report(email_message)
        if not bounce_rules.is_dead_address(action, status, diagnostic):
            return
        if not self._bounce_matches_sent_mail(email, message_dict):
            _logger.info("Bounce: report matches no mail sent to that address, ignored (status %s)", status)
            return
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        if Partner.search_count([
            ("email_normalized", "=", email),
            "|", ("category_id.name", "=", CUSTOMER_TAG), ("user_ids", "!=", False),
        ]):
            _logger.info("Bounce: customer or internal user, not set aside (status %s)", status)
            return
        # A new blacklist line pushes its revocation at once, so the push cap is not reached.
        self.env["mail.blacklist"].sudo()._add(
            email, message=f"Automatically blocklisted: permanent bounce (status {status}).",
        )
        _logger.info("Bounce: address set aside (status %s)", status)

    @api.model
    def _bounce_matches_sent_mail(self, email, message_dict):
        msg_ids = message_dict.get("bounced_msg_ids")
        if not msg_ids:
            return False
        return bool(self.env["mailing.trace"].sudo().search_count([
            ("message_id", "in", msg_ids), ("email", "=ilike", email),
        ]) or message_dict.get("bounced_message"))
