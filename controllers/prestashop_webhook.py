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
        _logger.info(
            "Webhook consents hit: method=%s path=%s",
            request.httprequest.method,
            request.httprequest.path,
        )
        if request.httprequest.method != "POST":
            return request.make_json_response({"status": "ok", "message": "use POST"})
        body = request.httprequest.data or b""
        if not body:
            return request.make_json_response({"status": "error", "message": "empty body"}, status=400)

        signature = request.httprequest.headers.get("X-Prestashop-Signature", "")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return request.make_json_response({"status": "error", "message": "invalid json"}, status=400)

        backend = self._find_backend(payload)
        if not backend or not backend.webhook_secret:
            _logger.warning("Webhook: backend not found. payload=%s", payload)
            return request.make_json_response({"status": "error", "message": "backend not found"}, status=400)

        expected = hmac.new(
            backend.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            backend._log(
                "sync_consents",
                "warning",
                "Webhook: invalid signature",
                details=f"path={request.httprequest.path}",
            )
            return request.make_json_response({"status": "error", "message": "invalid signature"}, status=401)

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
        _logger.info(
            "Webhook addresses hit: method=%s path=%s",
            request.httprequest.method,
            request.httprequest.path,
        )
        if request.httprequest.method != "POST":
            return request.make_json_response({"status": "ok", "message": "use POST"})
        body = request.httprequest.data or b""
        if not body:
            return request.make_json_response({"status": "error", "message": "empty body"}, status=400)

        signature = request.httprequest.headers.get("X-Prestashop-Signature", "")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return request.make_json_response({"status": "error", "message": "invalid json"}, status=400)

        backend = self._find_backend(payload)
        if not backend or not backend.webhook_secret:
            _logger.warning("Webhook addresses: backend not found. payload=%s", payload)
            return request.make_json_response({"status": "error", "message": "backend not found"}, status=400)

        expected = hmac.new(
            backend.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            backend._log(
                "sync_addresses",
                "warning",
                "Webhook addresses: invalid signature",
                details=f"path={request.httprequest.path}",
            )
            return request.make_json_response({"status": "error", "message": "invalid signature"}, status=401)

        res = backend.sudo()._apply_webhook_address(payload)
        backend._log(
            "sync_addresses",
            "ok",
            "Webhook address received",
            details=f"path={request.httprequest.path} action={payload.get('action', 'unknown')}",
        )
        return request.make_json_response(res or {"status": "ok"})

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

        shop_url = (payload.get("shop_url") or "").strip()
        host = ""
        if shop_url:
            try:
                parsed = urlparse(shop_url)
                host = (parsed.netloc or "").split(":")[0].strip().lower()
            except Exception:
                host = ""

        if host:
            for backend in candidates:
                bhost = ""
                try:
                    parsed = urlparse((backend.base_url or "").strip())
                    bhost = (parsed.netloc or "").split(":")[0].strip().lower()
                except Exception:
                    bhost = ""
                if bhost and bhost == host:
                    return backend

        if len(candidates) == 1:
            return candidates[0]
        return None
