"""Standalone tests for the Odoo -> PrestaShop revocation rules (no Odoo needed).

Run from the module folder:
    python tests/test_consent_rules.py
"""
import importlib.util
import os
import unittest

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "consent_rules.py")
spec = importlib.util.spec_from_file_location("consent_rules_under_test", RULES_PATH)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

A, B, C = "a@example.invalid", "b@example.invalid", "c@example.invalid"


def plan(customers, news=(), offers=(), revoked_news=(), revoked_offers=(), blacklisted=()):
    return rules.plan_customer_revocations(
        customers, set(news), set(offers), set(revoked_news), set(revoked_offers), set(blacklisted))


class TestCustomerRevocations(unittest.TestCase):
    def test_explicit_opt_out_is_pushed(self):
        self.assertEqual(plan({"1": A}, news={"1"}, revoked_news={A}), {"1": (0, None)})

    def test_absent_from_the_odoo_list_is_not_a_revocation(self):
        # Subscribed in PrestaShop, unknown to the Odoo list: not synced yet,
        # removed by hand or email changed on the partner. Must be left alone.
        self.assertEqual(plan({"1": A}, news={"1"}, offers={"1"}), {})

    def test_each_list_is_independent(self):
        self.assertEqual(plan({"1": A}, news={"1"}, offers={"1"}, revoked_offers={A}), {"1": (None, 0)})
        self.assertEqual(plan({"1": A}, news={"1"}, offers={"1"}, revoked_news={A}, revoked_offers={A}), {"1": (0, 0)})

    def test_blacklist_revokes_both_consents(self):
        self.assertEqual(plan({"1": A}, news={"1"}, offers={"1"}, blacklisted={A}), {"1": (0, 0)})

    def test_nothing_is_sent_when_prestashop_is_already_off(self):
        self.assertEqual(plan({"1": A}, revoked_news={A}, revoked_offers={A}, blacklisted={A}), {})
        self.assertEqual(plan({"1": A}, news={"1"}, blacklisted={A}), {"1": (0, None)})

    def test_unknown_prestashop_state_pushes_nothing(self):
        # When the PrestaShop lists could not be fetched they are empty.
        self.assertEqual(plan({"1": A, "2": B}, revoked_news={A}, blacklisted={B}), {})

    def test_duplicate_customers_only_the_subscribed_one_is_touched(self):
        # Two PrestaShop accounts share an email; only account 2 is subscribed.
        self.assertEqual(plan({"1": A, "2": A}, news={"2"}, revoked_news={A}), {"2": (0, None)})

    def test_other_customers_are_untouched(self):
        result = plan({"1": A, "2": B, "3": C}, news={"1", "2", "3"}, revoked_news={B})
        self.assertEqual(result, {"2": (0, None)})


class TestEmailOnlyRevocations(unittest.TestCase):
    def test_opted_out_or_blacklisted_active_rows(self):
        self.assertEqual(rules.plan_email_only_revocations({A, B, C}, {A}, {B}), {A, B})

    def test_inactive_rows_and_unknown_emails_are_ignored(self):
        self.assertEqual(rules.plan_email_only_revocations({C}, {A}, {B}), set())


class TestCap(unittest.TestCase):
    def test_count(self):
        self.assertEqual(rules.count_revocations({"1": (0, None), "2": (0, 0)}, {A}), 3)

    def test_cap(self):
        self.assertFalse(rules.exceeds_cap(25, 25))
        self.assertTrue(rules.exceeds_cap(26, 25))
        self.assertFalse(rules.exceeds_cap(1000, 0))
        self.assertFalse(rules.exceeds_cap(1000, None))
        self.assertFalse(rules.exceeds_cap(0, 25))


if __name__ == "__main__":
    unittest.main()
