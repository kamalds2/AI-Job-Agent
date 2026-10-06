"""
Scheduler Service — APScheduler that runs the agent every 6 hours.

Schedule:
  - 06:00 AM IST
  - 12:00 PM IST
  - 06:00 PM IST
  - 12:00 AM IST

Can also be configured to run at a fixed interval.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config.settings import SCHEDULER_INTERVAL_HOURS

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_agent_job():
    """APScheduler job function — runs the master multi-agent pipeline."""
    import sys
    import asyncio
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    from app.agents.orchestrator import run_full_multi_agent_pipeline_sync

    logger.info("⏰ Scheduled multi-agent job run starting...")
    try:
        summary = run_full_multi_agent_pipeline_sync(dry_run=False)
        logger.info("✅ Scheduled multi-agent pipeline completed successfully!")
    except Exception as e:
        logger.error(f"❌ Scheduled multi-agent run failed: {e}", exc_info=True)


def start_scheduler():
    """Start the APScheduler background scheduler configured for 6 AM, 12 PM, 6 PM, 12 AM IST."""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler already running")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Run at fixed times: 06:00 AM, 12:00 PM (Noon), 06:00 PM, 12:00 AM (Midnight) IST
    _scheduler.add_job(
        _run_agent_job,
        trigger=CronTrigger(hour="0,6,12,18", minute="0", timezone="Asia/Kolkata"),
        id="job_agent_run",
        name="AI Job Agent 6-Hour Run (06:00, 12:00, 18:00, 00:00 IST)",
        replace_existing=True,
        max_instances=1,  # Only one run at a time
    )

    _scheduler.start()
    next_run = None
    for j in _scheduler.get_jobs():
        if j.id == "job_agent_run":
            next_run = j.next_run_time
            break
    logger.info(
        f"⏰ Scheduler active — 24/7 fixed runs scheduled at 06:00 AM, 12:00 PM, 06:00 PM, 12:00 AM IST (Next Run: {next_run})"
    )


def stop_scheduler():
    """Stop the APScheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("⏰ Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return current scheduler status."""
    if not _scheduler:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })

    return {
        "running": _scheduler.running,
        "interval_hours": SCHEDULER_INTERVAL_HOURS,
        "jobs": jobs,
    }
