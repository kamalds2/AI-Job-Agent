"""
Test Browser Auto-Apply Script.
Allows testing Playwright browser auto-application in visible (headed) mode on any URL.

Usage:
    python scripts/test_browser_apply.py <job_url>
"""
import sys
import asyncio
import logging
from pathlib import Path

# Configure Windows UTF-8 console output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.browser_apply_service import BrowserApplyService
from app.services.resume_service import ResumeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_browser_apply.py <job_url> [company_name] [job_title]")
        print("Example: python scripts/test_browser_apply.py https://boards.greenhouse.io/stripe/jobs/12345 Stripe 'Software Engineer'")
        return

    job_url = sys.argv[1]
    company_name = sys.argv[2] if len(sys.argv) > 2 else "Target Company"
    job_title = sys.argv[3] if len(sys.argv) > 3 else "Software Engineer"

    print(f"\n🚀 Testing Browser Auto-Apply for: '{job_title}' @ {company_name}")
    print(f"🔗 Target URL: {job_url}")

    # Generate a sample ATS resume if needed
    resume_service = ResumeService()
    pdf_path = resume_service.create_tailored_resume(
        job_id=9999,
        job_title=job_title,
        company=company_name,
        job_description=f"Hiring {job_title} at {company_name}. Requires Java, Python, Spring Boot, FastAPI, AWS.",
    )

    print(f"📄 Tailored ATS Resume generated: {pdf_path}")
    print("🌐 Launching visible Chromium browser window with saved profile...\n")

    # Launch browser with headless=False so user can see it live
    service = BrowserApplyService(headless=False)
    result = await service.apply(
        job_url=job_url,
        job_title=job_title,
        company_name=company_name,
        resume_pdf_path=pdf_path,
        cover_letter=f"Dear Hiring Team at {company_name},\n\nI am writing to express my strong interest in the {job_title} role. With hands-on experience in Java, Spring Boot, Python, and cloud microservices, I am excited about the opportunity to contribute.\n\nBest regards,\nKamal Kumar",
    )

    print("\n" + "=" * 60)
    print("📋 Application Result:")
    print(f"   Success: {result.get('success')}")
    print(f"   Method:  {result.get('method')}")
    print(f"   Message: {result.get('message')}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
