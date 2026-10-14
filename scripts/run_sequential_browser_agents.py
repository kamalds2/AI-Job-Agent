"""
KKNN Autonomous Multi-Agent Sequential Browser Auto-Apply Runner.

Runs sequential browser-based auto-apply agents across selected portals:
LinkedIn, Y Combinator, Hirist, Cutshort, and Indeed.
Logs all output to stdout and logs/agent.log.
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

# Setup logging to both console and logs/agent.log
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

logger = logging.getLogger("SequentialRunner")

from app.services.cutshort_browser_agent import run_cutshort_auto_apply
from app.services.hirist_browser_agent import run_hirist_auto_apply
from app.services.linkedin_browser_agent import run_linkedin_auto_apply
from app.services.wellfound_browser_agent import run_wellfound_auto_apply
from app.services.ycombinator_browser_agent import run_ycombinator_auto_apply


async def main():
    parser = argparse.ArgumentParser(description="Sequential Multi-Portal Browser Auto-Apply Runner")
    parser.add_argument(
        "--target",
        type=int,
        default=5,
        help="Target number of applications per portal (default: 5)",
    )
    parser.add_argument(
        "--portals",
        nargs="+",
        default=["linkedin", "ycombinator", "hirist", "cutshort"],
        help="List of portals to run sequentially (e.g. linkedin ycombinator hirist cutshort indeed)",
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default="Java Backend Developer",
        help="Primary job search keyword (default: 'Java Backend Developer')",
    )
    parser.add_argument(
        "--location",
        type=str,
        default="India",
        help="Location filter (default: 'India')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview forms & test modal without final submit",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=25,
        help="Maximum jobs to inspect per portal (default: 25)",
    )
    parser.add_argument(
        "--include-indeed",
        action="store_true",
        default=False,
        help="Unpause and include Indeed browser agent",
    )
    args = parser.parse_args()

    # Normalize portals list
    selected_portals = [p.lower().strip() for p in args.portals]
    if "indeed" in selected_portals and not args.include_indeed:
        logger.info("⏸️ [PAUSED]: Indeed is paused by user preference until further notice. Skipping Indeed.")
        selected_portals = [p for p in selected_portals if p != "indeed"]

    logger.info("=" * 68)
    logger.info("  🚀 KKNN AUTONOMOUS MULTI-AGENT SEQUENTIAL RUNNER")
    logger.info("=" * 68)
    logger.info(f"  Working Directory: {BASE_DIR}")
    logger.info(f"  Target Portals:    {', '.join(selected_portals)}")
    logger.info(f"  Target Apps/Portal:{args.target}")
    logger.info(f"  Primary Keyword:   {args.keyword}")
    logger.info(f"  Location:          {args.location}")
    logger.info(f"  Mode:              {'🧪 DRY RUN (Safe Testing)' if args.dry_run else '🚀 LIVE SUBMISSIONS'}")
    logger.info(f"  Persistent Log:    {AGENT_LOG_FILE}")
    logger.info("=" * 68)

    session_summary = {}

    for portal in selected_portals:
        logger.info(f"\n{'#'*65}\n  ▶ STARTING BROWSER AGENT: {portal.upper()}\n{'#'*65}")
        start_time = datetime.now()
        portal_applied = 0

        try:
            if portal in ("linkedin", "li"):
                res = await run_linkedin_auto_apply(
                    keyword=args.keyword,
                    location=args.location,
                    target_applied=args.target,
                    max_jobs=args.max_jobs,
                    dry_run=args.dry_run,
                )
                portal_applied = len(res) if res else 0

            elif portal in ("ycombinator", "yc"):
                res = await run_ycombinator_auto_apply(
                    keyword=args.keyword,
                    location=args.location,
                    target_applied=args.target,
                    max_jobs=args.max_jobs,
                    dry_run=args.dry_run,
                )
                portal_applied = len(res) if res else 0

            elif portal == "hirist":
                res = await run_hirist_auto_apply(
                    target_applied=args.target,
                    max_jobs=args.max_jobs,
                    dry_run=args.dry_run,
                )
                portal_applied = len(res) if res else 0

            elif portal == "cutshort":
                res = await run_cutshort_auto_apply(
                    target_applied=args.target,
                    max_jobs=args.max_jobs,
                    dry_run=args.dry_run,
                )
                portal_applied = len(res) if res else 0

            elif portal == "wellfound":
                res = await run_wellfound_auto_apply(
                    keyword=args.keyword,
                    location=args.location,
                    target_applied=args.target,
                    max_jobs=args.max_jobs,
                    dry_run=args.dry_run,
                )
                portal_applied = len(res) if res else 0

            elif portal == "indeed":
                from app.services.indeed_browser_agent import run_indeed_auto_apply
                res = await run_indeed_auto_apply(
                    keyword=args.keyword,
                    location=args.location,
                    target_applied=args.target,
                    max_jobs=args.max_jobs,
                    dry_run=args.dry_run,
                )
                portal_applied = len(res) if res else 0

            else:
                logger.warning(f"Unknown portal specified: {portal}. Skipping.")
                continue

            duration = (datetime.now() - start_time).total_seconds()
            session_summary[portal] = {"status": "SUCCESS", "applied": portal_applied, "duration_sec": round(duration, 1)}
            logger.info(f"✅ Finished {portal.upper()}: {portal_applied} applications in {round(duration, 1)}s")

        except Exception as err:
            logger.exception(f"❌ Error executing browser agent for {portal.upper()}: {err}")
            session_summary[portal] = {"status": "ERROR", "applied": 0, "error": str(err)}
        finally:
            # Cooldown delay to allow browser session to cleanly release before next portal connects
            await asyncio.sleep(2.0)

    logger.info("\n" + "=" * 68)
    logger.info("  🏁 ALL SEQUENTIAL BROWSER AGENT RUNS COMPLETED")
    logger.info("=" * 68)
    for p, stats in session_summary.items():
        logger.info(f"  • {p.upper():<15}: {stats.get('status')} | Applied: {stats.get('applied', 0)}")
    logger.info("=" * 68 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
