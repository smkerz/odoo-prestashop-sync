"""Hook into Odoo's native mailing unsubscribe to push opt-outs to PrestaShop."""

import logging

from odoo import http
from odoo.http import request
from odoo.addons.mass_mailing.controllers.main import MassMailController

_logger = logging.getLogger(__name__)


class MassMailControllerPrestashop(MassMailController):

    @http.route('/mailing/confirm_unsubscribe', type='http', website=True,
                auth='public', methods=['POST'])
    def mailing_confirm_unsubscribe_post(self, mailing_id, document_id=None,
                                          email=None, hash_token=None):
        res = super().mailing_confirm_unsubscribe_post(
            mailing_id, document_id=document_id,
            email=email, hash_token=hash_token,
        )
        try:
            backends = request.env["prestashop.backend"].sudo().search([
                ("api_key", "!=", False),
            ])
            for backend in backends:
                try:
                    client = backend._client()
                    backend._push_opt_outs_to_prestashop(client)
                    _logger.info("Pushed opt-outs to PrestaShop backend %s after email unsubscribe", backend.name)
                except Exception as e:
                    _logger.warning("Failed to push opt-out to PrestaShop backend %s: %s", backend.name, e)
        except Exception as e:
            _logger.warning("Failed to trigger PrestaShop opt-out push after unsubscribe: %s", e)
        return res
