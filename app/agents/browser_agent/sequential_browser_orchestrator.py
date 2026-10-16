"""
Phase 3 Sequential Multi-Board Browser Auto-Apply Orchestrator.
Sequentially executes:
  1. LinkedIn Browser Agent ->
  2. Y Combinator Browser Agent ->
  3. Hirist Browser Agent ->
  4. Cutshort Browser Agent ->
  5. (Optional) Indeed / Wellfound Browser Agent
Reuses the shared live browser context via CDP Port 9222.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from app.config.settings import CANDIDATE_EXPERIENCE_YEARS, CANDIDATE_NAME
from app.services.cutshort_browser_agent import run_cutshort_auto_apply
from app.services.hirist_browser_agent import run_hirist_auto_apply
from app.services.indeed_browser_agent import run_indeed_auto_apply
from app.services.linkedin_browser_agent import run_linkedin_auto_apply
from app.services.wellfound_browser_agent import run_wellfound_auto_apply
from app.services.ycombinator_browser_agent import run_ycombinator_auto_apply

logger = logging.getLogger(__name__)


class SequentialBrowserOrchestrator:
    """
    Coordinates browser auto-apply agents in sequential execution.
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: Optional[str] = None,
        browser_executable_path: Optional[str] = None,
        dry_run: bool = False,
        include_indeed: bool = False,
    ):
        self.cdp_port = cdp_port
        self.user_data_dir = user_data_dir
        self.browser_executable_path = browser_executable_path
        self.dry_run = dry_run
        self.include_indeed = include_indeed or (os.getenv("INCLUDE_INDEED", "false").lower() in ("true", "1", "yes"))

    async def run(
        self,
        target_per_portal: int = 5,
        portals_to_run: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        location: str = "India",
    ) -> Dict[str, Any]:
        """
        Executes sequential pipeline across job portals.
        """
        if portals_to_run is None:
            active_portals = ["linkedin", "ycombinator", "hirist", "cutshort"]
        else:
            active_portals = [p.lower().strip() for p in portals_to_run]

        if "indeed" in active_portals and not self.include_indeed:
            active_portals = [p for p in active_portals if p != "indeed"]

        overall_stats = {
            "total_applied": 0,
            "portals": {},
        }

        logger.info("\n" + "#" * 68)
        logger.info(f"🌐 [PHASE 3: SEQUENTIAL MULTI-BOARD BROWSER AUTO-APPLY PIPELINE]")
        logger.info(f"🎯 Candidate: {CANDIDATE_NAME} ({CANDIDATE_EXPERIENCE_YEARS})")
        logger.info(f"👉 Active Portals: {', '.join(p.upper() for p in active_portals)}")
        if "indeed" not in active_portals and not self.include_indeed:
            logger.info("⏸️  Indeed Browser Agent: PAUSED")
        logger.info(f"🎯 Target per portal: {target_per_portal} applications")
        logger.info("#" * 68 + "\n")

        if not active_portals:
            logger.info("ℹ️ No active portals to run. Exiting without launching browser.")
            return overall_stats

        for portal in active_portals:
            portal_applied = 0
            try:
                if portal in ("linkedin", "li"):
                    logger.info("\n>>> STARTING PORTAL: LINKEDIN BROWSER AGENT <<<")
                    res = await run_linkedin_auto_apply(
                        keyword=keyword,
                        location=location,
                        target_applied=target_per_portal,
                        dry_run=self.dry_run,
                    )
                    portal_applied = len(res) if res else 0

                elif portal in ("ycombinator", "yc"):
                    logger.info("\n>>> STARTING PORTAL: Y COMBINATOR BROWSER AGENT <<<")
                    res = await run_ycombinator_auto_apply(
                        keyword=keyword,
                        location=location,
                        target_applied=target_per_portal,
                        dry_run=self.dry_run,
                    )
                    portal_applied = len(res) if res else 0

                elif portal == "hirist":
                    logger.info("\n>>> STARTING PORTAL: HIRIST BROWSER AGENT <<<")
                    res = await run_hirist_auto_apply(
                        target_applied=target_per_portal,
                        dry_run=self.dry_run,
                    )
                    portal_applied = len(res) if res else 0

                elif portal == "cutshort":
                    logger.info("\n>>> STARTING PORTAL: CUTSHORT BROWSER AGENT <<<")
                    res = await run_cutshort_auto_apply(
                        target_applied=target_per_portal,
                        dry_run=self.dry_run,
                    )
                    portal_applied = len(res) if res else 0

                elif portal in ("wellfound", "angel"):
                    logger.info("\n>>> STARTING PORTAL: WELLFOUND BROWSER AGENT <<<")
                    res = await run_wellfound_auto_apply(
                        keyword=keyword,
                        location=location,
                        target_applied=target_per_portal,
                        dry_run=self.dry_run,
                    )
                    portal_applied = len(res) if res else 0

                elif portal == "indeed":
                    logger.info("\n>>> STARTING PORTAL: INDEED BROWSER AGENT <<<")
                    res = await run_indeed_auto_apply(
                        keyword=keyword or "Java Developer",
                        location=location,
                        target_applied=target_per_portal,
                        dry_run=self.dry_run,
                    )
                    portal_applied = len(res) if res else 0

                overall_stats["portals"][portal] = portal_applied
                overall_stats["total_applied"] += portal_applied
                logger.info(f">>> {portal.upper()} COMPLETE: {portal_applied} applied <<<\n")

            except Exception as p_err:
                logger.error(f"Error executing browser agent for {portal}: {p_err}", exc_info=True)
                overall_stats["portals"][portal] = 0

        logger.info("\n" + "=" * 68)
        logger.info("🎉 [PHASE 3 COMPLETE: SEQUENTIAL MULTI-PORTAL AUTO-APPLY FINISHED]")
        logger.info(f"📊 Total Applications Submitted: {overall_stats['total_applied']}")
        for p, count in overall_stats["portals"].items():
            logger.info(f"   • {p.upper():15}: {count} applied")
        logger.info("=" * 68 + "\n")

        return overall_stats
