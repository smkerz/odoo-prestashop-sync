# PrestaShop Connector (Basic) - Odoo 17

Minimal, dependency-free starter connector for **Odoo 17** to import **PrestaShop 1.7** orders.

## Scope (v1)
- Import orders (since a rolling safety window)
- Create/update customers (res.partner)
- Create Sale Orders + lines
- Optional: create missing products from SKU/reference
- Optional: add shipping line using a configured Odoo product

## Out of scope (v1)
Taxes, variants, refunds/returns, invoice/payment reconciliation, stock sync.

## Install
1. Copy this folder into your Odoo addons path.
2. Update apps list.
3. Install **PrestaShop Connector (Basic)**.

## PrestaShop setup
Enable Webservice + create a key with (at least) read access to:
- orders, customers, addresses, countries

## Odoo setup
PrestaShop Connector > Configuration > Backends:
- set base_url and api_key
- Test Connection
- Import Orders Now

Cron exists but is disabled by default: enable it if desired.

