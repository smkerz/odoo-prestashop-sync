"""End-to-end test, Odoo side. TEST DATABASE ONLY.

Run inside `odoo shell` (the `env` variable comes from the shell), see README.md
in this folder. Settings come from environment variables:

    E2E_TAG      same tag as given to e2e_shop.php
    E2E_BACKEND  id of the prestashop.backend record of the test shop
    E2E_PHASE    "check" (default) or "cleanup"

"check" verifies what the shop sent, then revokes a few consents in Odoo and
pushes them, so that `e2e_shop.php ... verify` can check the way back.
"""
import os
from urllib.parse import urlparse

PRODUCTION_DATABASES = {"mcdavidian"}

TAG = os.environ["E2E_TAG"]
PHASE = os.environ.get("E2E_PHASE", "check")
backend = env["prestashop.backend"].browse(int(os.environ["E2E_BACKEND"]))  # noqa: F821 (odoo shell)

failures = []


def refuse(reason):
    raise SystemExit("REFUSED: " + reason)


if env.cr.dbname in PRODUCTION_DATABASES:
    refuse("this is the production database (%s)" % env.cr.dbname)
if not backend.exists():
    refuse("backend %s does not exist" % os.environ["E2E_BACKEND"])
# The blacklist step pushes to EVERY backend of the database: none may be a real shop.
for b in env["prestashop.backend"].search([]):
    host = urlparse(b.base_url or "").netloc
    if not host.startswith("dev."):
        refuse("backend %r points to %s, which is not a test shop" % (b.name, host))


def email(name):
    return "e2e-%s-%s@example.invalid" % (TAG, name)


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(("PASS " if ok else "FAIL ") + label + ("  (%s)" % detail if detail and not ok else ""))


def partner(name):
    return env["res.partner"].with_context(active_test=False).search([("email", "=ilike", email(name))])


def contact(name):
    return env["mailing.contact"].search([("email_normalized", "=", email(name))], limit=1)


def subscription(name, mailing_list):
    mc = contact(name)
    return backend._list_subscription(mc, mailing_list) if mc else None


def subscribed(name, mailing_list):
    sub = subscription(name, mailing_list)
    return sub is not None and not sub.opt_out


def opted_out(name, mailing_list):
    sub = subscription(name, mailing_list)
    return sub is not None and bool(sub.opt_out)


news = backend._ensure_mailing_list("newsletter")
offers = backend._ensure_mailing_list("offers")
client = backend._client()
print("== %s on database %s, backend %s, tag %s ==" % (PHASE, env.cr.dbname, backend.name, TAG))

if PHASE == "check":
    # --- what the shop sent through webhooks ---------------------------------
    p = partner("c1news")
    mapped = env["prestashop.customer.map"].search([("backend_id", "=", backend.id), ("partner_id", "in", p.ids)])
    check("c1: customer created and mapped", len(p) == 1 and len(mapped) == 1)
    check("c1: tagged as PrestaShop customer",
          len(p) == 1 and backend.customer_tag_id in p.category_id and backend.site_tag_id in p.category_id)
    check("c1: subscribed to Newsletter only", subscribed("c1news", news) and not subscribed("c1news", offers))
    check("c2: subscribed to Partner Offers only", subscribed("c2offers", offers) and not subscribed("c2offers", news))
    check("c3: newsletter switched off in the shop -> opted out", opted_out("c3toggle", news))

    check("c4: email change followed on the partner", len(partner("c4new")) == 1 and not partner("c4old"))
    check("c4: mailing contact renamed, still subscribed",
          subscribed("c4new", news) and not contact("c4old"))

    p = partner("c5addr")
    children = env["res.partner"].search([("parent_id", "in", p.ids), ("type", "=", "delivery")])
    check("c5: one address left, with the updated city",
          len(children) == 1 and children.city == "Lyon",
          "addresses=%s cities=%s" % (len(children), children.mapped("city")))

    check("c6 and c7: subscribed to both lists",
          all(subscribed(n, l) for n in ("c6optout", "c7black") for l in (news, offers)))

    check("e1: email-only subscriber on the Newsletter list, without partner",
          subscribed("e1sub", news) and not partner("e1sub"))
    check("e2: unsubscribed through the newsletter block -> opted out", opted_out("e2unsub", news))
    check("e3: email-only subscriber on the Newsletter list", subscribed("e3optout", news))

    # --- what only the cron can see -------------------------------------------
    check("e4: still subscribed before the sync (deactivated in the shop without hook)", subscribed("e4deact", news))
    result = backend._sync_email_marketing_lists(client=client, preview=False)
    check("e4: consent sync opts out the row deactivated in the shop",
          opted_out("e4deact", news) and result["newsletter"].get("email_only_deactivated", 0) >= 1,
          "result=%s" % result["newsletter"])
    check("sync leaves the other test contacts as they were",
          subscribed("c1news", news) and subscribed("e1sub", news) and opted_out("c3toggle", news))

    # --- revocations decided in Odoo, pushed to the shop ----------------------
    subscription("c6optout", news).write({"opt_out": True})
    subscription("e3optout", news).write({"opt_out": True})
    env["mail.blacklist"].sudo()._add(email("c7black"))
    plan = backend._push_opt_outs_to_prestashop(client, preview=True)
    print("push preview: %s" % plan)
    stats = backend._push_opt_outs_to_prestashop(client, enforce_cap=False)
    print("push result:  %s" % stats)
    check("push planned at least the three test revocations", plan["customers"] >= 2 and plan["email_only"] >= 1, str(plan))
    check("push to the shop finished without error", stats["errors"] == 0 and not stats["aborted"], str(stats))
    env.cr.commit()
    print('Next: run e2e_shop.php with "verify".')

elif PHASE == "cleanup":
    pattern = "e2e-%s-%%@example.invalid" % TAG
    partners = env["res.partner"].with_context(active_test=False).search([("email", "=ilike", pattern)])
    children = env["res.partner"].with_context(active_test=False).search([("parent_id", "in", partners.ids)])
    contacts = env["mailing.contact"].search([("email", "=ilike", pattern)])
    blacklist = env["mail.blacklist"].sudo().with_context(active_test=False).search([("email", "=ilike", pattern)])
    print("deleting %s partners, %s addresses, %s mailing contacts, %s blacklist entries"
          % (len(partners), len(children), len(contacts), len(blacklist)))
    blacklist.unlink()
    contacts.unlink()
    (children | partners).unlink()
    env.cr.commit()

else:
    refuse("unknown E2E_PHASE %r" % PHASE)

print("\n%s check(s) FAILED: %s" % (len(failures), failures) if failures else "\nOK")
