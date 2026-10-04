"""Standalone tests for the webhook controller's request checks (no Odoo needed).

Run from the module folder:
    python tests/test_webhook_controller.py

`odoo` is replaced by a minimal stub: only the HTTP plumbing the controller
touches is faked. Set PS_CONTROLLER_PATH to test another copy of the file.
"""
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import types
import unittest

CONTROLLER_PATH = os.environ.get("PS_CONTROLLER_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "controllers", "prestashop_webhook.py"
)
SECRET = "test-secret"


class FakeBackend:
    def __init__(self, backend_id, base_url, secret=SECRET):
        self.id = backend_id
        self.base_url = base_url
        self.webhook_secret = secret
        self.logs = []
        self.applied = []

    def exists(self):
        return True

    def __bool__(self):
        return True

    def sudo(self):
        return self

    def _log(self, operation, status, message, details=None):
        self.logs.append((operation, status, message))

    def _apply_webhook_consents(self, payload):
        self.applied.append(("consents", payload))
        return {"status": "ok"}

    def _apply_webhook_address(self, payload):
        self.applied.append(("address", payload))
        return {"status": "ok"}


class FakeBackendModel:
    def __init__(self, backends):
        self.backends = backends

    def sudo(self):
        return self

    def browse(self, backend_id):
        return next((b for b in self.backends if b.id == backend_id), None)

    def search(self, domain):
        return [b for b in self.backends if b.webhook_secret]


class FakeRequest:
    def __init__(self):
        self.env = {}
        self.httprequest = types.SimpleNamespace(method="POST", path="/prestashop/webhook/x", data=b"", headers={})

    @staticmethod
    def make_json_response(body, status=200):
        return {"body": body, "status": status}


def load_controller(fake_request):
    http = types.ModuleType("odoo.http")
    http.Controller = object
    http.route = lambda *a, **kw: (lambda f: f)
    http.request = fake_request
    odoo = types.ModuleType("odoo")
    odoo.http = http
    saved = {k: sys.modules.get(k) for k in ("odoo", "odoo.http")}
    sys.modules.update({"odoo": odoo, "odoo.http": http})
    try:
        spec = importlib.util.spec_from_file_location("webhook_controller_under_test", CONTROLLER_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for k, v in saved.items():
            if v is None:
                del sys.modules[k]
            else:
                sys.modules[k] = v
    return module.PrestashopWebhookController()


class WebhookCase(unittest.TestCase):
    def setUp(self):
        self.request = FakeRequest()
        self.fr = FakeBackend(1, "https://shop-fr.invalid")
        self.com = FakeBackend(2, "https://shop-com.invalid:443/")
        self.request.env = {"prestashop.backend": FakeBackendModel([self.fr, self.com])}
        self.controller = load_controller(self.request)

    def post(self, payload, secret=SECRET, signature=None):
        body = json.dumps(payload).encode("utf-8")
        if signature is None:
            signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        self.request.httprequest.data = body
        self.request.httprequest.headers = {"X-Prestashop-Signature": signature}

    def test_valid_consent_webhook_is_applied(self):
        self.post({"backend_id": 1, "email": "a@example.invalid"})
        res = self.controller.webhook_consents()
        self.assertEqual(res["status"], 200)
        self.assertEqual([kind for kind, _p in self.fr.applied], ["consents"])

    def test_valid_address_webhook_is_applied(self):
        self.post({"backend_id": 2, "action": "update"})
        res = self.controller.webhook_addresses()
        self.assertEqual(res["status"], 200)
        self.assertEqual([kind for kind, _p in self.com.applied], ["address"])

    def test_wrong_signature_is_rejected_and_logged(self):
        self.post({"backend_id": 1}, secret="other-secret")
        res = self.controller.webhook_consents()
        self.assertEqual(res["status"], 401)
        self.assertEqual(self.fr.applied, [])
        self.assertEqual(self.fr.logs, [("sync_consents", "warning", "Webhook: invalid signature")])

    def test_missing_signature_is_rejected(self):
        self.post({"backend_id": 1}, signature="")
        self.assertEqual(self.controller.webhook_addresses()["status"], 401)
        self.assertEqual(self.fr.applied, [])
        self.assertEqual(self.fr.logs, [("sync_addresses", "warning", "Webhook addresses: invalid signature")])

    def test_backend_resolved_by_shop_url(self):
        self.post({"shop_url": "https://SHOP-COM.invalid/fr/"})
        self.assertEqual(self.controller.webhook_consents()["status"], 200)
        self.assertEqual(len(self.com.applied), 1)

    def test_unknown_backend(self):
        self.post({"shop_url": "https://elsewhere.invalid/"})
        self.assertEqual(self.controller.webhook_consents()["status"], 400)

    def test_empty_body_and_invalid_json(self):
        self.request.httprequest.data = b""
        self.assertEqual(self.controller.webhook_consents()["status"], 400)
        self.request.httprequest.data = b"{not json"
        self.assertEqual(self.controller.webhook_consents()["status"], 400)

    def test_get_is_not_processed(self):
        self.request.httprequest.method = "GET"
        res = self.controller.webhook_consents()
        self.assertEqual(res, {"body": {"status": "ok", "message": "use POST"}, "status": 200})
        self.assertEqual(self.fr.applied, [])


if __name__ == "__main__":
    unittest.main()
