# TODO

Consolidated roadmap and improvement backlog for the PrestaShop Connector.
Ordered by priority within each section.

---

## Code improvements

### High priority

- [ ] **Sanity cap on mass unsubscribes** — refuse to apply a sync pass that would opt-out more than 5% (or a configurable threshold) of a list's active subscribers in one run. Belt-and-suspenders on top of the `news_ok` / `offers_ok` guards, in case a future bug sidesteps them. Log an error and abort the list's sync. Target: `_sync_email_marketing_lists` in `models/prestashop_backend.py`.

- [ ] **Monitoring / alerting on sync errors** — now that the sync aborts gracefully on API failure, operators need to be notified. Add an Odoo activity (or email) when a `sync_email_marketing` log row has `status='error'` with "aborted" in message. Alternative: a dashboard view of recent aborted syncs.

### Medium priority

- [ ] **Factor out `_lookup_partner_by_presta_id(prestashop_id)`** — the pattern "search `prestashop.customer.map` by (backend_id, prestashop_id), return partner, reactivate if inactive" is duplicated in at least four methods: `_apply_webhook_consents`, `_fetch_and_create_customer_from_webhook`, `_reimport_customer_by_presta_id`, `_import_customers`.

- [ ] **Move email-rename logic into `_fetch_and_create_customer_from_webhook`** — the webhook consents handler handles partner+mc email rename inline. The fetch-and-create helper already renames the partner but not the `mailing.contact`. Moving the mc rename there would let every caller benefit, not just the webhook-consents path.

- [ ] **Parallelise the PS API fetches** — `list_newsletter_customer_ids`, `list_optin_customer_ids`, and `list_email_only_subscribers` are called back-to-back sequentially in `_sync_email_marketing_lists`. They're independent, so a `ThreadPoolExecutor` with 3 workers would roughly halve the fetch phase on every run.

### Low priority

- [ ] **Batch `partner.write` calls in `update_tag`** — webhook consents path can issue up to 6 writes on the same partner in a single request (active, email, newsletter tag, offers tag, newsletter_revoked tag, offers_revoked tag). Collapse into one `partner.write({'category_id': [...all ops...]})` where possible.

- [ ] **Constant for the `"0"` customer_id sentinel** — scattered `customer_id != "0"` checks (and `address_id == "0"` in addresses path) would benefit from a named constant or a `_is_real_presta_id(s)` helper.

- [ ] **Harmonise `empty_result` shape with the early-return** — the `no partners` early-return at the top of `_sync_email_marketing_lists` and the `aborted` path both return a zero-counters dict but with different shapes (`aborted` key present or not). Either add the key in both or drop it.

---

## Feature roadmap (out of v1 scope)

### Order import

- [ ] Enable the existing (disabled) "Import Orders" cron and pipeline. Infrastructure is already in place behind a feature toggle. Needs scoping: which statuses sync, do we create sale.orders or invoices, what mapping for product refs, how to handle split/refunds.

### Product sync

- [ ] Only `prestashop.product.map` model exists — no sync logic. Needs a full design pass: direction (Odoo → PS? PS → Odoo?), matching key (reference? EAN?), variants, translations, images, stock.

### Other commerce features

- [ ] Taxes, variants, refunds/returns handling
- [ ] Invoice/payment reconciliation (link PS orders to Odoo invoices)
- [ ] Stock sync (bidirectional or Odoo → PS only)

---

## Config & data tasks (not code changes)

- [ ] **Install the `emailsubscribers` endpoint on mcdavidian.hair** — the PS companion module `prestashopodoo` is installed on `.fr` but not on `.hair`. Without it, email-only newsletter subs (footer block) on the hair shop are invisible to Odoo sync. Deploy the module and configure the webhook secret.

- [ ] **Deduplicate Colleen Shirazi on PS .fr** — customer IDs 954 and 982 share the same email. Pushes from Odoo towards 954 fail with PS error 141 ("email already in use"). Identify the correct record (the one with orders / recent activity) and delete or deactivate the other. This is what causes the recurring `errors=1` in push logs.

- [ ] **Investigate the 121 opt_out on the Newsletter .fr list** — anomalously high count. Likely historical (pre-incident) but worth confirming these were legitimate user opt-outs versus remnants of an earlier bug. Check `write_date` distribution on `mailing.subscription` for list `id=39`.

---

## Known gaps (documented, may or may not need fixing)

- **Email-only subs removed from PS stay in Odoo**: intentional post-revert behaviour. The old orphan-cleanup loop was unsafe. Clean-up has to be manual for now. If a safer automation is desired later, it must come with a cap (see Sanity cap above) and explicit per-email logging.

- **PS webhook may not fire on email changes in some back-office flows**: observed during testing. The `actionObjectCustomerUpdateAfter` hook should catch all updates, but the delivery can be delayed up to several minutes due to the PS webhook queue. For bulk email changes, a manual `_import_customers` run remains the reliable path.

- **PrestaShop API is behind Cloudflare (`.fr`, `.hair`)**: requires a Custom WAF rule `URI Path starts_with "/api/" and ip.src eq <Odoo server IP>` with Skip action, plus Bot Fight Mode OFF. Without this, all customer/address endpoints return 403 and the sync aborts. The current Odoo server IP is `141.95.154.67`.

- **`respect_odoo_opt_out=True`** on every backend: once a contact is opted-out in Odoo, the sync never re-subscribes them even if the PS flag flips back. Only the real-time webhook and an explicit user action can lift the opt_out. This is the intended governance behaviour.
