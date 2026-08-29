"""
WhatsApp Setup Helper Script.
Tests Meta WhatsApp Cloud API and CallMeBot Free WhatsApp API.

Usage:
    python scripts/setup_whatsapp.py
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config.settings import (
    WHATSAPP_TOKEN,
    WHATSAPP_PHONE_ID,
    WHATSAPP_TO_NUMBER,
    CALLMEBOT_APIKEY,
)
from app.services.whatsapp_service import WhatsAppService


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print("📱 WHATSAPP NOTIFICATION DIAGNOSTIC & SETUP")
    print("=" * 65)

    ws = WhatsAppService()

    print("\n1. Testing Current Configuration...")
    test_msg = "🤖 *AI Job Agent Test Notification*\nWhatsApp integration is active!"
    success = ws.send_message(test_msg)

    if success:
        print("✅ SUCCESS: Test WhatsApp message delivered!")
    else:
        print("\n❌ WhatsApp message delivery failed.")
        print("\n" + "-" * 65)
        print("💡 QUICK FIX 1: Instant Free WhatsApp API (CallMeBot - 30 Seconds)")
        print("-" * 65)
        print("1. Open WhatsApp on your phone and send this text:")
        print("   I allow callmebot to send me messages")
        print("   To phone number: +34 644 51 92 23")
        print("2. CallMeBot will reply instantly with your free API key.")
        print("3. Open your .env file and add:")
        print("   CALLMEBOT_APIKEY=your_apikey_here")
        print("   WHATSAPP_TO_NUMBER=916304883114")
        print("\n" + "-" * 65)
        print("💡 QUICK FIX 2: Meta WhatsApp Cloud API Fix")
        print("-" * 65)
        print("If using Meta Developer Portal (https://developers.facebook.com/apps):")
        print("1. In WhatsApp -> API Setup -> Add '916304883114' under 'To Phone Number'.")
        print("2. Send an initial WhatsApp message from your phone to the Meta Test Number.")
        print("3. Copy the updated Temporary Access Token into .env as WHATSAPP_TOKEN=...")
        print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
