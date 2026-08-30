"""
Batterie de tests pour le module PrestaShop Connector — à coller dans le shell Odoo.

Usage :
    docker exec -it odoo17-admin odoo shell -d mcdavidian --no-http
    >>> exec(open('/path/to/test_battery.py').read())

Ou : copier-coller le contenu directement dans le shell.

Tous les tests sont READ-ONLY (preview=True ou simples lectures).
Aucune écriture en base. Safe à lancer à tout moment.
"""

# === Configuration ===
HAIR_BACKEND_ID = 3
HAIR_LIST_ID = 44
ALL_BACKENDS = [1, 2, 3]

# === Helpers ===
results = []

def _check(name, ok, details=""):
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if details:
        line += f"  ({details})"
    print(line)
    results.append((name, ok, details))


# === Test 1 : API connectivity sur les 3 backends ===
print("\n=== Test 1 : API connectivity ===")
for bid in ALL_BACKENDS:
    b = env['prestashop.backend'].browse(bid)
    try:
        c = b._client()
        ids = c.list_newsletter_customer_ids(batch_size=50, max_total=100)
        _check(f"API NL {b.name}", len(ids) > 0, f"{len(ids)} IDs")
    except Exception as e:
        _check(f"API NL {b.name}", False, str(e)[:80])

    try:
        c = b._client()
        ids = c.list_optin_customer_ids(batch_size=50, max_total=100)
        _check(f"API Optin {b.name}", True, f"{len(ids)} IDs")
    except Exception as e:
        _check(f"API Optin {b.name}", False, str(e)[:80])


# === Test 2 : Patch défensif présent dans le code chargé ===
print("\n=== Test 2 : Defensive patch loaded ===")
import inspect
src = inspect.getsource(env['prestashop.backend']._sync_email_marketing_lists)
_check("news_ok flag present", "news_ok" in src, "patch deployed")
_check("offers_ok flag present", "offers_ok" in src, "patch deployed")
_check("aborted flag in result", "aborted" in src, "patch deployed")
_check("Orphan loop removed", "Catch orphaned contacts" not in src, "revert deployed")


# === Test 3 : Mapping integrity ===
print("\n=== Test 3 : Mapping integrity ===")
for bid in ALL_BACKENDS:
    b = env['prestashop.backend'].browse(bid)
    maps = env['prestashop.customer.map'].search([('backend_id', '=', bid)])
    partners = maps.mapped('partner_id')
    no_email = partners.filtered(lambda p: not p.email)
    _check(f"{b.name}: maps with email", len(no_email) == 0,
           f"{len(maps)} maps, {len(no_email)} sans email")


# === Test 4 : État de la liste hair (pas de catastrophe) ===
print("\n=== Test 4 : Hair list health ===")
opt_out = env['mailing.subscription'].search_count([('list_id', '=', HAIR_LIST_ID), ('opt_out', '=', True)])
total = env['mailing.contact'].search_count([('list_ids', 'in', HAIR_LIST_ID)])
_check("Hair list opt_out near zero", opt_out < 10,
       f"{opt_out} opt_out / {total} total")

# Aucun opt_out massif récent (< 50 dans les 24h)
from datetime import datetime, timedelta
yesterday = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
recent_optout = env['mailing.subscription'].search_count([
    ('list_id', '=', HAIR_LIST_ID),
    ('opt_out', '=', True),
    ('write_date', '>=', yesterday),
])
_check("No mass unsub last 24h", recent_optout < 50,
       f"{recent_optout} opt_out dans les dernieres 24h")


# === Test 5 : Preview sync hair (dry-run, doit montrer 0 ou peu d'unsub) ===
print("\n=== Test 5 : Hair sync preview ===")
backend = env['prestashop.backend'].browse(HAIR_BACKEND_ID)
try:
    result = backend._sync_email_marketing_lists(preview=True)
    nl = result.get('newsletter', {})
    off = result.get('offers', {})
    _check("Newsletter preview computed", not nl.get('aborted'),
           f"sub={nl.get('subscribe', 0)} unsub={nl.get('unsubscribe', 0)} skip={nl.get('skipped', 0)}")
    _check("Newsletter unsub count safe", nl.get('unsubscribe', 0) < 20,
           f"{nl.get('unsubscribe', 0)} unsubscribes prevus")
    _check("Offers preview computed", not off.get('aborted'),
           f"sub={off.get('subscribe', 0)} unsub={off.get('unsubscribe', 0)}")
except Exception as e:
    _check("Preview sync runs", False, str(e)[:80])


# === Test 6 : Preview sync .com et .fr ===
print("\n=== Test 6 : .com and .fr sync preview ===")
for bid in [1, 2]:
    b = env['prestashop.backend'].browse(bid)
    try:
        result = b._sync_email_marketing_lists(preview=True)
        nl = result.get('newsletter', {})
        _check(f"{b.name} preview safe", nl.get('unsubscribe', 0) < 20,
               f"unsub={nl.get('unsubscribe', 0)}")
    except Exception as e:
        _check(f"{b.name} preview", False, str(e)[:80])


# === Test 7 : Cohérence audience PS vs liste Odoo ===
print("\n=== Test 7 : PS vs Odoo audience consistency ===")
b = env['prestashop.backend'].browse(HAIR_BACKEND_ID)
client = b._client()
try:
    nl_ps_count = len(client.list_newsletter_customer_ids(batch_size=200, max_total=5000))
    odoo_count = env['mailing.contact'].search_count([('list_ids', 'in', HAIR_LIST_ID)])
    diff = abs(nl_ps_count - odoo_count)
    _check("PS NL count vs Odoo list count", diff < 20,
           f"PS={nl_ps_count} Odoo={odoo_count} diff={diff}")
except Exception as e:
    _check("Audience check", False, str(e)[:80])


# === Test 8 : Pas d'autre liste affectée par opt_out massif ===
print("\n=== Test 8 : Other mailing lists health ===")
all_lists = env['mailing.list'].search([])
for ml in all_lists:
    if ml.id == HAIR_LIST_ID:
        continue
    optout = env['mailing.subscription'].search_count([
        ('list_id', '=', ml.id), ('opt_out', '=', True),
        ('write_date', '>=', yesterday),
    ])
    if optout > 50:
        _check(f"List {ml.name}", False, f"{optout} opt_out recent suspects")
    else:
        _check(f"List {ml.name}", True, f"{optout} opt_out recent")


# === Résumé ===
print("\n" + "=" * 50)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"RESUME : {passed} PASS / {failed} FAIL sur {len(results)} tests")
if failed:
    print("\nEchecs :")
    for name, ok, details in results:
        if not ok:
            print(f"  - {name}: {details}")
print("=" * 50)
