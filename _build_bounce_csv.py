"""Convert hard_bounces.txt to a CSV ready for Odoo mail.blacklist import."""
import csv
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(ROOT, "hard_bounces.txt")
dst = os.path.join(ROOT, "blacklist_import.csv")

with open(src, encoding="utf-8") as f:
    emails = sorted({line.strip().lower() for line in f if line.strip()})

with open(dst, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["email"])
    for e in emails:
        w.writerow([e])

print(f"Wrote {dst} ({len(emails)} emails)")
