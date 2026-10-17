"""
KKNN Autonomous AI Job Agent — Phase 4 Global Career Sites Runner.

Sweeps through Startup & MNC company career sites from Excel/CSV (Careers Excel/ folder)
across Germany, Europe, UAE, Australia, Philippines, New Zealand, Saudi Arabia, etc.

Features:
  - Excel/CSV ingestion with flexible header detection.
  - Reuses single Google Chrome instance on port 9222 (TabGuard Rule 1 & Rule 2).
  - Searches 0-2 yrs software engineering / Java / AI / Backend roles.
  - Filters for latest / 24h posts.
  - Scores role with Gemini AI against candidate profile (Doddi Kamal Kumar).
  - Dynamically tailors 1-page ATS PDF resume in resumes/global_careers/.
  - Auto-fills application form fields.
  - Detects CAPTCHA / Human challenges, emails candidate alert, and pauses until solved.
  - Submits application & tracks progress in JobTracker & SQLite DB.

Usage:
    python scripts/run_global_career_sites.py
    python scripts/run_global_career_sites.py --dry-run
    python scripts/run_global_career_sites.py --target 15
    python scripts/run_global_career_sites.py --country germany
    python scripts/run_global_career_sites.py --country uae
    python scripts/run_global_career_sites.py --excel-path "Careers Excel/my_sites.xlsx"
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup logging
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
AGENT_LOG_FILE = LOGS_DIR / "agent.log"

file_handler = logging.FileHandler(str(AGENT_LOG_FILE), encoding="utf-8", mode="a")
stream_handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%H:%M:%S")
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(stream_handler)

from app.config.settings import CANDIDATE_EXPERIENCE_YEARS, CANDIDATE_NAME
from app.services.global_career_sites_agent import run_global_career_sites_apply


async def main():
    parser = argparse.ArgumentParser(description="Global Career Sites Autonomous Auto-Apply Runner (Phase 4)")
    parser.add_argument(
        "--excel-path",
        type=str,
        default=None,
        help="Path to company career sites Excel/CSV spreadsheet (default: scans 'Careers Excel/' folder)",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=10,
        help="Target number of applications to submit (default: 10)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default=None,
        help="Filter companies by country/region (e.g. 'germany', 'uae', 'australia', 'europe', 'saudi')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview forms & test modal without final submit",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  🌐 [KKNN AUTONOMOUS JOB ASSISTANT — PHASE 4 GLOBAL CAREER SITES]")
    print(f"  🎯 [CANDIDATE: {CANDIDATE_NAME.upper()} — SOFTWARE / JAVA & AI DEVELOPER ({CANDIDATE_EXPERIENCE_YEARS.upper()})]")
    print("=" * 70)
    print(f"  📁 Target Spreadsheet:  {args.excel_path or 'Auto-scan Careers Excel/'}")
    print(f"  🌍 Country Filter:      {args.country.upper() if args.country else 'ALL REGIONS (Germany, EU, UAE, AU, NZ, etc.)'}")
    print(f"  🎯 Target Applications: {args.target}")
    print(f"  🧪 Execution Mode:      {'DRY RUN (Forms filled up to review)' if args.dry_run else '🚀 LIVE SUBMISSIONS'}")
    print("=" * 70 + "\n")

    start_time = datetime.now()
    stats = await run_global_career_sites_apply(
        excel_path=args.excel_path,
        target_applied=args.target,
        country=args.country,
        dry_run=args.dry_run,
    )

    duration = datetime.now() - start_time
    print("\n" + "=" * 70)
    print("  🎉 [PHASE 4 EXECUTION COMPLETE]")
    print("=" * 70)
    print(f"  • Companies Evaluated:   {stats.get('processed_companies', 0)}")
    print(f"  • Applications Submitted: {stats.get('total_applied', 0)}")
    print(f"  • Execution Time:        {duration.total_seconds():.1f}s")
    print(f"  • Log File:              {AGENT_LOG_FILE}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
