# End-to-end tests (test shops + test Odoo)

Plays real scenarios between a PrestaShop **test** shop and an Odoo **test**
database, in both directions, and cleans up after itself. Run over SSH, on the
servers themselves: no API key, no HTTP password and no captcha involved.

Both scripts refuse to run outside a test environment:
- `e2e_shop.php` only runs when the shop domain starts with `dev.`
- `e2e_odoo.py` refuses the production database, and refuses any database in
  which a backend points to a shop whose domain does not start with `dev.`

## Prerequisites

- A test Odoo database with this module, one backend per test shop
  (base URL `https://dev....`, a Webservice key of that shop, a webhook secret).
- On each test shop: module `prestashopodoo` (1.3.2 or later) installed and configured with the
  **test** Odoo webhook URL, the same secret and the backend ID.
- The test Odoo must reach the shop's `/api/` and `/module/prestashopodoo/`
  URLs (if the shop is behind an HTTP password, exempt those two paths).

## One run

Pick a tag (short, lowercase letters/digits), e.g. `run1`. All test data uses
addresses `e2e-<tag>-...@example.invalid`.

1. On the shop server — create the data, webhooks go to Odoo:

       php e2e_shop.php /home/admin/web/dev.mcdavidian.com/public_html setup run1

2. On the Odoo server — check what arrived, then revoke and push back
   (`<container>`, `<test db>` and the backend ID are those of the test Odoo):

       docker exec -i -e E2E_TAG=run1 -e E2E_BACKEND=1 -e E2E_PHASE=check \
           <container> odoo shell -d <test db> --no-http < e2e_odoo.py

3. On the shop server — check what Odoo pushed back:

       php e2e_shop.php /home/admin/web/dev.mcdavidian.com/public_html verify run1

4. Clean up, on both sides:

       php e2e_shop.php /home/admin/web/dev.mcdavidian.com/public_html cleanup run1
       docker exec -i -e E2E_TAG=run1 -e E2E_BACKEND=1 -e E2E_PHASE=cleanup \
           <container> odoo shell -d <test db> --no-http < e2e_odoo.py

Each step prints `PASS` / `FAIL` lines and ends with `OK` or the number of failures.

## Scenarios

| Test contact | What the shop does | Expected in Odoo |
|---|---|---|
| c1news | customer created, newsletter only | partner, mapping, tags, Newsletter list only |
| c2offers | customer created, partner offers only | Partner Offers list only |
| c3toggle | newsletter on, then off | Newsletter subscription opted out |
| c4old → c4new | email changed | partner and mailing contact follow the new email |
| c5addr | address created and updated, a second one created and deleted | one delivery address, updated city |
| e1sub | newsletter form, new address (then the same address again: refused) | mailing contact subscribed, no partner |
| e5bad | newsletter form, invalid address: refused | nothing |
| e2unsub | newsletter form, subscribed then unsubscribed (the shop deletes the row) | opted out at once (prestashopodoo >= 1.3.2) |
| c9unsub | customer with newsletter unsubscribes through the newsletter form | opted out at once |
| c8block | existing customer with partner offers uses the newsletter form | both lists, optin untouched |
| e4deact | row deactivated directly in the database | opted out by the consent sync (cron path) |

| Test contact | What Odoo does | Expected in the shop |
|---|---|---|
| c6optout | Newsletter subscription opted out | newsletter=0, optin unchanged |
| c7black | email blacklisted | newsletter=0 and optin=0 |
| e3optout | Newsletter subscription opted out | email-only row deactivated |
| c1news, c2offers, e1sub | nothing | unchanged |

The newsletter form scenarios call the code of `ps_emailsubscription` directly
(what the footer form runs); they need the captcha module (`eicaptcha`) disabled
on the test shop.

Not covered: the captcha itself, and the signature check, which has its own
unit tests in `tests/test_webhook_controller.py`.
