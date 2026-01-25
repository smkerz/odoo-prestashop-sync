#!/usr/bin/env python3
"""
Test script for webhook automatic customer creation.

This script simulates a PrestaShop webhook to test the automatic customer
creation feature in Odoo.

Usage:
    python test_webhook_create_customer.py
"""

import hmac
import hashlib
import json
import requests
from datetime import datetime

# Configuration - MODIFIER SELON VOTRE ENVIRONNEMENT
ODOO_URL = "http://localhost:8069"  # ou https://votre-odoo.com
WEBHOOK_SECRET = "votre-secret-webhook"  # Copier depuis Odoo backend
BACKEND_ID = 1  # ID du backend PrestaShop dans Odoo

# Test payload (nouveau client fictif)
TEST_PAYLOAD = {
    "backend_id": str(BACKEND_ID),
    "customer_id": "9999",  # ID fictif - doit exister dans PrestaShop pour le test réel
    "email": "test-auto-create@example.com",
    "newsletter": 1,
    "optin": 0,
    "updated_at": datetime.utcnow().isoformat() + "Z",
    "shop_id": "1",
    "shop_url": "http://votre-prestashop.com",
}


def test_webhook():
    """Send test webhook to Odoo."""

    # Prepare webhook URL
    webhook_url = f"{ODOO_URL}/prestashop/webhook/consents"

    # Serialize payload
    body = json.dumps(TEST_PAYLOAD).encode("utf-8")

    # Calculate HMAC signature
    signature = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    # Send webhook
    headers = {
        "Content-Type": "application/json",
        "X-Prestashop-Signature": signature,
    }

    print(f"Sending webhook to: {webhook_url}")
    print(f"Payload: {json.dumps(TEST_PAYLOAD, indent=2)}")
    print(f"Signature: {signature}")
    print()

    try:
        response = requests.post(
            webhook_url,
            data=body,
            headers=headers,
            timeout=30,
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        print()

        if response.status_code == 200:
            result = response.json()
            status = result.get("status", "unknown")

            if status == "ok":
                print("✅ SUCCESS - Customer created/updated")
                print()
                print("Next steps:")
                print(f"1. Go to Odoo Contacts and search for: {TEST_PAYLOAD['email']}")
                print("2. Verify the contact has tag 'Client Prestashop'")
                print("3. Check Email Marketing lists (Newsletter should be subscribed)")
                print("4. Check PrestaShop → Logs for 'webhook_create_customer' operation")

            elif status == "skipped":
                print("⚠️  SKIPPED - Partner not found and could not be created")
                print()
                print("Possible reasons:")
                print(f"1. PrestaShop customer ID {TEST_PAYLOAD['customer_id']} does not exist")
                print("2. PrestaShop API is not accessible")
                print("3. Customer is a guest and include_guest_customers=False")
                print()
                print("Solutions:")
                print("1. Use a real customer ID from PrestaShop")
                print("2. First create the customer in PrestaShop, then run this test")

            elif status == "blocked":
                print("🚫 BLOCKED - Email is blacklisted or opted-out in Odoo")
                print()
                print("The email is in Odoo's blacklist or has global opt-out.")
                print("This is expected behavior to respect GDPR preferences.")

            else:
                print(f"❓ UNKNOWN STATUS: {status}")

        else:
            print(f"❌ ERROR - HTTP {response.status_code}")
            print("Check Odoo logs for details")

    except requests.exceptions.ConnectionError:
        print("❌ CONNECTION ERROR")
        print(f"Could not connect to {webhook_url}")
        print("Make sure Odoo is running and accessible")

    except Exception as e:
        print(f"❌ ERROR: {e}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("PrestaShop Webhook Test - Automatic Customer Creation")
    print("=" * 60)
    print()

    # Check configuration
    if WEBHOOK_SECRET == "votre-secret-webhook":
        print("⚠️  WARNING: You need to configure the script first!")
        print()
        print("Edit this file and set:")
        print("  - ODOO_URL: Your Odoo instance URL")
        print("  - WEBHOOK_SECRET: From PrestaShop backend in Odoo")
        print("  - BACKEND_ID: Your PrestaShop backend ID in Odoo")
        print()
        print("Also update TEST_PAYLOAD with:")
        print("  - customer_id: A real customer ID from PrestaShop")
        print("  - shop_url: Your PrestaShop URL")
        print()
        return

    test_webhook()


if __name__ == "__main__":
    main()
