"""Real-time propagation of Odoo consent revocations to PrestaShop.

When a mailing contact opts out, is removed from a list,
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
        # DEBUG: log every write to see what fields are being changed
        _logger.info("PRESTASHOP DEBUG mailing.contact.write called with keys: %s", list(vals.keys()))
        if "subscription_list_ids" in vals:
            _logger.info("PRESTASHOP DEBUG subscription_list_ids value: %s", vals["subscription_list_ids"])
        res = super().write(vals)
        should_push = False
        if vals.get("opt_out"):
            _logger.info("PRESTASHOP DEBUG opt_out detected on mailing.contact")
            should_push = True
        if "list_ids" in vals:
            for cmd in vals["list_ids"]:
                if isinstance(cmd, (list, tuple)) and cmd[0] in (2, 3):
                    should_push = True
                    break
        if "subscription_list_ids" in vals:
            for cmd in vals["subscription_list_ids"]:
                if isinstance(cmd, (list, tuple)) and cmd[0] in (1,):
                    if isinstance(cmd[2], dict) and cmd[2].get("opt_out"):
                        _logger.info("PRESTASHOP DEBUG opt_out detected via subscription_list_ids")
                        should_push = True
                        break
                elif isinstance(cmd, (list, tuple)) and cmd[0] in (2, 3):
                    should_push = True
                    break
        if should_push:
            _logger.info("PRESTASHOP DEBUG pushing opt-outs to PrestaShop")
            _push_opt_outs_to_all_backends(self.env)
        return res


class MailBlacklist(models.Model):
    _inherit = "mail.blacklist"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records:
            _logger.info("PRESTASHOP DEBUG mail.blacklist.create - pushing opt-outs")
            _push_opt_outs_to_all_backends(self.env)
        return records
