# -*- coding: utf-8 -*-
"""Rules and wording of the emails the connector sends to its operator.

Pure functions on plain values (no ORM), so they can be tested without Odoo:
    python tests/test_notify_rules.py

The emails are written in French, for the people who run the shops. Summaries
can list the addresses behind each counter (option of the backend); alerts only
carry counters.
"""
from datetime import timedelta
from html import escape

LEVELS = [
    ("none", "No email"),
    ("alerts", "Alerts only"),
    ("daily", "Alerts + daily summary"),
    ("each", "Alerts + hourly summary when something changed"),
]

# Counters of _activity_since(), in display order, with their French label.
COUNTERS = [
    ("new_customers", "Nouveaux clients reliés"),
    ("newsletter_subscribed", "Inscriptions à la newsletter"),
    ("newsletter_opted_out", "Désinscriptions de la newsletter"),
    ("offers_subscribed", "Inscriptions aux offres partenaires"),
    ("offers_opted_out", "Désinscriptions des offres partenaires"),
    ("revoked_in_shop", "Consentements retirés dans la boutique par Odoo"),
    ("errors", "Erreurs dans le journal du connecteur"),
]

DAILY_PERIOD = timedelta(hours=23, minutes=30)

# Lines listed under a counter, at most (a robot cleanup can opt out hundreds of rows)
DETAILS_SHOWN = 50


def sends_alerts(level):
    return level != "none"


def digest_due(level, now, last_digest, has_activity):
    """Whether a summary must be sent now.

    daily: once the previous one is about a day old (or was never sent), even when
    nothing happened, so that a missing email means the connector is not running.
    each: whenever something changed since the previous summary.
    """
    if level == "daily":
        # Odoo reads an empty Datetime field as False, not None
        return not last_digest or now - last_digest >= DAILY_PERIOD
    if level == "each":
        return bool(has_activity)
    return False


def has_activity(stats):
    return any(stats.get(key) for key, _label in COUNTERS)


def unusual_volume(stats, threshold):
    """Largest number of opt-outs of one list when it exceeds the threshold, else 0."""
    if not threshold or threshold <= 0:
        return 0
    worst = max(stats.get("newsletter_opted_out", 0), stats.get("offers_opted_out", 0))
    return worst if worst > threshold else 0


def _when(value):
    return value.strftime("%d/%m/%Y %H:%M") + " UTC"


def _details(lines):
    shown = ", ".join(escape(line) for line in lines[:DETAILS_SHOWN])
    if len(lines) > DETAILS_SHOWN:
        shown += " … et %s autres" % (len(lines) - DETAILS_SHOWN)
    return "<tr><td colspan=\"2\" style=\"padding:0 0 8px 16px;color:#555;font-size:90%%\">%s</td></tr>" % shown


def render_digest(sections, now):
    """Return (subject, html) of a summary.

    sections: [{"name", "since", "stats", "details"}, ...]; details (optional) maps a
    counter to the lines listed under it: addresses, or error messages.
    """
    quiet = not any(has_activity(section["stats"]) for section in sections)
    subject = "[Connecteur PrestaShop] Résumé du %s%s" % (
        now.strftime("%d/%m/%Y"), " : aucun changement" if quiet else "")
    with_addresses = any(section.get("details", {}).get(key)
                         for section in sections for key, _label in COUNTERS if key != "errors")
    parts = ["<p>Résumé de l'activité du connecteur PrestaShop. %s</p>" % (
        "Ce message contient des adresses de clients : ne le transférez pas." if with_addresses
        else "Chiffres uniquement, sans donnée de client.")]
    for section in sections:
        parts.append("<h3>%s</h3>" % escape(section["name"]))
        parts.append("<p>Depuis le %s</p>" % _when(section["since"]))
        if not has_activity(section["stats"]):
            parts.append("<p>Aucun changement.</p>")
            continue
        details = section.get("details", {})
        rows = "".join(
            "<tr><td>%s</td><td style=\"text-align:right;padding-left:16px\"><strong>%s</strong></td></tr>%s"
            % (label, section["stats"].get(key, 0), _details(details[key]) if details.get(key) else "")
            for key, label in COUNTERS if section["stats"].get(key)
        )
        parts.append("<table>%s</table>" % rows)
    return subject, "".join(parts)


def render_volume_alert(name, count, threshold, list_label):
    """Return (subject, html) of the immediate alert on a wave of opt-outs."""
    subject = "[Connecteur PrestaShop] %s : %s désinscriptions en une heure" % (name, count)
    html = (
        "<p><strong>%s désinscriptions</strong> de la liste « %s » ont été enregistrées en une heure "
        "pour la boutique <strong>%s</strong> (seuil d'alerte : %s).</p>"
        "<p>Si vous venez de faire un nettoyage volontaire, vous pouvez ignorer ce message. "
        "Sinon, désactivez la tâche planifiée « Sync Consents (Odoo -> Presta) » le temps de comprendre, "
        "puis regardez le journal du connecteur.</p>"
    ) % (count, escape(list_label), escape(name), threshold)
    return subject, html
