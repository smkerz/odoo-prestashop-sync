"""Hook into Odoo's native mailing unsubscribe to push opt-outs to PrestaShop."""

import logging
import threading

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
        # Push opt-outs after commit, in a separate thread to not block the user
        db_name = request.env.cr.dbname
        request.env.cr.postcommit.add(
            lambda: self._push_opt_outs_async(db_name)
        )
        return res

    @staticmethod
    def _push_opt_outs_async(db_name):
        """Push opt-outs in a new thread so the HTTP response is not delayed."""
        def _run():
            try:
                import odoo
                registry = odoo.registry(db_name)
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                    backends = env["prestashop.backend"].search([
                        ("api_key", "!=", False),
                    ])
                    for backend in backends:
                        try:
                            client = backend._client()
                            backend._push_opt_outs_to_prestashop(client)
                            _logger.info(
                                "Pushed opt-outs to PrestaShop backend %s after email unsubscribe",
                                backend.name,
                            )
                        except Exception as e:
                            _logger.warning(
                                "Failed to push opt-out to PrestaShop backend %s: %s",
                                backend.name, e,
                            )
            except Exception as e:
                _logger.warning("Failed to trigger async PrestaShop opt-out push: %s", e)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
