# -*- coding: utf-8 -*-
"""Decision rules for setting aside addresses that no longer exist, from a bounce report.

Pure functions on plain values and standard email messages (no ORM), so they can be
tested without Odoo:
    python tests/test_bounce_rules.py

Principle: an address is set aside only when the report says the address itself is gone.
A refusal aimed at the sender (spam filter, blocklist, local policy), a full mailbox or a
temporary failure says nothing about the address, and is left alone. When in doubt, the
answer is no: Odoo's own rule (5 bounces over more than a week) still applies afterwards.
"""
import re

# Enhanced status codes (RFC 3463) that designate the address or its domain.
DEAD_STATUSES = {"5.1.1", "5.1.3", "5.1.10", "5.4.4"}
# Generic codes: too vague alone, accepted only when the server's text is explicit.
GENERIC_STATUSES = {"5.0.0", "5.5.0"}

SENDER_REFUSAL_RE = re.compile(
    r"spam|polic|block|blacklist|dnsbl|\brbl\b|reputation|abuse|denied|not allowed|"
    r"prohibited|quota|mailbox (is )?full|over ?limit",
    re.IGNORECASE,
)
DEAD_TEXT_RE = re.compile(
    r"user unknown|unknown user|unknown recipient|no such (user|recipient|mailbox|address)|"
    r"(user|recipient|mailbox|address)( \S+)? (does not|doesn'?t) exist|"
    r"(user|recipient|mailbox) not found|invalid (recipient|mailbox)|address unknown|"
    r"unrouteable address|mailbox is disabled|user is terminated|host or domain name not found",
    re.IGNORECASE,
)
STATUS_RE = re.compile(r"\b([245]\.\d{1,3}\.\d{1,3})\b")


def read_report(email_message):
    """Return (action, status, diagnostic) of the first recipient of a delivery report.

    email_message: a standard email.message.EmailMessage.
    Values are empty strings when the report does not hold them.
    """
    for part in email_message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        blocks = part.get_payload()
        if isinstance(blocks, list) and len(blocks) > 1:
            block = blocks[1]
            status = STATUS_RE.search(str(block.get("Status") or ""))
            return (
                str(block.get("Action") or "").strip().lower(),
                status.group(1) if status else "",
                " ".join(str(block.get("Diagnostic-Code") or "").split()),
            )
    return "", "", ""


def is_dead_address(action, status, diagnostic):
    """True if the report says the address itself no longer exists."""
    if action != "failed" or SENDER_REFUSAL_RE.search(diagnostic or ""):
        return False
    if status in DEAD_STATUSES:
        return True
    return status in GENERIC_STATUSES and bool(DEAD_TEXT_RE.search(diagnostic or ""))
