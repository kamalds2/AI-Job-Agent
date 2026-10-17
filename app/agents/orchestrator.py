"""
LangGraph Orchestrator — builds and runs the job agent StateGraph.

Graph:
    search_node → scoring_node → resume_node → email_node → notify_node → report_node → END

The graph is run synchronously via asyncio for APScheduler compatibility.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.agents.state import AgentState
from app.agents.nodes import (
    make_search_node,
    make_scoring_node,
    make_resume_node,
    make_email_node,
    make_report_node,
)
from app.config.settings import DRY_RUN
from app.database.database import SessionLocal

logger = logging.getLogger(__name__)


def build_graph(db: Session) -> StateGraph:
    """
    Build the LangGraph StateGraph for the job agent.

    Architecture:
        search → scoring → resume → email → report → END
    """
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("search", make_search_node(db))
    graph.add_node("scoring", make_scoring_node(db))
    graph.add_node("resume", make_resume_node(db))
    graph.add_node("email", make_email_node(db))
    graph.add_node("report", make_report_node())

    # Entry point
    graph.set_entry_point("search")

    # Linear edges
    graph.add_edge("search", "scoring")
    graph.add_edge("scoring", "resume")
    graph.add_edge("resume", "email")
    graph.add_edge("email", "report")
    graph.add_edge("report", END)

    return graph.compile()


async def run_agent(
    dry_run: Optional[bool] = None,
    include_browser_agents: bool = False,
    target_per_portal: int = 5,
    portals: Optional[list] = None,
    include_indeed: bool = False,
    include_career_sites: bool = False,
    career_sites_excel: Optional[str] = None,
    career_sites_target: int = 10,
    career_sites_country: Optional[str] = None,
) -> AgentState:
    """
    Run the complete job agent pipeline.

    Args:
        dry_run: Override DRY_RUN setting. None uses env setting.
        include_browser_agents: Whether to automatically launch Phase 3 browser agents after Phase 1.
        target_per_portal: Target applications per portal for browser agents.
        portals: Specific portals to run in browser agent phase.
        include_indeed: Whether to unpause Indeed browser agent.
        include_career_sites: Whether to run Phase 4 Global Career Sites agent.
        career_sites_excel: Path to Excel spreadsheet for Phase 4.
        career_sites_target: Application target for Phase 4.
        career_sites_country: Country filter for Phase 4.

    Returns:
        Final AgentState with all results.
    """
    run_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat()
    is_dry_run = dry_run if dry_run is not None else DRY_RUN

    logger.info(f"🚀 AI Job Agent starting — Run ID: {run_id} | DRY_RUN: {is_dry_run}")

    # Initial state
    initial_state: AgentState = {
        "run_id": run_id,
        "run_timestamp": timestamp,
        "dry_run": is_dry_run,
        "raw_jobs_count": 0,
        "new_jobs_count": 0,
        "new_job_ids": [],
        "scored_jobs": [],
        "qualified_job_ids": [],
        "resume_paths": {},
        "email_drafts": [],
        "emails_sent": 0,
        "report_path": None,
        "browser_stats": None,
        "career_sites_stats": None,
        "errors": [],
        "logs": [],
    }

    db: Session = SessionLocal()
    try:
        app = build_graph(db)
        final_state = await app.ainvoke(initial_state)

        # Phase 3: Sequential Browser Auto-Apply Agents (if enabled)
        if include_browser_agents:
            logger.info("🌐 [Orchestrator] Starting Phase 3: Sequential Browser Auto-Apply Agents...")
            try:
                from app.agents.browser_agent.sequential_browser_orchestrator import SequentialBrowserOrchestrator
                browser_orchestrator = SequentialBrowserOrchestrator(
                    dry_run=is_dry_run,
                    include_indeed=include_indeed,
                )
                b_portals = portals or ["linkedin", "ycombinator", "hirist", "cutshort"]
                browser_stats = await browser_orchestrator.run(
                    target_per_portal=target_per_portal,
                    portals_to_run=b_portals,
                )
                final_state["browser_stats"] = browser_stats
            except Exception as b_err:
                logger.error(f"❌ Browser agent execution error: {b_err}")
                final_state["errors"].append(f"Browser auto-apply error: {b_err}")

        # Phase 4: Global Career Sites Autonomous Agent (if enabled)
        if include_career_sites:
            logger.info("🌐 [Orchestrator] Starting Phase 4: Global Career Sites Autonomous Agent...")
            try:
                from app.services.global_career_sites_agent import run_global_career_sites_apply
                c_stats = await run_global_career_sites_apply(
                    excel_path=career_sites_excel,
                    target_applied=career_sites_target,
                    country=career_sites_country,
                    dry_run=is_dry_run,
                )
                final_state["career_sites_stats"] = c_stats
            except Exception as c_err:
                logger.error(f"❌ Global Career Sites agent execution error: {c_err}")
                final_state["errors"].append(f"Global career sites error: {c_err}")

        # Summary logging
        logger.info("=" * 60)
        logger.info(f"✅ Agent Run Complete — ID: {run_id}")
        logger.info(f"   Jobs fetched:    {final_state.get('raw_jobs_count', 0)}")
        logger.info(f"   New jobs saved:  {final_state.get('new_jobs_count', 0)}")
        logger.info(f"   Scored:          {len(final_state.get('scored_jobs', []))}")
        logger.info(f"   Qualified:       {len(final_state.get('qualified_job_ids', []))}")
        logger.info(f"   Resumes made:    {len(final_state.get('resume_paths', {}))}")
        logger.info(f"   Emails sent:     {final_state.get('emails_sent', 0)}")
        logger.info(f"   Report:          {final_state.get('report_path', 'N/A')}")
        if final_state.get("browser_stats"):
            logger.info(f"   Browser Apps:    {final_state['browser_stats'].get('total_applied', 0)}")
        if final_state.get("career_sites_stats"):
            logger.info(f"   Career Site Apps:{final_state['career_sites_stats'].get('total_applied', 0)}")
        if final_state.get("errors"):
            logger.warning(f"   Errors:          {final_state['errors']}")
        logger.info("=" * 60)

        return final_state

    except Exception as e:
        logger.error(f"❌ Agent run failed: {e}")
        raise
    finally:
        db.close()


def run_agent_sync(
    dry_run: Optional[bool] = None,
    include_browser_agents: bool = False,
    target_per_portal: int = 5,
    portals: Optional[list] = None,
    include_indeed: bool = False,
) -> AgentState:
    """
    Synchronous wrapper for run_agent.
    Used by APScheduler and CLI scripts.
    """
    return asyncio.run(run_agent(
        dry_run=dry_run,
        include_browser_agents=include_browser_agents,
        target_per_portal=target_per_portal,
        portals=portals,
        include_indeed=include_indeed,
    ))

