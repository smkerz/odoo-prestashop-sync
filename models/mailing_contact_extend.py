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


def _has_opt_out_in_commands(cmds):
    """Check if a list of ORM write commands contains an opt_out=True."""
    for cmd in cmds:
        if not isinstance(cmd, (list, tuple)):
            continue
        if cmd[0] == 1 and isinstance(cmd[2], dict) and cmd[2].get("opt_out"):
            return True
        if cmd[0] in (2, 3):
            return True
    return False


class MailingContact(models.Model):
    _inherit = "mailing.contact"

    def write(self, vals):
        _logger.info("PRESTASHOP DEBUG mailing.contact.write keys=%s", list(vals.keys()))
        for field in ("subscription_ids", "subscription_list_ids", "list_ids"):
            if field in vals:
                _logger.info("PRESTASHOP DEBUG %s = %s", field, vals[field])
        if vals.get("opt_out"):
            _logger.info("PRESTASHOP DEBUG opt_out=True detected")
        res = super().write(vals)
        should_push = False
        # opt_out set directly on the contact
        if vals.get("opt_out"):
            should_push = True
        # Check all possible subscription field names
        for field in ("subscription_ids", "subscription_list_ids", "list_ids"):
            if field in vals and _has_opt_out_in_commands(vals[field]):
                _logger.info("PRESTASHOP DEBUG opt_out found in %s", field)
                should_push = True
                break
        if should_push:
            _logger.info("PRESTASHOP DEBUG pushing opt-outs to all backends")
            _push_opt_outs_to_all_backends(self.env)
        else:
            _logger.info("PRESTASHOP DEBUG no opt_out detected, skipping push")
        return res


class MailBlacklist(models.Model):
    _inherit = "mail.blacklist"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records:
            _push_opt_outs_to_all_backends(self.env)
        return records
