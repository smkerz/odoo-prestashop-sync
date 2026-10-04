"""Same as _add_category_to_products.py but with .fr product IDs."""
import os
import sys
import urllib.request
import urllib.error
from xml.etree import ElementTree as ET
from base64 import b64encode

PS_URL = os.environ.get("PS_URL", "https://mcdavidian.fr")
PS_KEY = os.environ.get("PS_KEY", "")
CATEGORY_ID = int(os.environ.get("CATEGORY_ID", "0"))
PRODUCT_IDS = [
    15,    # barrette-rectangle-tgm
    140,   # barrette-chat-qui-dort-gm
    656,   # barrette-dauphins-gm
    2544,  # barrette-boucles
    1992,  # pince-love-pm
    1990,  # pince-love-gm
    66,    # pince-marguerite
    57,    # pince-assemblage-pm
    55,    # pince-assemblage-mm
    2532,  # peigne-flamenco
    2226,  # peigne-rockn-roll
    25,    # serre-tete-entrelacement
    1232,  # serre-tete-renaissance
]

if not PS_KEY or CATEGORY_ID == 0:
    print("ERROR: set PS_KEY and CATEGORY_ID environment variables", file=sys.stderr)
    sys.exit(1)

DRY_RUN = "--apply" not in sys.argv

def auth_header():
    creds = f"{PS_KEY}:".encode()
    return "Basic " + b64encode(creds).decode()

def http(method, url, body=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", auth_header())
    if body:
        req.add_header("Content-Type", "application/xml")
        req.data = body.encode("utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return f"HTTP_ERROR_{e.code}: {e.read().decode('utf-8', errors='ignore')[:500]}"

def add_category_to_product(pid):
    url = f"{PS_URL}/api/products/{pid}"
    print(f"\n[Product {pid}] GET {url}")
    xml_str = http("GET", url)
    if xml_str.startswith("HTTP_ERROR"):
        print(f"  FAILED to fetch: {xml_str[:200]}")
        return False

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        print(f"  PARSE ERROR: {e}")
        return False

    product = root.find("product")
    if product is None:
        return False

    associations = product.find("associations")
    if associations is None:
        associations = ET.SubElement(product, "associations")

    categories = associations.find("categories")
    if categories is None:
        categories = ET.SubElement(associations, "categories")
        categories.set("nodeType", "category")
        categories.set("api", "categories")

    existing = [c.find("id").text for c in categories.findall("category") if c.find("id") is not None]
    print(f"  Current categories: {existing}")
    if str(CATEGORY_ID) in existing:
        print(f"  Category {CATEGORY_ID} ALREADY assigned, skipping")
        return True

    new_cat = ET.SubElement(categories, "category")
    new_id = ET.SubElement(new_cat, "id")
    new_id.text = str(CATEGORY_ID)

    for tag_name in ("manufacturer_name", "quantity", "position_in_category", "type"):
        elem = product.find(tag_name)
        if elem is not None:
            product.remove(elem)

    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    body = '<?xml version="1.0" encoding="UTF-8"?>\n' + body

    if DRY_RUN:
        print(f"  DRY_RUN: would PUT product with new category {CATEGORY_ID}")
        return True

    print(f"  PUT {url}")
    result = http("PUT", url, body)
    if result.startswith("HTTP_ERROR"):
        print(f"  FAILED: {result[:300]}")
        return False
    print(f"  SUCCESS")
    return True


def main():
    print(f"PS_URL = {PS_URL}")
    print(f"CATEGORY_ID = {CATEGORY_ID}")
    print(f"PRODUCT_IDS = {PRODUCT_IDS}")
    print(f"MODE = {'DRY_RUN' if DRY_RUN else 'APPLY'}")

    success = 0
    failures = []
    for pid in PRODUCT_IDS:
        if add_category_to_product(pid):
            success += 1
        else:
            failures.append(pid)

    print(f"\n=== SUMMARY ===")
    print(f"Success: {success}/{len(PRODUCT_IDS)}")
    if failures:
        print(f"Failures: {failures}")


if __name__ == "__main__":
    main()
