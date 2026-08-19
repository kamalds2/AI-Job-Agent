"""
Agent API — endpoints to control and monitor the AI Job Agent.
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services.scheduler_service import (
    get_scheduler_status,
    start_scheduler,
    stop_scheduler,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])

# Track last run result in memory
_last_run_result: Optional[dict] = None
_is_running: bool = False


class RunRequest(BaseModel):
    dry_run: bool = False


@router.post("/run")
async def trigger_agent_run(request: RunRequest, background_tasks: BackgroundTasks):
    """
    Manually trigger the AI Job Agent pipeline.
    Runs in the background — returns immediately with run_id.
    """
    global _is_running

    if _is_running:
        raise HTTPException(status_code=409, detail="Agent is already running")

    async def run_in_background():
        global _is_running, _last_run_result
        _is_running = True
        try:
            from app.agents.orchestrator import run_agent
            result = await run_agent(dry_run=request.dry_run)
            _last_run_result = {
                "run_id": result.get("run_id"),
                "timestamp": result.get("run_timestamp"),
                "raw_jobs": result.get("raw_jobs_count", 0),
                "new_jobs": result.get("new_jobs_count", 0),
                "scored": len(result.get("scored_jobs", [])),
                "qualified": len(result.get("qualified_job_ids", [])),
                "resumes": len(result.get("resume_paths", {})),
                "emails_sent": result.get("emails_sent", 0),
                "whatsapp_sent": result.get("whatsapp_sent", False),
                "report_path": result.get("report_path"),
                "errors": result.get("errors", []),
                "logs": result.get("logs", []),
                "status": "completed",
            }
        except Exception as e:
            logger.error(f"Background run failed: {e}")
            _last_run_result = {"status": "failed", "error": str(e)}
        finally:
            _is_running = False

    background_tasks.add_task(run_in_background)

    return {
        "message": "Agent run started in background",
        "dry_run": request.dry_run,
        "status": "started",
    }


@router.get("/status")
def get_agent_status():
    """Get current agent and scheduler status."""
    return {
        "agent_running": _is_running,
        "last_run": _last_run_result,
        "scheduler": get_scheduler_status(),
    }


@router.get("/last-run")
def get_last_run():
    """Get results from the last agent run."""
    if not _last_run_result:
        return {"message": "No runs yet", "result": None}
    return _last_run_result


@router.post("/scheduler/start")
def start_agent_scheduler():
    """Start the 6-hour automatic scheduler."""
    start_scheduler()
    return {"message": "Scheduler started", "status": get_scheduler_status()}


@router.post("/scheduler/stop")
def stop_agent_scheduler():
    """Stop the automatic scheduler."""
    stop_scheduler()
    return {"message": "Scheduler stopped"}


@router.get("/scheduler/status")
def scheduler_status():
    """Get scheduler status and next run time."""
    return get_scheduler_status()
