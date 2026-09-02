"""
CLI script to run the AI Job Agent manually.

Usage:
    python scripts/run_agent.py              # Full run
    python scripts/run_agent.py --dry-run    # Dry run (no emails/WhatsApp sent)
    python scripts/run_agent.py --search-only # Only search, no AI scoring
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
    parser = argparse.ArgumentParser(description="AI Job Agent CLI")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails/WhatsApp")
    parser.add_argument("--search-only", action="store_true", help="Only run job search, skip AI scoring")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  [AI JOB AGENT]")
    print("=" * 60)

    if args.dry_run:
        print("  [DRY RUN] No emails or WhatsApp will be sent")
    if args.search_only:
        print("  [SEARCH ONLY] No AI scoring")
    print("=" * 60 + "\n")

    if args.search_only:
        # Only run the search node
        from app.database.database import SessionLocal
        from app.connectors.manager import SearchManager

        db = SessionLocal()
        try:
            manager = SearchManager(db)
            result = await manager.run_all()
            print(f"\nSearch complete:")
            print(f"   Total fetched:     {result['total_raw']}")
            print(f"   New jobs saved:    {result['saved']}")
            print(f"   Duplicates:        {result['duplicates_skipped']}")
            print(f"\n   By connector:")
            for connector, count in result.get("connector_stats", {}).items():
                print(f"     {connector:25} {count} jobs")
        finally:
            db.close()
    else:
        # Full agent run — Pipeline 1 (Job Boards) + Pipeline 2 (LinkedIn Feed)
        from app.agents.orchestrator import run_agent
        from app.services.linkedin_feed_scanner import LinkedInFeedScanner

        print("🚀 [1/2] Executing Job Boards & ATS Aggregator Pipeline...")
        result = await run_agent(dry_run=args.dry_run)

        print(f"\n✅ Job Boards & ATS Pipeline complete:")
        print(f"   Jobs fetched:   {result.get('raw_jobs_count', 0)}")
        print(f"   New jobs:       {result.get('new_jobs_count', 0)}")
        print(f"   Scored:         {len(result.get('scored_jobs', []))}")
        print(f"   Qualified:      {len(result.get('qualified_job_ids', []))}")
        print(f"   Resumes made:   {len(result.get('resume_paths', {}))}")
        print(f"   Job Report:     {result.get('report_path', 'N/A')}")

        print("\n🔍 [2/2] Executing LinkedIn Recruiter Feed & Outreach Pipeline...")
        scanner = LinkedInFeedScanner()
        recruiter_result = await scanner.scan_posts_and_outreach(dry_run=args.dry_run)

        print(f"\n✅ LinkedIn Recruiter Outreach complete:")
        print(f"   LinkedIn Posts Scanned:        {recruiter_result.get('posts_scanned', 0)}")
        print(f"   Verified Recruiter Emails:     {recruiter_result.get('recruiter_emails_found', 0)}")
        print(f"   Cold Emails Sent to HR:        {recruiter_result.get('emails_sent', 0)}")
        print(f"   Direct Post Links Prepared:    {recruiter_result.get('direct_links_prepared', 0)}")
        print(f"   Recruiter HR Report:           {recruiter_result.get('report_path', 'N/A')}")

        if errors := result.get("errors"):
            print(f"\n[ERRORS] ({len(errors)}):")
            for err in errors:
                print(f"   - {err}")

        print("\n" + "=" * 60)
        print("  🎉 COMPLETE FULL RUN FINISHED SUCCESSFULLY!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
