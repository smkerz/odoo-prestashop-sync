"""Standalone tests for the notification rules (no Odoo needed).

Run from the module folder:
    python tests/test_notify_rules.py
"""
import importlib.util
import os
import unittest
from datetime import datetime, timedelta

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "notify_rules.py")
spec = importlib.util.spec_from_file_location("notify_rules_under_test", RULES_PATH)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

NOW = datetime(2026, 10, 6, 8, 0)
QUIET = {key: 0 for key, _label in rules.COUNTERS}
BUSY = dict(QUIET, new_customers=3, newsletter_opted_out=2)


class TestDigestDue(unittest.TestCase):
    def test_daily_is_sent_once_a_day_even_without_activity(self):
        self.assertTrue(rules.digest_due("daily", NOW, None, False))
        self.assertTrue(rules.digest_due("daily", NOW, NOW - timedelta(hours=24), False))
        self.assertFalse(rules.digest_due("daily", NOW, NOW - timedelta(hours=5), True))

    def test_each_is_sent_only_when_something_changed(self):
        self.assertTrue(rules.digest_due("each", NOW, NOW - timedelta(hours=1), True))
        self.assertFalse(rules.digest_due("each", NOW, NOW - timedelta(days=3), False))

    def test_other_levels_never_send_a_summary(self):
        for level in ("none", "alerts"):
            self.assertFalse(rules.digest_due(level, NOW, None, True))

    def test_only_none_silences_alerts(self):
        self.assertFalse(rules.sends_alerts("none"))
        for level in ("alerts", "daily", "each"):
            self.assertTrue(rules.sends_alerts(level))

    def test_levels_match_the_rules(self):
        self.assertEqual([key for key, _label in rules.LEVELS], ["none", "alerts", "daily", "each"])


class TestVolume(unittest.TestCase):
    def test_above_threshold(self):
        self.assertEqual(rules.unusual_volume(dict(QUIET, newsletter_opted_out=11), 10), 11)
        self.assertEqual(rules.unusual_volume(dict(QUIET, offers_opted_out=40, newsletter_opted_out=12), 10), 40)

    def test_at_or_below_threshold(self):
        self.assertEqual(rules.unusual_volume(dict(QUIET, newsletter_opted_out=10), 10), 0)
        self.assertEqual(rules.unusual_volume(QUIET, 10), 0)

    def test_threshold_zero_disables_the_alert(self):
        self.assertEqual(rules.unusual_volume(dict(QUIET, newsletter_opted_out=500), 0), 0)


class TestRendering(unittest.TestCase):
    def test_digest_lists_only_what_changed(self):
        subject, html = rules.render_digest(
            [{"name": "shop <A>", "since": NOW - timedelta(days=1), "stats": BUSY},
             {"name": "shop B", "since": NOW - timedelta(days=1), "stats": QUIET}], NOW)
        self.assertEqual(subject, "[Connecteur PrestaShop] Résumé du 06/10/2026")
        self.assertIn("shop &lt;A&gt;", html)
        self.assertIn("Nouveaux clients reliés", html)
        self.assertIn("Désinscriptions de la newsletter", html)
        self.assertNotIn("Inscriptions aux offres partenaires", html)
        self.assertIn("Aucun changement.", html)

    def test_quiet_digest_says_so_in_the_subject(self):
        subject, _html = rules.render_digest([{"name": "shop", "since": NOW, "stats": QUIET}], NOW)
        self.assertTrue(subject.endswith("aucun changement"))

    def test_volume_alert(self):
        subject, html = rules.render_volume_alert("shop", 161, 10, "Newsletter")
        self.assertIn("161 désinscriptions en une heure", subject)
        self.assertIn("seuil d'alerte : 10", html)


if __name__ == "__main__":
    unittest.main()
