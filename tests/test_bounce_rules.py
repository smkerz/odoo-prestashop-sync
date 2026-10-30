"""Standalone tests for the bounce rules (no Odoo needed).

Run from the module folder:
    python tests/test_bounce_rules.py
"""
import email
import email.policy
import importlib.util
import os
import unittest

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "bounce_rules.py")
spec = importlib.util.spec_from_file_location("bounce_rules_under_test", RULES_PATH)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

REPORT = """\
From: MAILER-DAEMON@example.invalid
To: sender@example.invalid
Content-Type: multipart/report; report-type=delivery-status; boundary="b"

--b
Content-Type: text/plain

Undelivered.
--b
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.example.invalid

Final-Recipient: rfc822; a@example.invalid
Action: {action}
Status: {status}
Diagnostic-Code: smtp; {diagnostic}

--b--
"""


def dead(status, diagnostic="", action="failed"):
    return rules.is_dead_address(action, status, diagnostic)


class TestIsDeadAddress(unittest.TestCase):
    def test_codes_that_designate_the_address(self):
        for status in ("5.1.1", "5.1.3", "5.1.10", "5.4.4"):
            self.assertTrue(dead(status, "550 no details"), status)

    def test_generic_codes_need_an_explicit_text(self):
        self.assertTrue(dead("5.0.0", "550 Address unknown"))
        self.assertTrue(dead("5.0.0", "554 This mailbox is disabled"))
        self.assertTrue(dead("5.5.0", "550 No such user here"))
        self.assertFalse(dead("5.0.0", "550 Message was not accepted"))
        self.assertFalse(dead("5.5.0", "550 mailbox unavailable"))

    def test_refusal_aimed_at_the_sender_is_never_a_dead_address(self):
        self.assertFalse(dead("5.7.1", "554 Service unavailable; listed on a DNSBL"))
        self.assertFalse(dead("5.1.1", "550 5.1.1 rejected by local policy"))
        self.assertFalse(dead("5.0.0", "550 user unknown or message looks like spam"))
        self.assertFalse(dead("5.4.1", "550 5.4.1 Recipient address rejected: Access denied"))

    def test_full_mailbox_and_temporary_failures_are_left_alone(self):
        self.assertFalse(dead("5.2.2", "552 Mailbox is full"))
        self.assertFalse(dead("4.4.1", "connection timed out"))
        self.assertFalse(dead("5.1.1", "user unknown", action="delayed"))


class TestReadReport(unittest.TestCase):
    def _read(self, text):
        return rules.read_report(email.message_from_string(text, policy=email.policy.SMTP))

    def test_reads_action_status_and_diagnostic(self):
        text = REPORT.format(action="Failed", status="5.1.1 (user unknown)", diagnostic="550 5.1.1 User unknown")
        self.assertEqual(self._read(text), ("failed", "5.1.1", "smtp; 550 5.1.1 User unknown"))

    def test_message_without_report_gives_empty_values(self):
        self.assertEqual(self._read("From: a@example.invalid\n\nHello"), ("", "", ""))


if __name__ == "__main__":
    unittest.main()
