"""
CLI script to run the AI Job Agent — Full 3-Phase Autonomous Execution.

Phases:
    Phase 1: Job Boards & ATS Aggregator Pipeline (Search, Gemini Scoring, Tailored Resumes, 1-Click Links/Reports)
    Phase 2: LinkedIn Recruiter Feed & HR Outreach Pipeline (Feed Scanning, Email Extraction, Cold Outreach)
    Phase 3: Sequential Multi-Board Browser Auto-Apply Pipeline (LinkedIn, Y Combinator, Hirist, Cutshort)

Usage:
    python scripts/run_agent.py                      # Full 3-phase run
    python scripts/run_agent.py --dry-run            # Dry run across all 3 phases
    python scripts/run_agent.py --target 5           # Target applications per portal for Phase 3
    python scripts/run_agent.py --portals linkedin ycombinator hirist cutshort
    python scripts/run_agent.py --include-indeed     # Include Indeed in Phase 3 (paused by default)
    python scripts/run_agent.py --browser-only       # Only execute Phase 3 browser agents
    python scripts/run_agent.py --skip-browser       # Execute Phase 1 & 2 without launching browser
    python scripts/run_agent.py --search-only        # Only run job search without AI scoring
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="KKNN Autonomous AI Job Agent CLI — 3-Phase Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails / dry-run on browser forms")
    parser.add_argument("--search-only", action="store_true", help="Only run job search, skip AI scoring and browser apply")
    parser.add_argument("--target", type=int, default=5, help="Target applications per portal for Phase 3 browser agents (Default: 5)")
    parser.add_argument("--portals", nargs="+", default=None, help="Specific portals for browser agent: linkedin ycombinator hirist cutshort indeed")
    parser.add_argument("--include-indeed", action="store_true", help="Unpause and include Indeed browser agent")
    parser.add_argument("--skip-browser", action="store_true", help="Skip Phase 3 browser auto-apply agents")
    parser.add_argument("--browser-only", action="store_true", help="Only run Phase 3 browser auto-apply agents")
    parser.add_argument("--skip-recruiter", action="store_true", help="Skip Phase 2 LinkedIn recruiter feed outreach")
    args = parser.parse_args()

    from app.config.settings import CANDIDATE_NAME, CANDIDATE_EXPERIENCE_YEARS

    print("\n" + "=" * 70)
    print("  🌐 [KKNN AUTONOMOUS JOB ASSISTANT — 3-PHASE PIPELINE]")
    print(f"  🎯 [CANDIDATE: {CANDIDATE_NAME.upper()} — SOFTWARE / JAVA & AI DEVELOPER ({CANDIDATE_EXPERIENCE_YEARS.upper()})]")
    print("=" * 70)

    if args.dry_run:
        print("  ⚠️  [DRY RUN MODE ENABLED]: No emails sent, forms filled up to review")
    if args.search_only:
        print("  🔍  [SEARCH ONLY]: No AI scoring or auto-apply")
    if args.browser_only:
        print("  🖥️  [BROWSER AGENTS ONLY]: Skipping API & Recruiter feed pipelines")
    elif not args.skip_browser:
        print(f"  📊  Target Browser Applications per Portal: {args.target}")
    print("=" * 70 + "\n")

    # ── Search Only Mode ──────────────────────────────────────────
    if args.search_only:
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
        return

    phase1_result = {}
    phase2_result = {}
    browser_stats = {"total_applied": 0, "portals": {}}

    # ── Phase 1: Job Boards & ATS Aggregator Pipeline ─────────────
    if not args.browser_only:
        from app.agents.orchestrator import run_agent

        print("━" * 70)
        print("🚀 [PHASE 1/3] EXECUTING JOB BOARDS & ATS AGGREGATOR PIPELINE...")
        print("━" * 70)
        phase1_result = await run_agent(dry_run=args.dry_run, include_browser_agents=False)

        print(f"\n✅ [Phase 1 Complete] Job Boards & ATS Pipeline:")
        print(f"   • Jobs fetched from boards:    {phase1_result.get('raw_jobs_count', 0)}")
        print(f"   • New qualified jobs:          {len(phase1_result.get('qualified_job_ids', []))}")
        print(f"   • ATS Resumes Tailored:        {len(phase1_result.get('resume_paths', {}))}")
        print(f"   • 1-Click Apply Links:         {phase1_result.get('emails_sent', 0)}")
        print(f"   • Pipeline Report:             {phase1_result.get('report_path', 'N/A')}")

    # ── Phase 2: LinkedIn Recruiter Feed & HR Outreach ────────────
    if not args.browser_only and not args.skip_recruiter:
        from app.services.linkedin_feed_scanner import LinkedInFeedScanner

        print("\n" + "━" * 70)
        print("📨 [PHASE 2/3] EXECUTING LINKEDIN RECRUITER FEED & HR OUTREACH...")
        print("━" * 70)
        scanner = LinkedInFeedScanner()
        phase2_result = await scanner.scan_posts_and_outreach(dry_run=args.dry_run)

        print(f"\n✅ [Phase 2 Complete] LinkedIn Recruiter Outreach:")
        print(f"   • LinkedIn Posts Scanned:      {phase2_result.get('posts_scanned', 0)}")
        print(f"   • Verified Recruiter Contacts: {phase2_result.get('recruiter_emails_found', 0)}")
        print(f"   • Outreach Emails Dispatched:  {phase2_result.get('emails_sent', 0)}")
        print(f"   • Recruiter HR Report:         {phase2_result.get('report_path', 'N/A')}")

    # ── Phase 3: Sequential Browser Auto-Apply Agents ─────────────
    if not args.skip_browser:
        from app.agents.browser_agent.sequential_browser_orchestrator import SequentialBrowserOrchestrator

        selected_portals = args.portals
        if selected_portals is None:
            if args.include_indeed:
                selected_portals = ["linkedin", "indeed", "ycombinator", "hirist", "cutshort"]
            else:
                selected_portals = ["linkedin", "ycombinator", "hirist", "cutshort"]
        else:
            selected_portals = [p.lower().strip() for p in selected_portals]
            if "indeed" in selected_portals and not args.include_indeed:
                print("  ⏸️  [PAUSED]: Indeed is paused by user preference until further notice.")
                print("      (Pass --include-indeed to explicitly unpause Indeed)")
                selected_portals = [p for p in selected_portals if p != "indeed"]

        print("\n" + "━" * 70)
        print("🌐 [PHASE 3/3] EXECUTING SEQUENTIAL MULTI-BOARD BROWSER AUTO-APPLY AGENTS...")
        print(f"👉 Target per portal: {args.target} | Portals: {', '.join(p.upper() for p in selected_portals)}")
        print("━" * 70)

        browser_orchestrator = SequentialBrowserOrchestrator(
            dry_run=args.dry_run,
            include_indeed=args.include_indeed,
        )
        browser_stats = await browser_orchestrator.run(
            target_per_portal=args.target,
            portals_to_run=selected_portals,
        )

    # ── Final Consolidated Summary ────────────────────────────────
    print("\n" + "=" * 70)
    print("  🎉 [KKNN AUTONOMOUS JOB AGENT — RUN FINISHED SUCCESSFULLY]")
    print("=" * 70)
    if not args.browser_only:
        print(f"  • Phase 1 (Job Boards & ATS):   {len(phase1_result.get('qualified_job_ids', []))} qualified, {len(phase1_result.get('resume_paths', {}))} resumes")
        if not args.skip_recruiter:
            print(f"  • Phase 2 (Recruiter Outreach): {phase2_result.get('emails_sent', 0)} cold emails to HR ({phase2_result.get('recruiter_emails_found', 0)} verified)")
    if not args.skip_browser:
        print(f"  • Phase 3 (Browser Auto-Apply): {browser_stats.get('total_applied', 0)} applications submitted")
        for portal_name, count in browser_stats.get("portals", {}).items():
            print(f"     ✅ {portal_name.upper():14}: {count} applied")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
