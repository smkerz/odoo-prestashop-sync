"""Standalone tests for the PrestaShop Webservice client (no Odoo needed).

Run from the module folder:
    python tests/test_prestashop_client.py

`requests` is replaced by a fake PrestaShop, so nothing goes over the network.
Set PS_CLIENT_PATH to test another copy of prestashop_client.py.
"""
import importlib.util
import os
import re
import sys
import types
import unittest

CLIENT_PATH = os.environ.get("PS_CLIENT_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "models", "prestashop_client.py"
)


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload


class FakeShop:
    """In-memory PrestaShop answering the few Webservice calls the client makes."""

    def __init__(self):
        self.customers = []          # dicts: id, newsletter, optin, is_guest
        self.addresses = []          # dicts: id, id_customer, deleted
        self.subscribers = []        # dicts: email, active
        self.rejected_filters = set()
        self.calls = []              # (method, url, kwargs)

    # -- requests API -------------------------------------------------------
    def get(self, url, **kw):
        self.calls.append(("get", url, kw))
        params = kw.get("params") or {}
        if "/module/prestashopodoo/emailsubscribers" in url:
            rows = [s for s in self.subscribers if params.get("active_only") != "1" or s["active"] == "1"]
            return FakeResponse(payload={"subscribers": rows, "total": len(rows)})
        resource = url.rsplit("/api/", 1)[1]
        for key in params:
            if key in self.rejected_filters:
                return FakeResponse(400, "<error><code>32</code><message>This filter does not exist</message></error>")
        if resource == "customers":
            return FakeResponse(text=self._xml("customers", "customer", self._select(self.customers, params)))
        if resource == "addresses":
            return FakeResponse(text=self._xml("addresses", "address", self._select(self.addresses, params)))
        return FakeResponse(text="<prestashop><%s/></prestashop>" % resource)

    def post(self, url, **kw):
        self.calls.append(("post", url, kw))
        return FakeResponse(payload={"status": "ok", "updated": 1})

    def put(self, url, **kw):
        self.calls.append(("put", url, kw))
        return FakeResponse(text="<prestashop/>")

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _matches(row, field, expr):
        value = str(row.get(field, ""))
        m = re.fullmatch(r"\[(\d+),(\d+)\]", expr)
        if m:
            return int(m.group(1)) <= int(value) <= int(m.group(2))
        if expr.startswith("["):
            return value in expr.strip("[]").split("|")
        return value == expr

    def _select(self, rows, params):
        for key, expr in params.items():
            m = re.fullmatch(r"filter\[(\w+)\]", key)
            if m:
                rows = [r for r in rows if self._matches(r, m.group(1), expr)]
        rows = sorted(rows, key=lambda r: int(r["id"]), reverse=params.get("sort") == "[id_DESC]")
        offset, limit = (int(x) for x in params["limit"].split(","))
        return rows[offset:offset + limit]

    @staticmethod
    def _xml(container, item, rows):
        body = "".join(
            "<%s>%s</%s>" % (item, "".join("<%s>%s</%s>" % (k, v, k) for k, v in row.items()), item)
            for row in rows
        )
        return "<prestashop><%s>%s</%s></prestashop>" % (container, body, container)


