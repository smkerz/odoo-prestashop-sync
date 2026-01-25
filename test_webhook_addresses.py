#!/usr/bin/env python3
"""
Test script for webhook address synchronization.

This script simulates PrestaShop address webhooks to test the automatic
address synchronization feature in Odoo.

Usage:
    python test_webhook_addresses.py [create|update|delete]
"""

import hmac
import hashlib
import json
import requests
import sys
from datetime import datetime

# Configuration - MODIFIER SELON VOTRE ENVIRONNEMENT
ODOO_URL = "http://localhost:8069"  # ou https://votre-odoo.com
WEBHOOK_SECRET = "votre-secret-webhook"  # Copier depuis Odoo backend
BACKEND_ID = 1  # ID du backend PrestaShop dans Odoo

# Test payload templates
TEST_PAYLOAD_CREATE = {
    "backend_id": str(BACKEND_ID),
    "customer_id": "123",  # ID du customer dans PrestaShop (doit exister dans Odoo)
    "address_id": "456",   # ID de l'adresse dans PrestaShop (doit exister)
    "action": "create",
    "updated_at": datetime.utcnow().isoformat() + "Z",
    "shop_id": "1",
    "shop_url": "http://votre-prestashop.com",
}

TEST_PAYLOAD_UPDATE = {
    "backend_id": str(BACKEND_ID),
    "customer_id": "123",
    "address_id": "456",
    "action": "update",
    "updated_at": datetime.utcnow().isoformat() + "Z",
    "shop_id": "1",
    "shop_url": "http://votre-prestashop.com",
}

TEST_PAYLOAD_DELETE = {
    "backend_id": str(BACKEND_ID),
    "customer_id": "123",
    "address_id": "456",
    "action": "delete",
    "updated_at": datetime.utcnow().isoformat() + "Z",
    "shop_id": "1",
    "shop_url": "http://votre-prestashop.com",
}


def test_webhook(action="create"):
    """Send test webhook to Odoo."""

    # Select payload based on action
    if action == "create":
        payload = TEST_PAYLOAD_CREATE
    elif action == "update":
        payload = TEST_PAYLOAD_UPDATE
    elif action == "delete":
        payload = TEST_PAYLOAD_DELETE
    else:
        print(f"❌ Invalid action: {action}")
        print("Valid actions: create, update, delete")
        return

    # Prepare webhook URL
    webhook_url = f"{ODOO_URL}/prestashop/webhook/addresses"

    # Serialize payload
    body = json.dumps(payload).encode("utf-8")

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
    print(f"Action: {action.upper()}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
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
            message = result.get("message", "")

            if status == "ok":
                print(f"✅ SUCCESS - Address {action}d")
                print()
                print("Next steps:")
                print(f"1. Go to Odoo Contacts and search for customer_id {payload['customer_id']}")
                print("2. Click on the customer to see addresses (child contacts)")
                print(f"3. Verify the address with ID {payload['address_id']} is present")
                if action == "delete":
                    print("   (should be deleted)")
                print("4. Check PrestaShop → Logs for 'sync_addresses' operation")

            elif status == "skipped":
                print(f"⚠️  SKIPPED - {message}")
                print()
                print("Possible reasons:")
                print(f"1. Customer ID {payload['customer_id']} not found in Odoo mappings")
                print(f"2. Address ID {payload['address_id']} not found in PrestaShop")
                print("3. Parent partner not found")
                print()
                print("Solutions:")
                print("1. First import customer via 'Import Customers' button")
                print("2. Use a real address ID from PrestaShop")
                print("3. Ensure customer exists in both systems")

            elif status == "error":
                print(f"❌ ERROR - {message}")
                print("Check Odoo logs for details")

            else:
                print(f"❓ UNKNOWN STATUS: {status} - {message}")

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
    print("PrestaShop Webhook Test - Address Synchronization")
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
        print("Also update TEST_PAYLOAD_* with:")
        print("  - customer_id: A real customer ID from PrestaShop (must exist in Odoo)")
        print("  - address_id: A real address ID from PrestaShop")
        print("  - shop_url: Your PrestaShop URL")
        print()
        return

    # Get action from command line or default to "create"
    action = sys.argv[1] if len(sys.argv) > 1 else "create"

    test_webhook(action)


if __name__ == "__main__":
    main()
