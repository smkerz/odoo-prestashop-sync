"""Real-time propagation of Odoo consent revocations to PrestaShop.

When a mailing contact opts out or an email is blacklisted in Odoo,
we schedule an immediate push of opt-outs to all PrestaShop backends.
This avoids waiting for the hourly cron.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class MailingContact(models.Model):
    _inherit = "mailing.contact"

    def write(self, vals):
        res = super().write(vals)
        if "opt_out" in vals and vals["opt_out"]:
            self._trigger_prestashop_opt_out_push()
        return res

    def _trigger_prestashop_opt_out_push(self):
        """Schedule an immediate push of opt-outs to PrestaShop backends."""
        try:
            backends = self.env["prestashop.backend"].sudo().search([
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


class MailBlacklist(models.Model):
    _inherit = "mail.blacklist"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records:
            self._trigger_prestashop_opt_out_push()
        return records

    def _trigger_prestashop_opt_out_push(self):
        """Schedule an immediate push of opt-outs to PrestaShop backends."""
        try:
            backends = self.env["prestashop.backend"].sudo().search([
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
