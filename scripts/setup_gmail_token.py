"""
Gmail OAuth2 Token Generator.
Generates a fresh GMAIL_REFRESH_TOKEN for the AI Job Agent.

Usage:
    python scripts/setup_gmail_token.py
"""
import sys
from pathlib import Path
import urllib.parse
import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config.settings import GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET

SCOPE = "https://www.googleapis.com/auth/gmail.send"
REDIRECT_URI = "https://developers.google.com/oauthplayground"


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print("🔑 GMAIL OAUTH2 REFRESH TOKEN GENERATOR")
    print("=" * 65)

    if not GMAIL_CLIENT_ID or not GMAIL_CLIENT_SECRET:
        print("❌ Please set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env first.")
        return

    print("\nOption 1: Generate via Google OAuth Playground (Recommended - 2 mins)")
    print("-" * 65)
    print("1. Open: https://developers.google.com/oauthplayground")
    print("2. Click the ⚙️ (Settings gear icon) in the top right corner.")
    print("3. Check 'Use your own OAuth credentials'.")
    print(f"4. Enter Client ID: {GMAIL_CLIENT_ID}")
    print(f"5. Enter Client Secret: {GMAIL_CLIENT_SECRET}")
    print("6. In Step 1 (left side), scroll to 'Gmail API v1' and select:")
    print("   https://www.googleapis.com/auth/gmail.send")
    print("7. Click 'Authorize APIs' and log in with your Gmail account.")
    print("8. In Step 2, click 'Exchange authorization code for tokens'.")
    print("9. Copy the 'Refresh token' and paste it into your .env as:")
    print("   GMAIL_REFRESH_TOKEN=your_new_refresh_token_here")
    print("\n" + "=" * 65)
    print("💡 Tip to stop tokens from expiring after 7 days:")
    print("   In Google Cloud Console -> 'OAuth consent screen' ->")
    print("   Change 'Publishing status' from 'Testing' to 'In production'.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
