# -*- coding: utf-8 -*-
import base64
import logging
import requests
from xml.etree import ElementTree as ET

_logger = logging.getLogger(__name__)

class PrestaShopAPIError(Exception):
    pass

class PrestaShopClient:
    """
    Minimal PrestaShop Webservice client for PrestaShop 1.7.x (XML).
    """
    def __init__(self, base_url: str, api_key: str, timeout: int = 30, verify_tls: bool = True):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_tls = verify_tls

    def _auth_header(self):
        token = base64.b64encode((self.api_key + ":").encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _url(self, path: str):
        if path.startswith("http"):
            return path
        path = path.lstrip("/")
        return f"{self.base_url}/{path}"

    def get(self, resource: str, params=None):
        url = self._url(f"api/{resource.lstrip('/')}")
        headers = {"Accept": "application/xml"}
        headers.update(self._auth_header())
        try:
            resp = requests.get(url, headers=headers, params=params or {}, timeout=self.timeout, verify=self.verify_tls)
        except Exception as e:
            raise PrestaShopAPIError(f"HTTP error calling {url}: {e}") from e
        if resp.status_code >= 300:
            raise PrestaShopAPIError(f"PrestaShop API error {resp.status_code} on {url}: {resp.text[:500]}")
        return resp.text

    def put(self, resource: str, xml_payload: str):
        """PUT an XML payload to a given PrestaShop resource path.

        Example resource: 'customers/123'
        """
        url = self._url(f"api/{resource.lstrip('/')}" )
        headers = {"Accept": "application/xml", "Content-Type": "application/xml"}
        headers.update(self._auth_header())
        try:
            resp = requests.put(url, headers=headers, data=(xml_payload or "").encode("utf-8"), timeout=self.timeout, verify=self.verify_tls)
        except Exception as e:
            raise PrestaShopAPIError(f"HTTP error calling {url}: {e}") from e
        if resp.status_code >= 300:
            raise PrestaShopAPIError(f"PrestaShop API error {resp.status_code} on {url}: {resp.text[:500]}")
        return resp.text

    def get_xml(self, resource: str, params=None):
        xml_text = self.get(resource, params=params)
        try:
            return ET.fromstring(xml_text.encode("utf-8"))
        except Exception as e:
            raise PrestaShopAPIError(f"XML parsing error for resource {resource}: {e}") from e

    @staticmethod
    def _text(node, default=""):
        if node is None:
            return default
        return (node.text or "").strip()

    def list_orders_since(self, dt_str: str, limit: int = 200):
        """
        dt_str: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'
        """
        params = {
            "display": "full",
            "limit": str(limit),
            "filter[date_add]": f"[>={dt_str}]",
            "sort": "[date_add_ASC]",
        }
        root = self.get_xml("orders", params=params)
        orders = []
        orders_node = root.find("orders")
        if orders_node is None:
            return orders
        for order in orders_node.findall("order"):
            orders.append(order)
        return orders

    def list_orders_latest(self, limit: int = 200):
        """Return the latest orders by ID (descending).

        This is used as a compatible fallback for shops where filtering on date_add
        is not available on the Webservice.
        """
        limit = int(limit or 200)
        if limit <= 0:
            limit = 200
        params = {
            "display": "full",
            "limit": f"0,{limit}",
            "sort": "[id_DESC]",
        }
        root = self.get_xml("orders", params=params)
        return self._extract_list(root, "orders", "order")

    def list_orders_incremental(self, after_id: int = 0, batch_size: int = 200, max_total: int = 5000):
        """Iterate over orders incrementally, using id-based pagination.

        This is the most compatible approach across PrestaShop 1.7 instances, as
        some shops reject filtering on date_add.
        """
        after_id = int(after_id or 0)
        batch_size = int(batch_size or 200)
        max_total = int(max_total or 0)
        if batch_size <= 0:
            batch_size = 200

        results = []
        last_id = after_id
        fetched = 0

        while True:
            params = {
                "display": "full",
                "limit": f"0,{batch_size}",
                "sort": "[id_ASC]",
                "filter[id]": f"[{last_id + 1},999999999]",
            }
            root = self.get_xml("orders", params=params)
            batch = self._extract_list(root, "orders", "order")
            if not batch:
                break

            results.extend(batch)
            fetched += len(batch)

            try:
                last_id = int(self._text(batch[-1].find("id")) or last_id)
            except Exception:
                break

            if max_total and fetched >= max_total:
                break

        return results

    def get_customers_since(self, dt_str: str, limit: int = 1000, include_guests: bool = False):
        """
        List customers created since dt_str.
        dt_str: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'
        """
        # PrestaShop instances differ in which fields are filterable via Webservice.
        # Some shops (or overrides) reject filtering on date_add. We therefore:
        #  1) try date_add filtering
        #  2) if the API rejects the filter, fall back to an id-based incremental list.
        params = {
            "display": "full",
            # PrestaShop Webservice commonly expects the "offset,limit" form.
            "limit": f"0,{int(limit)}",
            "filter[date_add]": f"[>={dt_str}]",
            "sort": "[date_add_ASC]",
        }
        if not include_guests:
            params["filter[is_guest]"] = "0"

        try:
            root = self.get_xml("customers", params=params)
            return self._extract_list(root, "customers", "customer")
        except PrestaShopAPIError as e:
            msg = str(e)
            # Error code 32 in Presta often means "This filter does not exist".
            # When that happens, we retry without date filters.
            if "This filter does not exist" not in msg:
                raise

        # Fallback: list customers without date filters (id sort) and apply guest filter if requested.
        params2 = {
            "display": "full",
            "limit": f"0,{int(limit)}",
            "sort": "[id_ASC]",
        }
        if not include_guests:
            params2["filter[is_guest]"] = "0"
        root2 = self.get_xml("customers", params=params2)
        return self._extract_list(root2, "customers", "customer")

    def list_customers_incremental(self, after_id: int = 0, batch_size: int = 200, include_guests: bool = False, max_total: int = 5000):
        """Iterate over customers incrementally, using id-based pagination.

        This is the most compatible approach across PrestaShop 1.7 instances.
        """
        after_id = int(after_id or 0)
        batch_size = int(batch_size or 200)
        max_total = int(max_total or 0)
        if batch_size <= 0:
            batch_size = 200

        results = []
        last_id = after_id
        fetched = 0

        while True:
            params = {
                "display": "full",
                "limit": f"0,{batch_size}",
                "sort": "[id_ASC]",
                # Some PrestaShop instances expect an explicit upper bound.
                "filter[id]": f"[{last_id + 1},999999999]",
            }
            if not include_guests:
                params["filter[is_guest]"] = "0"

            root = self.get_xml("customers", params=params)
            batch = self._extract_list(root, "customers", "customer")
            if not batch:
                break

            results.extend(batch)
            fetched += len(batch)

            # Update last_id from the last item in the batch
            try:
                last_id = int(self._text(batch[-1].find("id")) or last_id)
            except Exception:
                # If parsing fails, avoid infinite loops by stopping.
                break

            if max_total and fetched >= max_total:
                break

        return results


    def list_newsletter_customer_ids(self, batch_size: int = 200, include_guests: bool = True, max_total: int = 0):
        """Return customer IDs with newsletter=1.

        Primary path uses the Webservice filter[newsletter]=1.
        Some PrestaShop deployments reject that filter (error code 32). In that case
        we fall back to scanning customers and reading the `newsletter` flag.
        """
        try:
            batch_size = int(batch_size or 200)
            if batch_size <= 0:
                batch_size = 200
            max_total = int(max_total or 0)
            offset = 0
            ids = []
            while True:
                limit = batch_size
                if max_total:
                    remaining = max_total - len(ids)
                    if remaining <= 0:
                        break
                    limit = min(limit, remaining)

                params = {
                    "display": "[id]",
                    "filter[newsletter]": "1",
                    "limit": f"{offset},{limit}",
                }
                if not include_guests:
                    params["filter[is_guest]"] = "0"

                root = self.get_xml("customers", params=params)
                batch = [self._text(n.find("id")) for n in root.findall(".//customer") if self._text(n.find("id"))]
                if not batch:
                    break
                ids.extend(batch)
                offset += limit
                if len(batch) < limit:
                    break
            return ids
        except PrestaShopAPIError:
            # Fallback scanner (more compatible, slower)
            ids = []
            nodes = self.list_customers_incremental(
                after_id=0,
                batch_size=batch_size,
                include_guests=include_guests,
                max_total=max_total or 100000,
            )
            for n in nodes:
                cid = self._text(n.find("id"))
                if cid and self._text(n.find("newsletter")) == "1":
                    ids.append(cid)
            return ids


    def list_optin_customer_ids(self, batch_size: int = 200, include_guests: bool = True, max_total: int = 0):
        """Return customer IDs with optin=1.

        Primary path uses the Webservice filter[optin]=1.
        Some PrestaShop deployments reject that filter (error code 32). In that case
        we fall back to scanning customers and reading the `optin` flag.
        """
        try:
            batch_size = int(batch_size or 200)
            if batch_size <= 0:
                batch_size = 200
            max_total = int(max_total or 0)
            offset = 0
            ids = []
            while True:
                limit = batch_size
                if max_total:
                    remaining = max_total - len(ids)
                    if remaining <= 0:
                        break
                    limit = min(limit, remaining)

                params = {
                    "display": "[id]",
                    "filter[optin]": "1",
                    "limit": f"{offset},{limit}",
                }
                if not include_guests:
                    params["filter[is_guest]"] = "0"

                root = self.get_xml("customers", params=params)
                batch = [self._text(n.find("id")) for n in root.findall(".//customer") if self._text(n.find("id"))]
                if not batch:
                    break
                ids.extend(batch)
                offset += limit
                if len(batch) < limit:
                    break
            return ids
        except PrestaShopAPIError:
            ids = []
            nodes = self.list_customers_incremental(
                after_id=0,
                batch_size=batch_size,
                include_guests=include_guests,
                max_total=max_total or 100000,
            )
            for n in nodes:
                cid = self._text(n.find("id"))
                if cid and self._text(n.find("optin")) == "1":
                    ids.append(cid)
            return ids


    @staticmethod
    def _extract_list(root, container_tag: str, item_tag: str):
        items = []
        if root is None:
            return items
        container = root.find(container_tag)
        if container is None:
            return items
        for node in container.findall(item_tag):
            items.append(node)
        return items



    def get_customer(self, customer_id: str):
        root = self.get_xml(f"customers/{customer_id}")
        return root.find("customer")

    def get_address(self, address_id: str):
        root = self.get_xml(f"addresses/{address_id}")
        return root.find("address")

    def get_country(self, country_id: str):
        root = self.get_xml(f"countries/{country_id}")
        return root.find("country")

    def get_state(self, state_id: str):
        root = self.get_xml(f"states/{state_id}")
        return root.find("state")

    def update_customer_consents(self, customer_id: str, newsletter: int | None = None, optin: int | None = None):
        """Update a customer's marketing consent flags.

        PrestaShop Webservice generally requires a full resource payload for PUT.
        We therefore GET the full customer XML, modify the relevant nodes, and PUT it back.
        """
        customer_id = str(customer_id)
        root = self.get_xml(f"customers/{customer_id}")
        customer = root.find("customer")
        if customer is None:
            raise PrestaShopAPIError(f"Customer {customer_id} not found")

        # Ensure nodes exist
        def _ensure_text(tag: str, val: str):
            node = customer.find(tag)
            if node is None:
                node = ET.SubElement(customer, tag)
            node.text = str(val)

        if newsletter is not None:
            _ensure_text("newsletter", str(int(newsletter)))
        if optin is not None:
            _ensure_text("optin", str(int(optin)))

        xml_payload = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
        self.put(f"customers/{customer_id}", xml_payload)
        return True

    def list_addresses_for_customer(self, customer_id: str, batch_size: int = 200, max_total: int = 2000):
        """Return address XML nodes for a given PrestaShop customer ID.

        Important: In PrestaShop 1.7, the customer Webservice resource typically does NOT expose
        addresses as an association. The reliable way is to query the `addresses` resource filtered
        by `id_customer`.

        We try a filter-based query first (fast). If the instance rejects a specific filter
        (error code 32: "This filter does not exist"), we retry with a reduced set of filters.
        """
        batch_size = int(batch_size or 200)
        if batch_size <= 0:
            batch_size = 200
        max_total = int(max_total or 0) or 2000

        results = []

        # Most shops accept filter[id_customer]. Some also accept filter[deleted].
        base_params = {
            "display": "full",
            "limit": f"0,{batch_size}",
            "sort": "[id_ASC]",
            "filter[id_customer]": str(customer_id),
        }

        # First try with deleted filter to reduce noise.
        params = dict(base_params)
        params["filter[deleted]"] = "0"

        try:
            root = self.get_xml("addresses", params=params)
        except PrestaShopAPIError as e:
            if "This filter does not exist" in str(e):
                # Retry without filter[deleted]
                root = self.get_xml("addresses", params=base_params)
            else:
                raise

        batch = self._extract_list(root, "addresses", "address")
        results.extend(batch)

        # In practice, per-customer addresses are few; we keep pagination simple.
        # If the shop returns more than batch_size, we page using limit offsets.
        offset = batch_size
        while batch and len(results) < max_total:
            params2 = dict(params)
            params2["limit"] = f"{offset},{batch_size}"
            try:
                root2 = self.get_xml("addresses", params=params2)
            except PrestaShopAPIError as e:
                if "This filter does not exist" in str(e) and "filter[deleted]" in params2:
                    # Retry without deleted filter
                    params2 = dict(base_params)
                    params2["limit"] = f"{offset},{batch_size}"
                    root2 = self.get_xml("addresses", params=params2)
                else:
                    raise
            batch = self._extract_list(root2, "addresses", "address")
            if not batch:
                break
            results.extend(batch)
            offset += batch_size

        if max_total and len(results) > max_total:
            results = results[:max_total]

        grouped = {}
        for addr in results:
            cid = self._text(addr.find("id_customer"))
            if not cid:
                continue
            grouped.setdefault(cid, []).append(addr)
        return grouped

    def list_addresses_for_customers(self, customer_ids, batch_size: int = 500, max_total: int = 0):
        """Fetch addresses for multiple customers in one call.

        Many PrestaShop instances support: filter[id_customer]=[1|2|3]
        We use that to reduce HTTP calls. If the instance rejects the syntax, callers should
        fall back to per-customer calls.

        Returns: dict[str_customer_id] -> list[address_nodes]
        """
        customer_ids = [str(cid) for cid in (customer_ids or []) if str(cid).strip()]
        if not customer_ids:
            return {}

        batch_size = int(batch_size or 500)
        if batch_size <= 0:
            batch_size = 500
        max_total = int(max_total or 0)

        filter_val = "[" + "|".join(customer_ids) + "]"
        base_params = {
            "display": "full",
            "limit": f"0,{batch_size}",
            "sort": "[id_ASC]",
            "filter[id_customer]": filter_val,
        }

        params = dict(base_params)
        params["filter[deleted]"] = "0"

        try:
            root = self.get_xml("addresses", params=params)
        except PrestaShopAPIError as e:
            if "This filter does not exist" in str(e):
                # Retry without deleted filter
                root = self.get_xml("addresses", params=base_params)
                params = dict(base_params)
            else:
                raise

        results = self._extract_list(root, "addresses", "address")
        offset = batch_size
        batch = results

        while batch:
            if max_total and len(results) >= max_total:
                results = results[:max_total]
                break
            params2 = dict(params)
            params2["limit"] = f"{offset},{batch_size}"
            try:
                root2 = self.get_xml("addresses", params=params2)
            except PrestaShopAPIError as e:
                if "This filter does not exist" in str(e) and "filter[deleted]" in params2:
                    params2 = dict(base_params)
                    params2["limit"] = f"{offset},{batch_size}"
                    root2 = self.get_xml("addresses", params=params2)
                else:
                    raise
            batch = self._extract_list(root2, "addresses", "address")
            if not batch:
                break
            results.extend(batch)
            offset += batch_size

        if max_total and len(results) > max_total:
            results = results[:max_total]

        grouped = {}
        for addr in results:
            cid = self._text(addr.find("id_customer"))
            if not cid:
                continue
            grouped.setdefault(cid, []).append(addr)
        return grouped
