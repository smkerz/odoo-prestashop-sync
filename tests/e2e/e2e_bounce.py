"""Bounce rule, end-to-end through the mail gateway. TEST DATABASE ONLY.

Run inside `odoo shell` (the `env` variable comes from the shell):

    <container> odoo shell -d <test db> --no-http < e2e_bounce.py

Feeds delivery reports to `mail.thread.message_process`, as the incoming mail server
would, and checks which addresses reach the blacklist. Nothing is committed in Odoo:
everything is rolled back at the end. Each blacklisted address is pushed to the test shops
(all addresses are @example.invalid, so no consent changes there).
"""
import uuid
from urllib.parse import urlparse

PRODUCTION_DATABASES = {"mcdavidian"}
PARAM = "prestashop_connector.blacklist_dead_bounces"

if env.cr.dbname in PRODUCTION_DATABASES:  # noqa: F821 (odoo shell)
    raise SystemExit("REFUSED: this is the production database (%s)" % env.cr.dbname)  # noqa: F821
# The blacklist step pushes to EVERY backend of the database: none may be a real shop.
for b in env["prestashop.backend"].search([]):  # noqa: F821
    if not urlparse(b.base_url or "").netloc.startswith("dev."):
        raise SystemExit("REFUSED: backend %r is not a test shop" % b.name)

failures = []
Blacklist = env["mail.blacklist"].with_context(active_test=True)  # noqa: F821
mailing = env["mailing.mailing"].create({  # noqa: F821
    "subject": "e2e bounce",
    "body_html": "<p>e2e</p>",
    "mailing_model_id": env.ref("mass_mailing.model_mailing_contact").id,  # noqa: F821
})


def address(name):
    return "e2e-bounce-%s-%s@example.invalid" % (name, uuid.uuid4().hex[:8])


def sent_to(email_address):
    """Record a mail sent to this address and return its Message-Id."""
    contact = env["mailing.contact"].create({"name": "e2e", "email": email_address})  # noqa: F821
    message_id = "<%s-openerp-%d-mailing.contact@example.invalid>" % (uuid.uuid4().hex, contact.id)
    env["mailing.trace"].create({  # noqa: F821
        "model": "mailing.contact",
        "res_id": contact.id,
        "email": email_address,
        "message_id": message_id,
        "mass_mailing_id": mailing.id,
    })
    return message_id


def report(email_address, message_id, status, diagnostic):
    return (
        "From: MAILER-DAEMON@example.invalid\r\n"
        "To: sender@example.invalid\r\n"
        "Subject: Undelivered\r\n"
        "Message-Id: <%s@example.invalid>\r\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="b"\r\n\r\n'
        "--b\r\nContent-Type: text/plain\r\n\r\nUndelivered.\r\n"
        "--b\r\nContent-Type: message/delivery-status\r\n\r\n"
        "Reporting-MTA: dns; mx.example.invalid\r\n\r\n"
        "Final-Recipient: rfc822; %s\r\nAction: failed\r\nStatus: %s\r\n"
        "Diagnostic-Code: smtp; %s\r\n\r\n"
        "--b\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-Id: %s\r\n\r\n"
        "--b--\r\n" % (uuid.uuid4().hex, email_address, status, diagnostic, message_id)
    ).encode()


def scenario(label, email_address, message_id, status, diagnostic, expected):
    env["mail.thread"].message_process(False, report(email_address, message_id, status, diagnostic))  # noqa: F821
    blocked = bool(Blacklist.search_count([("email", "=", email_address)]))
    if blocked != expected:
        failures.append(label)
    print(("PASS " if blocked == expected else "FAIL ") + label)


set_param = env["ir.config_parameter"].sudo().set_param  # noqa: F821
try:
    set_param(PARAM, "0")
    a = address("off")
    scenario("off by default: nothing blocked", a, sent_to(a), "5.1.1", "550 User unknown", False)

    set_param(PARAM, "1")
    a = address("dead")
    scenario("dead address blocked", a, sent_to(a), "5.1.1", "550 User unknown", True)
    a = address("trace")
    message_id = sent_to(a)
    scenario("bounce counted on the mailing", a, message_id, "5.2.2", "552 Mailbox is full", False)
    trace = env["mailing.trace"].search([("message_id", "=", message_id)])  # noqa: F821
    if trace.trace_status != "bounce":
        failures.append("trace status")
    print(("PASS " if trace.trace_status == "bounce" else "FAIL ") + "trace marked as bounced")
    a = address("policy")
    scenario("refusal by policy not blocked", a, sent_to(a), "5.7.1", "554 rejected by policy", False)
    a = address("forged")
    scenario("forged report not blocked", a, "<unknown@example.invalid>", "5.1.1", "550 User unknown", False)
    a = address("customer")
    env["res.partner"].create({  # noqa: F821
        "name": "e2e customer",
        "email": a,
        "category_id": [(4, env["res.partner.category"].create({"name": "Client Prestashop"}).id)],  # noqa: F821
    })
    scenario("customer not blocked", a, sent_to(a), "5.1.1", "550 User unknown", False)
finally:
    env.cr.rollback()  # noqa: F821

print("FAILED: %s" % ", ".join(failures) if failures else "ALL PASSED")
