"""
CLI Script to run and test Agent 3 (Chrome Browser Auto-Apply Agent).

Usage:
    # 1. Test in Dry-Run mode (fills forms & takes preview screenshots, does not click final submit):
    python scripts/run_browser_agent.py --dry-run

    # 2. Test for custom keyword and location:
    python scripts/run_browser_agent.py --keywords "Java Backend Developer" --location "India" --dry-run

    # 3. Live Auto-Apply:
    python scripts/run_browser_agent.py --live --max-apps 5
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.browser_auto_apply_agent import BrowserAutoApplyAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="AI Job Agent — Agent 3 Chrome Auto-Apply CLI")
    parser.add_argument("--keywords", type=str, default="Java Backend Developer", help="Search keyword on LinkedIn")
    parser.add_argument("--location", type=str, default="India", help="Location filter")
    parser.add_argument("--min-score", type=int, default=70, help="Minimum AI match score required to apply")
    parser.add_argument("--max-apps", type=int, default=5, help="Maximum jobs to apply to in this run")
    parser.add_argument("--live", action="store_true", help="Execute live submission (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview & screenshot without submitting")
    args = parser.parse_args()

    is_dry_run = not args.live

    print("\n" + "=" * 65)
    print("  🚀 [AGENT 3] AUTONOMOUS CHROME BROWSER AUTO-APPLY TESTER")
    print("=" * 65)
    print(f"  Keyword:      {args.keywords}")
    print(f"  Location:     {args.location}")
    print(f"  Min Score:    {args.min_score}%")
    print(f"  Max Apps:     {args.max_apps}")
    print(f"  Mode:         {'[DRY RUN - SAFE PREVIEW]' if is_dry_run else '[LIVE SUBMISSIONS ENABLED]'}")
    print("=" * 65 + "\n")

    agent = BrowserAutoApplyAgent(
        min_score=args.min_score,
        max_applications=args.max_apps,
        dry_run=is_dry_run,
    )

    results = await agent.run_search_and_apply(
        keywords=args.keywords,
        location=args.location,
    )

    print("\n" + "=" * 65)
    print("  📋 EXECUTION SUMMARY:")
    print(f"   - Total Jobs Evaluated:      {results.get('jobs_scanned', 0)}")
    print(f"   - Qualified Matches (>=70%): {results.get('jobs_qualified', 0)}")
    print(f"   - Tailored Resumes Made:     {results.get('resumes_generated', 0)}")
    print(f"   - Applications Processed:    {results.get('applications_submitted', 0)}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
