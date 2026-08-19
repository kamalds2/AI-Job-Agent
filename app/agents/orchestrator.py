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
    make_notify_node,
    make_report_node,
)
from app.config.settings import DRY_RUN
from app.database.database import SessionLocal

logger = logging.getLogger(__name__)


def build_graph(db: Session) -> StateGraph:
    """
    Build the LangGraph StateGraph for the job agent.

    Architecture:
        search → scoring → resume → email → notify → report → END
    """
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("search", make_search_node(db))
    graph.add_node("scoring", make_scoring_node(db))
    graph.add_node("resume", make_resume_node(db))
    graph.add_node("email", make_email_node(db))
    graph.add_node("notify", make_notify_node())
    graph.add_node("report", make_report_node())

    # Entry point
    graph.set_entry_point("search")

    # Linear edges
    graph.add_edge("search", "scoring")
    graph.add_edge("scoring", "resume")
    graph.add_edge("resume", "email")
    graph.add_edge("email", "notify")
    graph.add_edge("notify", "report")
    graph.add_edge("report", END)

    return graph.compile()


async def run_agent(dry_run: Optional[bool] = None) -> AgentState:
    """
    Run the complete job agent pipeline.

    Args:
        dry_run: Override DRY_RUN setting. None uses env setting.

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
        "whatsapp_sent": False,
        "report_path": None,
        "errors": [],
        "logs": [],
    }

    db: Session = SessionLocal()
    try:
        app = build_graph(db)
        final_state = await app.ainvoke(initial_state)

        # Summary logging
        logger.info("=" * 60)
        logger.info(f"✅ Agent Run Complete — ID: {run_id}")
        logger.info(f"   Jobs fetched:    {final_state.get('raw_jobs_count', 0)}")
        logger.info(f"   New jobs saved:  {final_state.get('new_jobs_count', 0)}")
        logger.info(f"   Scored:          {len(final_state.get('scored_jobs', []))}")
        logger.info(f"   Qualified:       {len(final_state.get('qualified_job_ids', []))}")
        logger.info(f"   Resumes made:    {len(final_state.get('resume_paths', {}))}")
        logger.info(f"   Emails sent:     {final_state.get('emails_sent', 0)}")
        logger.info(f"   WhatsApp sent:   {final_state.get('whatsapp_sent', False)}")
        logger.info(f"   Report:          {final_state.get('report_path', 'N/A')}")
        if final_state.get("errors"):
            logger.warning(f"   Errors:          {final_state['errors']}")
        logger.info("=" * 60)

        return final_state

    except Exception as e:
        logger.error(f"❌ Agent run failed: {e}")
        raise
    finally:
        db.close()


def run_agent_sync(dry_run: Optional[bool] = None) -> AgentState:
    """
    Synchronous wrapper for run_agent.
    Used by APScheduler and CLI scripts.
    """
    return asyncio.run(run_agent(dry_run=dry_run))