def load_client(shop):
    fake_requests = types.ModuleType("requests")
    fake_requests.get, fake_requests.post, fake_requests.put = shop.get, shop.post, shop.put
    saved = sys.modules.get("requests")
    sys.modules["requests"] = fake_requests
    try:
        spec = importlib.util.spec_from_file_location("prestashop_client_under_test", CLIENT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            del sys.modules["requests"]
        else:
            sys.modules["requests"] = saved
    return module, module.PrestaShopClient("https://shop.invalid/", "KEY")


class ClientCase(unittest.TestCase):
    def setUp(self):
        self.shop = FakeShop()
        self.module, self.client = load_client(self.shop)
        # ids 1..7; odd ids subscribed to the newsletter, 3 and 4 opted in, 7 is a guest
        for i in range(1, 8):
            self.shop.customers.append({
                "id": str(i),
                "newsletter": "1" if i % 2 else "0",
                "optin": "1" if i in (3, 4) else "0",
                "is_guest": "1" if i == 7 else "0",
            })
        for i, (cid, deleted) in enumerate([(1, 0), (1, 0), (2, 0), (2, 1), (3, 0)], start=10):
            self.shop.addresses.append({"id": str(i), "id_customer": str(cid), "deleted": str(deleted)})

    def ids(self, nodes):
        return [n.find("id").text for n in nodes]


class TestConsentIds(ClientCase):
    def test_newsletter_ids_paginated(self):
        self.assertEqual(self.client.list_newsletter_customer_ids(batch_size=2), ["1", "3", "5", "7"])

    def test_optin_ids(self):
        self.assertEqual(self.client.list_optin_customer_ids(batch_size=200), ["3", "4"])

    def test_guests_excluded(self):
        self.assertEqual(
            self.client.list_newsletter_customer_ids(batch_size=200, include_guests=False), ["1", "3", "5"])

    def test_max_total_truncates(self):
        self.assertEqual(self.client.list_newsletter_customer_ids(batch_size=2, max_total=3), ["1", "3", "5"])

    def test_fallback_scan_when_filter_rejected(self):
        self.shop.rejected_filters = {"filter[newsletter]", "filter[optin]"}
        self.assertEqual(self.client.list_newsletter_customer_ids(batch_size=3), ["1", "3", "5", "7"])
        self.assertEqual(self.client.list_optin_customer_ids(batch_size=3), ["3", "4"])


class TestIncremental(ClientCase):
    def test_customers_after_id(self):
        nodes = self.client.list_customers_incremental(after_id=2, batch_size=2, include_guests=True)
        self.assertEqual(self.ids(nodes), ["3", "4", "5", "6", "7"])

    def test_customers_without_guests(self):
        nodes = self.client.list_customers_incremental(after_id=0, batch_size=3)
        self.assertEqual(self.ids(nodes), ["1", "2", "3", "4", "5", "6"])

    def test_customers_max_total_stops_on_batch_boundary(self):
        nodes = self.client.list_customers_incremental(after_id=0, batch_size=2, include_guests=True, max_total=3)
        self.assertEqual(self.ids(nodes), ["1", "2", "3", "4"])


class TestAddresses(ClientCase):
    def test_grouped_for_several_customers(self):
        grouped = self.client.list_addresses_for_customers(["1", "2", "3"], batch_size=2)
        self.assertEqual({k: self.ids(v) for k, v in grouped.items()}, {"1": ["10", "11"], "2": ["12"], "3": ["14"]})

    def test_grouped_without_deleted_filter(self):
        self.shop.rejected_filters = {"filter[deleted]"}
        grouped = self.client.list_addresses_for_customers(["2"], batch_size=1)
        self.assertEqual({k: self.ids(v) for k, v in grouped.items()}, {"2": ["12", "13"]})

    def test_grouped_max_total(self):
        grouped = self.client.list_addresses_for_customers(["1", "2", "3"], batch_size=2, max_total=3)
        self.assertEqual(sum(len(v) for v in grouped.values()), 3)

    def test_single_customer_returns_nodes(self):
        nodes = self.client.list_addresses_for_customer("1", batch_size=1)
        self.assertEqual(self.ids(nodes), ["10", "11"])


class TestModuleEndpoints(ClientCase):
    def setUp(self):
        super().setUp()
        self.shop.subscribers = [
            {"email": "a@example.invalid", "active": "1"},
            {"email": "b@example.invalid", "active": "0"},
        ]

    def test_active_only_by_default(self):
        self.assertEqual(len(self.client.list_email_only_subscribers()), 1)

    def test_inactive_rows_on_request(self):
        self.assertEqual(len(self.client.list_email_only_subscribers(active_only=False)), 2)

    def test_every_request_carries_the_user_agent(self):
        self.client.get_xml("languages")
        self.client.put("customers/1", "<x/>")
        self.client.list_email_only_subscribers()
        self.client.unsubscribe_email_only_subscriber("a@example.invalid")
        self.assertEqual(len(self.shop.calls), 4)
        for _method, _url, kw in self.shop.calls:
            self.assertEqual(kw["headers"]["User-Agent"], self.module.USER_AGENT)


if __name__ == "__main__":
    unittest.main()
