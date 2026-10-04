# -*- coding: utf-8 -*-
"""Decision rules for pushing consent revocations from Odoo to PrestaShop.

Pure functions on plain sets and dicts (no ORM), so they can be tested without Odoo:
    python tests/test_consent_rules.py

Principle: a consent is revoked in PrestaShop only on a positive signal from
Odoo, never because something is missing there:
  - the email is blacklisted, or
  - its subscription to the list is explicitly opted out.
A contact that is simply absent from the Odoo list (not synced yet, removed by
hand, email changed on the partner) is left alone.
"""


def plan_customer_revocations(customer_emails, presta_news_ids, presta_offers_ids,
                              revoked_news_emails, revoked_offers_emails, blacklisted_emails):
    """Return the consent flags to switch off, per PrestaShop customer.

    customer_emails: {prestashop customer id (str): normalized email} of mapped customers
    presta_news_ids / presta_offers_ids: customer ids currently subscribed in PrestaShop
    revoked_*_emails: emails explicitly opted out of the matching Odoo list
    blacklisted_emails: emails blacklisted in Odoo (revokes both consents)

    Returns {customer id: (newsletter, optin)} where each value is 0 (switch off)
    or None (leave untouched). Customers with nothing to change are left out, so a
    flag PrestaShop already has at 0 never triggers a call.
    """
    plan = {}
    for customer_id, email in customer_emails.items():
        blocked = email in blacklisted_emails
        newsletter = 0 if customer_id in presta_news_ids and (blocked or email in revoked_news_emails) else None
        optin = 0 if customer_id in presta_offers_ids and (blocked or email in revoked_offers_emails) else None
        if newsletter is not None or optin is not None:
            plan[customer_id] = (newsletter, optin)
    return plan


def plan_email_only_revocations(active_emails, revoked_news_emails, blacklisted_emails):
    """Return the email-only newsletter subscribers to deactivate in PrestaShop.

    active_emails: emails with an active row in ps_emailsubscription
    """
    return {e for e in active_emails if e in blacklisted_emails or e in revoked_news_emails}


def count_revocations(customer_plan, email_only_plan):
    """Number of people whose consent a push would revoke."""
    return len(customer_plan) + len(email_only_plan)


def exceeds_cap(revocations, cap):
    """True when an automatic push should be refused. cap <= 0 means no limit."""
    return bool(cap and cap > 0 and revocations > cap)
