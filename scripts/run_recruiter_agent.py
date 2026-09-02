"""
Standalone Runner for LinkedIn Recruiter & HR Email Module.

Usage:
    python scripts/run_recruiter_agent.py              # Live scan & outreach
    python scripts/run_recruiter_agent.py --dry-run    # Dry run test
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="LinkedIn Recruiter & HR Email Agent")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails")
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("  [LINKEDIN RECRUITER & HR EMAIL OUTREACH AGENT]")
    print("=" * 65)
    if args.dry_run:
        print("  [DRY RUN MODE] No emails will be sent")
    print("=" * 65 + "\n")

    from app.services.linkedin_feed_scanner import LinkedInFeedScanner

    scanner = LinkedInFeedScanner()
    result = await scanner.scan_posts_and_outreach(dry_run=args.dry_run)

    print("\n" + "=" * 65)
    print("  [RECRUITER HR RUN COMPLETE]")
    print("=" * 65)
    print(f"   LinkedIn Posts Scanned:        {result['posts_scanned']}")
    print(f"   Verified Recruiter Emails:     {result['recruiter_emails_found']}")
    print(f"   Outreach Emails Dispatched:    {result['emails_sent']}")
    print(f"   Direct Post Links Prepared:    {result['direct_links_prepared']}")
    print(f"   Dedicated Excel Report:        {result['report_path']}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
