"""
LangGraph Orchestrator — builds and runs the job agent StateGraph.

Graph:
    search_node → scoring_node → resume_node → email_node → report_node → END

The graph is run synchronously via asyncio for APScheduler compatibility.
"""
import sys
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

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


def _run_in_proactor_thread(async_func, *args, **kwargs):
    """
    Run an async coroutine inside a dedicated ProactorEventLoop on Windows.
    This guarantees that Playwright async subprocesses never hit NotImplementedError
    even when triggered from within Uvicorn/FastAPI or foreign event loops.
    """
    import threading

    result_container = {}
    exc_container = {}

    def _worker():
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_container["res"] = loop.run_until_complete(async_func(*args, **kwargs))
        except Exception as e:
            exc_container["err"] = e
        finally:
            try:
                loop.close()
            except Exception:
                pass

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join()

    if "err" in exc_container:
        raise exc_container["err"]
    return result_container.get("res")


async def run_full_multi_agent_pipeline(
    dry_run: Optional[bool] = None,
    target_applied_per_portal: int = 40,
    keyword: str = "Java Backend Developer",
    location: str = "India",
) -> dict:
    """
    Master Multi-Agent Workflow:
      Phase 1: Job Search Aggregator -> Gemini AI Scoring -> Tailored Resumes -> Notifications & Reports
      Phase 2: LinkedIn Recruiter Feed Scanner -> Extract HR Emails -> Cold Email Outreach
      Phase 3: Sequential Browser Auto-Apply Agents (LinkedIn -> Indeed -> YC -> Hirist -> Cutshort)
               Each agent targets 40-50 applications before automatically switching to the next portal.
    """
    is_dry_run = dry_run if dry_run is not None else DRY_RUN
    pipeline_summary = {
        "start_time": datetime.utcnow().isoformat(),
        "dry_run": is_dry_run,
        "phase1_aggregator": {},
        "phase2_recruiter_outreach": {},
        "phase3_browser_agents": {},
    }

    logger.info("\n" + "=" * 70)
    logger.info("🤖 [MULTI-AGENT WORKFLOW] STARTING FULL END-TO-END JOB ACQUISITION")
    logger.info(f"   Target:           {target_applied_per_portal} apps per browser portal (Max 40-50)")
    logger.info(f"   Mode:             {'🧪 DRY RUN (Safe Testing)' if is_dry_run else '🚀 LIVE SUBMISSIONS'}")
    logger.info("=" * 70)

    # ── PHASE 1: JOB BOARDS & ATS AGGREGATOR AGENT ────────────────────────────
    logger.info("\n📦 [PHASE 1/3] Launching Job Boards & ATS Aggregator Agent...")
    try:
        p1_result = await run_agent(dry_run=is_dry_run)
        pipeline_summary["phase1_aggregator"] = {
            "jobs_fetched": p1_result.get("raw_jobs_count", 0),
            "new_jobs": p1_result.get("new_jobs_count", 0),
            "scored": len(p1_result.get("scored_jobs", [])),
            "qualified": len(p1_result.get("qualified_job_ids", [])),
            "resumes_made": len(p1_result.get("resume_paths", {})),
            "report_path": p1_result.get("report_path"),
        }
        logger.info(f"✅ [PHASE 1 COMPLETE] Scored {pipeline_summary['phase1_aggregator']['scored']} jobs, Generated Report.")
    except Exception as e:
        logger.error(f"⚠️ [PHASE 1 ERROR] {e}", exc_info=True)
        pipeline_summary["phase1_aggregator"]["error"] = str(e)

    await asyncio.sleep(2.0)

    # ── PHASE 2: LINKEDIN RECRUITER FEED SCANNER & OUTREACH ──────────────────
    logger.info("\n📬 [PHASE 2/3] Launching LinkedIn Recruiter Feed Scanner & HR Cold Outreach...")
    try:
        from app.services.linkedin_feed_scanner import LinkedInFeedScanner
        scanner = LinkedInFeedScanner()
        recruiter_result = await asyncio.to_thread(_run_in_proactor_thread, scanner.scan_posts_and_outreach, dry_run=is_dry_run)
        pipeline_summary["phase2_recruiter_outreach"] = {
            "posts_scanned": recruiter_result.get("posts_scanned", 0),
            "recruiter_emails_found": recruiter_result.get("recruiter_emails_found", 0),
            "emails_sent": recruiter_result.get("emails_sent", 0),
            "direct_links_prepared": recruiter_result.get("direct_links_prepared", 0),
            "report_path": recruiter_result.get("report_path"),
        }
        logger.info(f"✅ [PHASE 2 COMPLETE] Dispatched {pipeline_summary['phase2_recruiter_outreach']['emails_sent']} outreach emails to verified recruiters.")
    except Exception as e:
        logger.error(f"⚠️ [PHASE 2 ERROR] {e}", exc_info=True)
        pipeline_summary["phase2_recruiter_outreach"]["error"] = str(e)

    await asyncio.sleep(3.0)

    # ── PHASE 3: SEQUENTIAL BROWSER AUTO-APPLY AGENTS ────────────────────────
    logger.info("\n🌐 [PHASE 3/3] Launching Sequential Multi-Board Browser Auto-Apply Agents...")
    from app.services.linkedin_browser_agent import run_linkedin_auto_apply
    from app.services.ycombinator_browser_agent import run_ycombinator_auto_apply
    from app.services.hirist_browser_agent import run_hirist_auto_apply
    from app.services.cutshort_browser_agent import run_cutshort_auto_apply

    browser_portals = [
        ("LinkedIn", run_linkedin_auto_apply, {"keyword": keyword, "location": location}),
        ("Y Combinator", run_ycombinator_auto_apply, {"keyword": keyword, "location": location}),
        ("Hirist", run_hirist_auto_apply, {}),
        ("Cutshort", run_cutshort_auto_apply, {}),
    ]

    phase3_results = {}
    for idx, (portal_name, run_func, extra_kwargs) in enumerate(browser_portals, 1):
        logger.info(f"\n{'─' * 65}")
        logger.info(f"👉 [BROWSER AGENT {idx}/{len(browser_portals)}] Starting {portal_name} (Target: {target_applied_per_portal} apps)...")
        logger.info(f"{'─' * 65}")
        try:
            portal_res = await asyncio.to_thread(
                _run_in_proactor_thread,
                run_func,
                target_applied=target_applied_per_portal,
                max_jobs=50,
                dry_run=is_dry_run,
                **extra_kwargs,
            )
            applied_count = sum(1 for r in (portal_res or []) if r.get("status") in ("APPLIED", "DRY_RUN", "DRY_RUN_COMPLETED"))
            phase3_results[portal_name] = {
                "status": "completed",
                "applications": applied_count,
                "target": target_applied_per_portal,
            }
            logger.info(f"✅ [{portal_name}] Finished with {applied_count}/{target_applied_per_portal} applications. Moving to next portal...")
        except Exception as b_err:
            logger.error(f"⚠️ [{portal_name}] Agent run notice: {b_err}. Moving to next portal...")
            phase3_results[portal_name] = {"status": "error", "error": str(b_err)}

        # Wait for the previous agent's Playwright CDP WebSocket to fully close
        # before the next agent tries to connect to the same Chrome port.
        await asyncio.sleep(8.0)

    pipeline_summary["phase3_browser_agents"] = phase3_results
    pipeline_summary["end_time"] = datetime.utcnow().isoformat()

    logger.info("\n" + "=" * 70)
    logger.info("🎉 [MULTI-AGENT WORKFLOW COMPLETED] ALL PIPELINES EXECUTED SUCCESSFULLY!")
    logger.info("=" * 70)

    return pipeline_summary


def run_full_multi_agent_pipeline_sync(
    dry_run: Optional[bool] = None,
    target_applied_per_portal: int = 40,
) -> dict:
    """Synchronous wrapper for full multi-agent pipeline."""
    return asyncio.run(run_full_multi_agent_pipeline(
        dry_run=dry_run,
        target_applied_per_portal=target_applied_per_portal,
    ))
