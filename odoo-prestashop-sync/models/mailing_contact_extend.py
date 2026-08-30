"""Real-time propagation of Odoo consent revocations to PrestaShop.

When a mailing contact opts out, is removed from a list,
or an email is blacklisted in Odoo, we immediately push opt-outs to all
PrestaShop backends. This avoids waiting for the cron.

Note: the native Odoo unsubscribe link (/mailing/confirm_unsubscribe) writes
directly on the subscription record without going through mailing.contact.write.
That path is covered by the cron (recommended: 15 min interval).
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
        res = super().write(vals)
        should_push = False
        # opt_out set directly on the contact
        if vals.get("opt_out"):
            should_push = True
        # Check all possible subscription field names
        for field in ("subscription_ids", "subscription_list_ids", "list_ids"):
            if field in vals and _has_opt_out_in_commands(vals[field]):
                should_push = True
                break
        if should_push:
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
