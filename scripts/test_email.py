"""Quick test to verify Gmail App Password sending."""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.email_service import EmailService
from app.config.settings import EMAIL_ADDRESS, GMAIL_APP_PASSWORD

def main():
    print("\n" + "=" * 50)
    print("  GMAIL APP PASSWORD TEST")
    print("=" * 50)
    print(f"From: {EMAIL_ADDRESS}")
    print(f"App Password set: {'Yes (' + str(len(GMAIL_APP_PASSWORD)) + ' chars)' if GMAIL_APP_PASSWORD else 'NO (Empty in .env)'}")

    if not GMAIL_APP_PASSWORD:
        print("\n[!] GMAIL_APP_PASSWORD is empty in .env. Please add your 16-character App Password.")
        return

    service = EmailService()
    success = service.send_email(
        to_email=EMAIL_ADDRESS,
        subject="AI Job Agent - Gmail App Password Test Successful!",
        body="Hello Kamal,\n\nYour Gmail App Password is functioning properly! The AI Job Agent can now send applications, recruiter emails, and daily reports permanently without any token expiration.\n\nBest regards,\nAI Job Agent",
    )

    if success:
        print("\n[OK] SUCCESS! Test email was delivered directly to your inbox.")
    else:
        print("\n[ERROR] Failed to send email. Check password correctness and 2-step verification.")

if __name__ == "__main__":
    main()
