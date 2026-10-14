"""
Phase 3 Sequential Multi-Board Browser Auto-Apply Orchestrator.
Sequentially executes:
  1. LinkedIn Browser Agent (40-50 apps) ->
  2. Indeed Browser Agent (40-50 apps) ->
  3. Y Combinator Browser Agent (40-50 apps) ->
  4. Hirist Browser Agent (40-50 apps) ->
  5. Cutshort Browser Agent (40-50 apps)
Reuses the shared live browser context via CDP Port 9222.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from app.agents.browser_agent.browser_client import SharedBrowserClient
from app.agents.browser_agent.cutshort_browser_agent import CutshortBrowserAgent
from app.agents.browser_agent.hirist_browser_agent import HiristBrowserAgent
from app.agents.browser_agent.indeed_browser_agent import IndeedBrowserAgent
from app.agents.browser_agent.linkedin_browser_agent import LinkedInBrowserAgent
from app.agents.browser_agent.ycombinator_browser_agent import YCombinatorBrowserAgent

logger = logging.getLogger(__name__)


class SequentialBrowserOrchestrator:
    """
    Coordinates 5 browser auto-apply agents in sequential execution.
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
        self.browser_client = SharedBrowserClient(
            cdp_port=cdp_port,
            user_data_dir=user_data_dir,
            browser_executable_path=browser_executable_path,
            dry_run=dry_run,
        )

    async def run(
        self,
        target_per_portal: int = 45,
        portals_to_run: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes sequential pipeline across all 5 job portals.
        """
        # Default active portals with Indeed paused per user request
        if portals_to_run is None:
            active_portals = ["linkedin", "ycombinator", "hirist", "cutshort"]
        else:
            active_portals = portals_to_run

        overall_stats = {
            "total_applied": 0,
            "portals": {},
        }

        logger.info("\n" + "#" * 68)
        logger.info(f"🌐 [PHASE 3: SEQUENTIAL MULTI-BOARD BROWSER AUTO-APPLY PIPELINE]")
        logger.info(f"👉 Active Portals: {', '.join(p.upper() for p in active_portals)}")
        if "indeed" not in active_portals:
            logger.info("⏸️  Indeed Browser Agent: PAUSED")
        logger.info(f"🎯 Target per portal: {target_per_portal} applications (Fresher / 0-1 Years Finance)")
        logger.info("#" * 68 + "\n")

        if not active_portals:
            logger.info("ℹ️ No active portals to run. Exiting without launching browser.")
            return overall_stats

        try:
            # 1. Establish single shared browser connection
            page = await self.browser_client.connect()
            context = self.browser_client._context

            # ── 1. LinkedIn Browser Agent ──────────────────────────────
            if "linkedin" in active_portals:
                try:
                    logger.info("\n>>> STARTING PORTAL: LINKEDIN BROWSER AGENT <<<")
                    page = await self.browser_client.ensure_active_page()
                    agent = LinkedInBrowserAgent(dry_run=self.dry_run)
                    await agent.connect(context=context, page=page)
                    li_results = await agent.run_auto_apply(target_applied=target_per_portal)
                    overall_stats["portals"]["linkedin"] = len(li_results)
                    overall_stats["total_applied"] += len(li_results)
                    logger.info(f">>> LINKEDIN COMPLETE: {len(li_results)} applied <<<\n")
                except Exception as li_err:
                    logger.error(f"LinkedIn Agent note/error: {li_err}")

            # ── 2. Indeed Browser Agent (PAUSED BY DEFAULT) ───────────
            if "indeed" in active_portals and self.include_indeed:
                try:
                    logger.info("\n>>> STARTING PORTAL: INDEED BROWSER AGENT <<<")
                    page = await self.browser_client.ensure_active_page()
                    agent = IndeedBrowserAgent(dry_run=self.dry_run, is_paused=False)
                    await agent.connect(context=context, page=page)
                    ind_results = await agent.run_auto_apply(target_applied=target_per_portal)
                    overall_stats["portals"]["indeed"] = len(ind_results)
                    overall_stats["total_applied"] += len(ind_results)
                    logger.info(f">>> INDEED COMPLETE: {len(ind_results)} applied <<<\n")
                except Exception as ind_err:
                    logger.error(f"Indeed Agent note/error: {ind_err}")
            else:
                logger.info("⏸️ [PAUSED] Indeed Browser Agent is paused per user configuration. Skipping to Y Combinator...")

            # ── 3. Y Combinator Browser Agent ──────────────────────────
            if "ycombinator" in active_portals:
                try:
                    logger.info("\n>>> STARTING PORTAL 3/5: Y COMBINATOR BROWSER AGENT <<<")
                    page = await self.browser_client.ensure_active_page()
                    agent = YCombinatorBrowserAgent(dry_run=self.dry_run)
                    await agent.connect(context=context, page=page)
                    yc_results = await agent.run_auto_apply(target_applied=target_per_portal)
                    overall_stats["portals"]["ycombinator"] = len(yc_results)
                    overall_stats["total_applied"] += len(yc_results)
                    logger.info(f">>> Y COMBINATOR COMPLETE: {len(yc_results)} applied <<<\n")
                except Exception as yc_err:
                    logger.error(f"Y Combinator Agent note/error: {yc_err}")

            # ── 4. Hirist Browser Agent ────────────────────────────────
            if "hirist" in active_portals:
                try:
                    logger.info("\n>>> STARTING PORTAL 4/5: HIRIST BROWSER AGENT <<<")
                    page = await self.browser_client.ensure_active_page()
                    agent = HiristBrowserAgent(dry_run=self.dry_run)
                    await agent.connect(context=context, page=page)
                    hir_results = await agent.run_auto_apply(target_applied=target_per_portal)
                    overall_stats["portals"]["hirist"] = len(hir_results)
                    overall_stats["total_applied"] += len(hir_results)
                    logger.info(f">>> HIRIST COMPLETE: {len(hir_results)} applied <<<\n")
                except Exception as hir_err:
                    logger.error(f"Hirist Agent note/error: {hir_err}")

            # ── 5. Cutshort Browser Agent ──────────────────────────────
            if "cutshort" in active_portals:
                try:
                    logger.info("\n>>> STARTING PORTAL 5/5: CUTSHORT BROWSER AGENT <<<")
                    page = await self.browser_client.ensure_active_page()
                    agent = CutshortBrowserAgent(dry_run=self.dry_run)
                    await agent.connect(context=context, page=page)
                    cut_results = await agent.run_auto_apply(target_applied=target_per_portal)
                    overall_stats["portals"]["cutshort"] = len(cut_results)
                    overall_stats["total_applied"] += len(cut_results)
                    logger.info(f">>> CUTSHORT COMPLETE: {len(cut_results)} applied <<<\n")
                except Exception as cut_err:
                    logger.error(f"Cutshort Agent note/error: {cut_err}")

        except Exception as e:
            logger.error(f"Sequential browser pipeline execution error: {e}", exc_info=True)
        finally:
            await self.browser_client.close()

        logger.info("\n" + "=" * 68)
        logger.info("🎉 [PHASE 3 COMPLETE: SEQUENTIAL MULTI-PORTAL AUTO-APPLY FINISHED]")
        logger.info(f"📊 Total Applications Submitted: {overall_stats['total_applied']}")
        for p, count in overall_stats["portals"].items():
            logger.info(f"   • {p.upper():15}: {count} applied")
        logger.info("=" * 68 + "\n")

        return overall_stats
