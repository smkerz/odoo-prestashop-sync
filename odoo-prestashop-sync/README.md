# PrestaShop Connector (Basic) — Odoo 17

Minimal connector for **Odoo 17** and **PrestaShop 1.7+**.
Syncs customers, addresses, and marketing consents (newsletter / partner offers) between the two platforms.

## Features

### Customer Import
- Incremental import by PrestaShop customer ID (no re-import of already synced customers)
- Deduplication by email (if mapping is lost, the customer is matched by email)
- Optional: include guest checkout customers (`include_guest_customers`)
- Per-site tag (e.g. "Client Prestashop — shop.example.com")

### Address Sync
- Imported as child contacts (type "Delivery") under the main customer
- Deduplication by address signature (street, zip, city, country, phone)
- Real-time via webhooks (create / update / delete)
- Weekly full scan cron as safety net

### Marketing Consents

**PrestaShop → Odoo:**
- Syncs `newsletter` and `optin` fields from PrestaShop
- Creates one mailing list per site: "Newsletter (hostname)" and "Partner Offers (hostname)"
- Applies tags on contacts (newsletter / partner offers)
- Respects `respect_odoo_opt_out`: never re-subscribes a contact who opted out in Odoo

**Odoo → PrestaShop (revocation-only):**
- When a contact is opted out of a mailing list → pushes `newsletter=0` to PrestaShop
- When an email is blacklisted → pushes `newsletter=0` AND `optin=0` to all backends
- Real-time push on manual opt-out and email blacklist (via model hooks)
- Async push on email unsubscribe link click (via controller hook, no page delay)
- Cron as fallback (recommended: every 15 minutes)

**Important:** Odoo → PrestaShop is **revocation-only**. Odoo never pushes `newsletter=1` or `optin=1` to PrestaShop.

### Webhooks
- HMAC-SHA256 signature verification on all endpoints
- `POST /prestashop/webhook/consents` — real-time consent changes
- `POST /prestashop/webhook/addresses` — real-time address create/update/delete
- `GET  /prestashop/webhook/ping` — health check

### Multi-backend
- Each backend = one PrestaShop site
- Separate tags, mailing lists, mappings, and logs per backend
- Blacklist is global: affects all backends

## Prerequisites

- Odoo 17 (Community or Enterprise)
- PrestaShop 1.7+
- Odoo modules: `sale_management`, `stock`, `contacts`, `mass_mailing`

## Install

1. Copy this folder into your Odoo addons path
2. Update the apps list
3. Install **PrestaShop Connector (Basic)**

## PrestaShop Setup

Enable Webservice in **Advanced Parameters > Webservice** and create an API key with:

| Permission | Resources |
|------------|-----------|
| **GET** | `customers`, `addresses`, `countries`, `states`, `languages` |
| **PUT** | `customers` |

## Odoo Setup

### System Parameters
- Verify that `web.base.url` points to your Odoo instance (e.g. `https://odoo.example.com`)
- **No trailing slash!** A trailing slash breaks email unsubscribe links (`https://odoo.example.com/` → double slash in URLs)

### Create a Backend
Go to **PrestaShop Connector > Configuration > Backends > Create**:

| Field | Value |
|-------|-------|
| Name | Your shop name |
| Base URL | PrestaShop URL (e.g. `https://shop.example.com`) |
| API Key | The key created in PrestaShop |
| Webhook Secret | A shared secret (e.g. `myS3cretKey!`) — must be identical in PrestaShop and Odoo |

Click **Test** → should display "Connection successful".

### Customer Tags
In the **Customers** tab of the backend:
- `customer_tag_id` is auto-created on first import
- `newsletter_tag_id` and `partner_offers_tag_id`: create manually if empty
- `include_guest_customers` is checked by default

### Webhooks (optional, for real-time)
Requires a PHP module on the PrestaShop side to send webhooks. Without it, use the crons.

Example curl to test:

```bash
BODY='{"backend_id":1,"customer_id":3,"newsletter":"1","optin":"0","shop_url":"https://shop.example.com"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "myS3cretKey!" | awk '{print $2}')
curl -X POST https://odoo.example.com/prestashop/webhook/consents \
  -H "Content-Type: application/json" \
  -H "X-Prestashop-Signature: $SIG" \
  -d "$BODY"
```

## Crons

All crons are **inactive by default**. Activate them in **Settings > Technical > Scheduled Actions**.

| Cron | Interval | Purpose |
|------|----------|---------|
| Import Customers | 6 hours | Import new customers from PrestaShop |
| Sync Consents (Presta → Odoo) | 2 hours | Sync newsletter/optin flags to Odoo |
| Sync Consents (Odoo → Presta) | 1 hour | Push opt-outs to PrestaShop (fallback for email unsubscribe) |
| Full Scan Addresses (Weekly) | 1 week | Full address resync, safety net |
| Import Orders | 15 min | Disabled (feature toggle off in v1) |

**Recommendation:** set "Sync Consents (Odoo → Presta)" to **15 minutes** for faster propagation of unsubscribes.

## Architecture

```
PrestaShop                          Odoo
┌──────────┐   GET /api/customers   ┌─────────────────────┐
│          │ ◄───────────────────── │  Import Customers    │
│          │   GET /api/addresses   │  Sync Addresses      │
│          │ ◄───────────────────── │  Sync Consents PS→OD │
│          │                        │                      │
│          │   PUT /api/customers   │  Push Opt-outs OD→PS │
│          │ ──────────────────────►│  (revocation-only)   │
│          │                        │                      │
│  Webhook │   POST /webhook/*      │  Real-time webhooks  │
│  Module  │ ──────────────────────►│  (consents/addresses)│
└──────────┘                        └─────────────────────┘
```

## Out of Scope (v1)

- Order import (infrastructure ready, feature toggle disabled)
- Product sync
- Taxes, variants, refunds/returns
- Invoice/payment reconciliation
- Stock sync

## License

LGPL-3
