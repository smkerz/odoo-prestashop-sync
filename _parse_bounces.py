"""Parse a folder of bounce notification .eml files and classify each bounce.

Outputs:
- bounces.csv (full report)
- hard_bounces.txt (one email per line — invalid addresses, safe to blacklist)
"""
import csv
import email
import os
import re
import sys
from collections import Counter, defaultdict
from email import policy


def find_value(headers_text, key):
    pattern = re.compile(r"^" + re.escape(key) + r"\s*:\s*(.+?)$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(headers_text)
    return m.group(1).strip() if m else None


def parse_eml(path):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    failed_email = None
    status = None
    diagnostic = None
    action = None

    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("message/delivery-status", "text/rfc822-headers"):
            try:
                payload = part.get_payload(decode=False)
                if isinstance(payload, list):
                    for sub in payload:
                        text = sub.as_string() if hasattr(sub, "as_string") else str(sub)
                        _maybe_set = lambda var, key, t=text: find_value(t, key)
                        if not failed_email:
                            fr = _maybe_set(None, "Final-Recipient")
                            if fr:
                                m = re.search(r"rfc822\s*;\s*(\S+)", fr, re.IGNORECASE)
                                failed_email = m.group(1) if m else fr.strip()
                        status = status or _maybe_set(None, "Status")
                        diagnostic = diagnostic or _maybe_set(None, "Diagnostic-Code")
                        action = action or _maybe_set(None, "Action")
                else:
                    text = str(payload)
                    if not failed_email:
                        fr = find_value(text, "Final-Recipient")
                        if fr:
                            m = re.search(r"rfc822\s*;\s*(\S+)", fr, re.IGNORECASE)
                            failed_email = m.group(1) if m else fr.strip()
                    status = status or find_value(text, "Status")
                    diagnostic = diagnostic or find_value(text, "Diagnostic-Code")
                    action = action or find_value(text, "Action")
            except Exception:
                pass

    # Fallback : full body scan for hosts that don't return RFC delivery-status
    if not failed_email:
        try:
            body = msg.as_string()
        except Exception:
            body = ""
        m = re.search(r"Final-Recipient\s*:\s*rfc822\s*;\s*(\S+)", body, re.IGNORECASE)
        if m:
            failed_email = m.group(1)
        if not status:
            ms = re.search(r"Status\s*:\s*([0-9]\.[0-9]\.[0-9])", body)
            status = ms.group(1) if ms else None
        if not diagnostic:
            md = re.search(r"Diagnostic-Code\s*:\s*(.+?)(?:\r?\n[A-Z][^:]*:|\Z)", body, re.IGNORECASE | re.DOTALL)
            diagnostic = md.group(1).strip().replace("\r", " ").replace("\n", " ") if md else None

    return {
        "file": os.path.basename(path),
        "email": (failed_email or "").strip().lower(),
        "status": status or "",
        "action": action or "",
        "diagnostic": (diagnostic or "").strip()[:500],
    }


def classify(status):
    if not status:
        return "unknown"
    if status.startswith("5."):
        return "hard"
    if status.startswith("4."):
        return "soft"
    return "other"


def main(folder, out_csv, out_hard):
    files = []
    for root, _, names in os.walk(folder):
        for n in names:
            if n.lower().endswith(".eml"):
                files.append(os.path.join(root, n))
    print(f"Found {len(files)} .eml files")

    rows = []
    for path in files:
        try:
            r = parse_eml(path)
            r["bounce_type"] = classify(r["status"])
            rows.append(r)
        except Exception as e:
            rows.append({"file": os.path.basename(path), "email": "",
                         "status": "", "action": "", "diagnostic": f"PARSE_ERROR: {e}",
                         "bounce_type": "error"})

    by_type = Counter(r["bounce_type"] for r in rows)
    print(f"\nBy type: {dict(by_type)}")

    by_status = Counter(r["status"] for r in rows if r["status"])
    print(f"\nTop status codes:")
    for s, n in by_status.most_common(10):
        print(f"  {s}: {n}")

    emails_per_type = defaultdict(set)
    for r in rows:
        if r["email"]:
            emails_per_type[r["bounce_type"]].add(r["email"])

    print(f"\nUnique emails: total={sum(len(v) for v in emails_per_type.values())} "
          f"hard={len(emails_per_type['hard'])} soft={len(emails_per_type['soft'])} "
          f"unknown={len(emails_per_type['unknown'])} other={len(emails_per_type['other'])}")

    # Top hard-bounce diagnostics
    hard_diags = Counter()
    for r in rows:
        if r["bounce_type"] == "hard":
            short = (r["diagnostic"] or "")[:80]
            hard_diags[short] += 1
    print(f"\nTop hard-bounce reasons:")
    for d, n in hard_diags.most_common(10):
        print(f"  {n}x  {d}")

    # CSV
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "email", "bounce_type", "status",
                                          "action", "diagnostic"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {out_csv}")

    # Hard bounces: one email per line, unique
    with open(out_hard, "w", encoding="utf-8") as f:
        for em in sorted(emails_per_type["hard"]):
            f.write(em + "\n")
    print(f"Wrote {out_hard} ({len(emails_per_type['hard'])} unique hard-bounce emails)")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    out_csv = sys.argv[2] if len(sys.argv) > 2 else "bounces.csv"
    out_hard = sys.argv[3] if len(sys.argv) > 3 else "hard_bounces.txt"
    main(folder, out_csv, out_hard)
