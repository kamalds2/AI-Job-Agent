"""
CLI test script for Agent 3 — LinkedIn Chrome Auto-Apply Agent.

Usage:
    # 1. Dry run (default safe mode - inspects, scores, generates resume, tests modal, skips final submit):
    python scripts/test_browser_agent.py

    # 2. Custom search query:
    python scripts/test_browser_agent.py --keyword "Java Spring Boot Developer" --location "India"

    # 3. Live Apply mode (submits actual applications):
    python scripts/test_browser_agent.py --submit --max-jobs 5
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.services.cutshort_browser_agent import CutshortBrowserAgent, run_cutshort_auto_apply
from app.services.hirist_browser_agent import HiristBrowserAgent, run_hirist_auto_apply
from app.services.linkedin_browser_agent import LinkedInBrowserAgent, run_linkedin_auto_apply
from app.services.wellfound_browser_agent import WellfoundBrowserAgent, run_wellfound_auto_apply
from app.services.ycombinator_browser_agent import YCombinatorBrowserAgent, run_ycombinator_auto_apply

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Multi-Board Browser Auto-Apply Agent CLI (Agent 3)")
    parser.add_argument(
        "--portal",
        type=str,
        default="hirist",
        choices=["hirist", "cutshort", "linkedin", "ycombinator", "yc", "wellfound", "feed", "all"],
        help="Target portal: 'hirist', 'cutshort', 'linkedin', 'ycombinator'/'yc', 'wellfound', 'feed' (LinkedIn feed scanner), or 'all'",
    )

    parser.add_argument(
        "--keyword",
        type=str,
        default="Java Backend Developer",
        help="Job search keyword (default: 'Java Backend Developer')",
    )
    parser.add_argument(
        "--location",
        type=str,
        default="India",
        help="Job location filter (default: 'India')",
    )
    parser.add_argument(
        "--target-applied",
        type=int,
        default=5,
        help="Target number of applications to submit per role (default: 5)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=25,
        help="Maximum jobs to inspect per page (default: 25)",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit actual applications (by default runs in safe dry-run mode)",
    )
    args = parser.parse_args()

    dry_run = not args.submit

    print("\n" + "=" * 65)
    print("  🌐 [AGENT 3] BROWSER AUTO-APPLY AGENT")
    print("=" * 65)
    print(f"  Target Profile:   Kamal Kumar (kamalkumar.doddi@gmail.com)")
    print(f"  Portal:           {args.portal.upper()}")
    print(f"  Primary Keyword:  {args.keyword}")
    print(f"  Multi-Role Sweep: Auto-progresses through all matching roles")
    print(f"  Location:         {args.location}")
    print(f"  Target Applied:   {args.target_applied} jobs")
    print(f"  Max Inspect/Page: {args.max_jobs} jobs")
    print(f"  Resumes Dir:      resumes/{args.portal}/")
    print(f"  Mode:             {'🧪 DRY RUN (Safe Testing)' if dry_run else '🚀 LIVE SUBMISSION'}")
    print("=" * 65 + "\n")

    results = []

    if args.portal == "hirist":
        results = await run_hirist_auto_apply(
            target_applied=args.target_applied,
            max_jobs=args.max_jobs,
            dry_run=dry_run,
        )

    elif args.portal == "cutshort":
        results = await run_cutshort_auto_apply(
            target_applied=args.target_applied,
            max_jobs=args.max_jobs,
            dry_run=dry_run,
        )


    elif args.portal == "linkedin":
        results = await run_linkedin_auto_apply(
            keyword=args.keyword,
            location=args.location,
            target_applied=args.target_applied,
            max_jobs=args.max_jobs,
            dry_run=dry_run,
        )

    elif args.portal == "feed":
        # LinkedIn Feed Scanner — search hiring posts, email recruiters
        from app.services.linkedin_feed_scanner import LinkedInFeedScanner
        scanner = LinkedInFeedScanner()
        result = await scanner.scan_posts_and_outreach(dry_run=dry_run, use_browser=True)
        print(f"\n  📊 Feed Scan Complete: {result.get('emails_sent', 0)} emails sent, {result.get('direct_links_prepared', 0)} links saved")
        return

    elif args.portal in ("ycombinator", "yc"):
        results = await run_ycombinator_auto_apply(
            keyword=args.keyword,
            location=args.location,
            target_applied=args.target_applied,
            max_jobs=args.max_jobs,
            dry_run=dry_run,
        )

    elif args.portal == "wellfound":
        results = await run_wellfound_auto_apply(
            keyword=args.keyword,
            location=args.location,
            target_applied=args.target_applied,
            max_jobs=args.max_jobs,
            dry_run=dry_run,
        )

    elif args.portal == "all":
        portals_to_run = [
            ("Cutshort", run_cutshort_auto_apply, {}),
            ("Hirist", run_hirist_auto_apply, {}),
            ("LinkedIn", run_linkedin_auto_apply, {"keyword": args.keyword, "location": args.location}),
            ("Y Combinator", run_ycombinator_auto_apply, {"keyword": args.keyword, "location": args.location}),
        ]

        for p_idx, (p_name, p_func, p_kwargs) in enumerate(portals_to_run, 1):
            logger.info(f"\n{'=' * 65}")
            logger.info(f"🌐 [PORTAL {p_idx}/{len(portals_to_run)}] Launching {p_name} Auto-Apply Agent (Target: {args.target_applied} apps)...")
            logger.info(f"{'=' * 65}")
            try:
                p_results = await p_func(
                    target_applied=args.target_applied,
                    max_jobs=args.max_jobs,
                    dry_run=dry_run,
                    **p_kwargs,
                )
                results.extend(p_results or [])
                applied_on_portal = sum(1 for r in (p_results or []) if r.get("status") in ("APPLIED", "DRY_RUN", "DRY_RUN_COMPLETED"))
                logger.info(f"✅ [{p_name}] Complete! Applications: {applied_on_portal}/{args.target_applied}. Moving to next portal...")
            except Exception as p_err:
                logger.error(f"⚠️ [{p_name}] Agent error: {p_err}. Progressing to next portal in pipeline...")
            await asyncio.sleep(3.0)

    print("\n" + "=" * 65)
    print("  📊 COMPREHENSIVE SUMMARY OF ALL PORTAL RUNS")
    print("=" * 65)
    for r in results:
        status = r.get("status")
        title = r.get("title")
        company = r.get("company")
        template = r.get("template", "N/A")
        reason = r.get("reason", "")
        if status in ("APPLIED", "DRY_RUN_COMPLETED"):
            print(f"  ✅ [{status}] {title} @ {company} | Template: {template}")
        elif status == "EXTERNAL_LINK_EMAILED":
            print(f"  📧 [{status}] {title} @ {company} | Direct Link & Tailored Resume sent to kamalkumar.doddi@gmail.com")
        elif status == "SKIPPED_EXP":
            print(f"  ⏩ [{status}] {title} @ {company} | {reason}")
        else:
            print(f"  ℹ️ [{status}] {title} @ {company}")
if __name__ == "__main__":
    import sys
    # Suppress harmless Python/Windows asyncio proactor pipe transport cleanup warning on exit
    if sys.platform == "win32":
        try:
            from asyncio.proactor_events import _ProactorBasePipeTransport
            _orig_del = _ProactorBasePipeTransport.__del__
            def _safe_del(self, _warn=None):
                try:
                    _orig_del(self, _warn)
                except (ValueError, Exception):
                    pass
            _ProactorBasePipeTransport.__del__ = _safe_del
        except Exception:
            pass

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
