# -*- coding: utf-8 -*-
import hmac
import hashlib
import json
from urllib.parse import urlparse

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PrestashopWebhookController(http.Controller):
    @http.route(
        "/prestashop/webhook/ping",
        type="http",
        auth="public",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
        website=False,
    )
    def webhook_ping(self, **kwargs):
        return request.make_json_response({"status": "ok"})

    @http.route(
        "/prestashop/webhook/consents",
        type="http",
        auth="public",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
        website=False,
    )
    def webhook_consents(self, **kwargs):
        backend, payload, error = self._read_signed_payload("Webhook", "sync_consents")
        if error:
            return error

        res = backend.sudo()._apply_webhook_consents(payload)
        backend._log(
            "sync_consents",
            "ok",
            "Webhook received",
            details=f"path={request.httprequest.path}",
        )
        return request.make_json_response(res or {"status": "ok"})

    @http.route(
        "/prestashop/webhook/addresses",
        type="http",
        auth="public",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
        website=False,
    )
    def webhook_addresses(self, **kwargs):
        backend, payload, error = self._read_signed_payload("Webhook addresses", "sync_addresses")
        if error:
            return error

        res = backend.sudo()._apply_webhook_address(payload)
        backend._log(
            "sync_addresses",
            "ok",
            "Webhook address received",
            details=f"path={request.httprequest.path} action={payload.get('action', 'unknown')}",
        )
        return request.make_json_response(res or {"status": "ok"})

    def _read_signed_payload(self, label, operation):
        """Parse the JSON body of a webhook and check its HMAC-SHA256 signature.

        Returns (backend, payload, None) when the request is a valid signed POST,
        otherwise (None, None, response) with the response to send back.
        """
        def refuse(body, status=200):
            return None, None, request.make_json_response(body, status=status)

        _logger.info(
            "%s hit: method=%s path=%s",
            label,
            request.httprequest.method,
            request.httprequest.path,
        )
        if request.httprequest.method != "POST":
            return refuse({"status": "ok", "message": "use POST"})
        body = request.httprequest.data or b""
        if not body:
            return refuse({"status": "error", "message": "empty body"}, 400)

        signature = request.httprequest.headers.get("X-Prestashop-Signature", "")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return refuse({"status": "error", "message": "invalid json"}, 400)

        backend = self._find_backend(payload)
        if not backend or not backend.webhook_secret:
            _logger.warning("%s: backend not found. payload=%s", label, payload)
            return refuse({"status": "error", "message": "backend not found"}, 400)

        expected = hmac.new(
            backend.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            backend._log(
                operation,
                "warning",
                f"{label}: invalid signature",
                details=f"path={request.httprequest.path}",
            )
            return refuse({"status": "error", "message": "invalid signature"}, 401)

        return backend, payload, None

    def _find_backend(self, payload):
        Backend = request.env["prestashop.backend"].sudo()
        backend_id = payload.get("backend_id")
        if backend_id:
            try:
                rec = Backend.browse(int(backend_id))
                if rec and rec.exists():
                    return rec
            except Exception:
                pass
        candidates = Backend.search([("webhook_secret", "!=", False)])
        if not candidates:
            return None

        host = self._host(payload.get("shop_url"))
        if host:
            for backend in candidates:
                if self._host(backend.base_url) == host:
                    return backend

        return None

    @staticmethod
    def _host(url):
        """Lowercased hostname of a URL, without port; '' when it cannot be parsed."""
        try:
            return (urlparse((url or "").strip()).netloc or "").split(":")[0].strip().lower()
        except Exception:
            return ""
