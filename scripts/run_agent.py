"""
CLI script to run the AI Job Agent manually.

Usage:
    python scripts/run_agent.py              # Full run
    python scripts/run_agent.py --dry-run    # Dry run (no live submissions or emails sent)
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
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no live submissions or emails sent)")
    parser.add_argument("--submit", action="store_true", help="Run live submissions across all browser agents")
    parser.add_argument("--search-only", action="store_true", help="Only run job search, skip AI scoring and applications")
    parser.add_argument("--target-apps", type=int, default=20, help="Target applications per browser portal (default: 20)")
    parser.add_argument("--keyword", type=str, default="Java Backend Developer", help="Primary search keyword")
    parser.add_argument("--location", type=str, default="India", help="Location filter")
    args = parser.parse_args()

    is_dry_run = not args.submit if args.submit else args.dry_run

    print("\n" + "=" * 70)
    print("  🤖 [AI JOB AGENT] MASTER MULTI-AGENT WORKFLOW RUNNER")
    print("=" * 70)
    print(f"  Target Role:      {args.keyword}")
    print(f"  Location:         {args.location}")
    print(f"  Target/Portal:    {args.target_apps} applications")
    print(f"  Mode:             {'🧪 DRY RUN (Safe Mode)' if is_dry_run else '🚀 LIVE SUBMISSIONS ENABLED'}")
    print("=" * 70 + "\n")

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
        # Full Multi-Agent Pipeline: Phase 1 -> Phase 2 -> Phase 3
        from app.agents.orchestrator import run_full_multi_agent_pipeline

        summary = await run_full_multi_agent_pipeline(
            dry_run=is_dry_run,
            target_applied_per_portal=args.target_apps,
            keyword=args.keyword,
            location=args.location,
        )

        print("\n" + "=" * 70)
        print("  📊 MASTER MULTI-AGENT EXECUTION SUMMARY")
        print("=" * 70)
        p1 = summary.get("phase1_aggregator", {})
        print(f"  📦 Phase 1 (Job Boards & ATS):")
        print(f"     - Jobs Fetched:  {p1.get('jobs_fetched', 0)}")
        print(f"     - Scored:        {p1.get('scored', 0)}")
        print(f"     - Qualified:     {p1.get('qualified', 0)}")
        print(f"     - Report:        {p1.get('report_path', 'N/A')}")

        p2 = summary.get("phase2_recruiter_outreach", {})
        print(f"  📬 Phase 2 (LinkedIn Recruiter Feed & Outreach):")
        print(f"     - Posts Scanned: {p2.get('posts_scanned', 0)}")
        print(f"     - HR Emails:     {p2.get('recruiter_emails_found', 0)}")
        print(f"     - Cold Emails:   {p2.get('emails_sent', 0)}")
        print(f"     - Report:        {p2.get('report_path', 'N/A')}")

        p3 = summary.get("phase3_browser_agents", {})
        print(f"  🌐 Phase 3 (Browser Auto-Apply Agents):")
        for portal, p_data in p3.items():
            print(f"     - {portal:15}: {p_data.get('applications', 0)}/{args.target_apps} applications ({p_data.get('status', 'N/A')})")

        print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
