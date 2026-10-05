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
from datetime import datetime, timedelta
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
    check("test customers are new to Odoo (no id collision, tag used once)",
          len(p) == 1 and p.create_date >= datetime.now() - timedelta(days=1),
          "partners=%s created=%s" % (len(p), p.mapped("create_date")))
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
    # Reported by the prestashopodoo "before" hook (module >= 1.3.2): the shop
    # deletes the row, so the sync could never see this unsubscription.
    check("e2: form unsubscription of a visitor is known at once", opted_out("e2unsub", news))
    check("c9: form unsubscription of a customer is known at once", opted_out("c9unsub", news))
    check("e3: email-only subscriber on the Newsletter list", subscribed("e3optout", news))
    check("e5: the refused invalid address reached nothing in Odoo",
          not env["mailing.contact"].search([("email", "=ilike", "e2e-%s-e5bad%%" % TAG)]))
    check("c8: customer who used the newsletter block is on both lists (optin untouched)",
          subscribed("c8block", news) and subscribed("c8block", offers),
          "news=%s offers=%s" % (subscribed("c8block", news), subscribed("c8block", offers)))

    p = partner("c10dup")
    maps = env["prestashop.customer.map"].search([("backend_id", "=", backend.id), ("partner_id", "in", p.ids)])
    check("c10: guest order of a known customer is linked to the same contact",
          len(p) == 1 and len(maps) == 2, "contacts=%s mappings=%s" % (len(p), len(maps)))
    kids = env["res.partner"].search([("parent_id", "in", p.ids), ("type", "=", "delivery")])
    check("c10: address of the guest order is attached to the contact",
          len(kids) == 1 and kids.city == "Nantes", "addresses=%s cities=%s" % (len(kids), kids.mapped("city")))

    # --- what only the cron can see -------------------------------------------
    check("e4: still subscribed before the sync (deactivated in the shop without hook)", subscribed("e4deact", news))
    result = backend._sync_email_marketing_lists(client=client, preview=False)
    check("e4: consent sync opts out the row deactivated in the shop",
          opted_out("e4deact", news) and result["newsletter"].get("email_only_deactivated", 0) >= 1,
          "result=%s" % result["newsletter"])
    check("e2 and c9: still opted out after the sync", opted_out("e2unsub", news) and opted_out("c9unsub", news))
    check("c8 and e1: still subscribed after the sync",
          subscribed("c8block", news) and subscribed("c8block", offers) and subscribed("e1sub", news))
    check("sync leaves the other test contacts as they were",
          subscribed("c1news", news) and subscribed("e1sub", news) and opted_out("c3toggle", news))

    # --- revocations decided in Odoo, pushed to the shop ----------------------
    # Opt-outs written straight on the subscription trigger nothing by themselves:
    # this is the path the cron covers.
    subscription("c6optout", news).write({"opt_out": True})
    subscription("e3optout", news).write({"opt_out": True})
    subscription("c10dup", news).write({"opt_out": True})
    plan = backend._push_opt_outs_to_prestashop(client, preview=True)
    print("push preview: %s" % plan)
    check("preview announces the test revocations (c6, both rows of c10, e3)",
          plan["customers"] >= 3 and plan["email_only"] >= 1, str(plan))
    stats = backend._push_opt_outs_to_prestashop(client, enforce_cap=False)
    print("push result:  %s" % stats)
    check("push applied them, the guest row through the module",
          stats["updated"] >= 3 and stats["email_only_unsub"] >= 1 and stats["errors"] == 0 and not stats["aborted"], str(stats))
    again = backend._push_opt_outs_to_prestashop(client, preview=True)
    check("nothing is planned twice", again["customers"] <= stats["errors"] and again["email_only"] == 0, str(again))

    # Blacklisting pushes by itself, in real time (no explicit push here on purpose).
    env["mail.blacklist"].sudo()._add(email("c7black"))
    # --- notifications -----------------------------------------------------------
    stats = backend._activity_since(datetime.now() - timedelta(hours=1))
    print("activity over the last hour: %s" % stats)
    check("activity counters see the run",
          stats["new_customers"] >= 9 and stats["newsletter_opted_out"] >= 5 and stats["revoked_in_shop"] >= 4, str(stats))
    saved = backend.read(["alert_email", "notify_level", "last_digest_date", "volume_alert_date", "mass_unsub_alert_threshold"])[0]
    recipient = "e2e-%s-operator@example.invalid" % TAG
    backend.write({"alert_email": recipient, "notify_level": "each", "last_digest_date": datetime.now() - timedelta(hours=1),
                   "volume_alert_date": False, "mass_unsub_alert_threshold": 3})
    env["prestashop.backend"].cron_send_notifications()
    subjects = env["mail.mail"].sudo().search([("email_to", "=", recipient)]).mapped("subject")
    check("a summary email was prepared for the operator", any("Résumé" in (x or "") for x in subjects), str(subjects))
    check("a wave of opt-outs triggers an alert email", any("désinscriptions en une heure" in (x or "") for x in subjects), str(subjects))
    env["mail.mail"].sudo().search([("email_to", "=", recipient)]).unlink()
    backend.write({k: saved[k] for k in ("alert_email", "notify_level", "last_digest_date", "volume_alert_date", "mass_unsub_alert_threshold")})

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
