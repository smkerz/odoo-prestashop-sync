"""Real-time propagation of Odoo consent revocations to PrestaShop.

When a mailing contact opts out, is removed from a list,
or an email is blacklisted in Odoo, we immediately push opt-outs to all
PrestaShop backends. This avoids waiting for the hourly cron.

Note: mailing.contact.subscription does not exist in all Odoo 17 installations.
We only override mailing.contact (always present with mass_mailing) and
mail.blacklist. The opt_out field on subscriptions is handled by intercepting
writes on mailing.contact.subscription_list_ids / list_ids.
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
        should_push = False
        # opt_out set directly on the contact
        if vals.get("opt_out"):
            should_push = True
        # Contact removed from a list
        if "list_ids" in vals:
            for cmd in vals["list_ids"]:
                if isinstance(cmd, (list, tuple)) and cmd[0] in (2, 3):
                    should_push = True
                    break
        # subscription_list_ids modified (contains opt_out changes in Odoo 17)
        if "subscription_list_ids" in vals:
            for cmd in vals["subscription_list_ids"]:
                if isinstance(cmd, (list, tuple)) and cmd[0] in (1,):
                    # cmd = (1, id, {field: val}) — check if opt_out is being set
                    if isinstance(cmd[2], dict) and cmd[2].get("opt_out"):
                        should_push = True
                        break
                elif isinstance(cmd, (list, tuple)) and cmd[0] in (2, 3):
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
