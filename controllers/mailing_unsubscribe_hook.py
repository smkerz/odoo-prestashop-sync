"""Hook into Odoo's native mailing unsubscribe to push opt-outs to PrestaShop.

The native POST /mailing/confirm_unsubscribe writes opt_out directly on the
subscription record without going through mailing.contact.write(). We inherit
the controller and trigger the PrestaShop push after the native handler runs.
"""

import logging

from odoo.http import request

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.mass_mailing.controllers.main import MassMailController

    class MassMailControllerPrestashop(MassMailController):

        def mailing_confirm_unsubscribe_post(self, mailing_id, document_id=None,
                                              email=None, hash_token=None):
            res = super().mailing_confirm_unsubscribe_post(
                mailing_id, document_id=document_id,
                email=email, hash_token=hash_token,
            )
            _logger.info("PrestaShop: unsubscribe via email link detected, pushing opt-outs")
            _push_prestashop_opt_outs()
            return res

except (ImportError, Exception) as e:
    _logger.debug("mass_mailing controller not available, skipping unsubscribe hook: %s", e)


def _push_prestashop_opt_outs():
    try:
        env = request.env
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
