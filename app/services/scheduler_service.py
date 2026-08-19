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
    """APScheduler job function — runs the agent pipeline."""
    from app.agents.orchestrator import run_agent_sync
    logger.info("⏰ Scheduled agent run starting...")
    try:
        result = run_agent_sync()
        logger.info(
            f"✅ Scheduled run complete — "
            f"new: {result.get('new_jobs_count', 0)}, "
            f"qualified: {len(result.get('qualified_job_ids', []))}"
        )
    except Exception as e:
        logger.error(f"❌ Scheduled run failed: {e}")


def start_scheduler():
    """Start the APScheduler background scheduler."""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler already running")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Run every N hours (default: 6)
    _scheduler.add_job(
        _run_agent_job,
        trigger=IntervalTrigger(hours=SCHEDULER_INTERVAL_HOURS),
        id="job_agent_run",
        name="AI Job Agent Run",
        replace_existing=True,
        max_instances=1,  # Only one run at a time
    )

    _scheduler.start()
    logger.info(
        f"⏰ Scheduler started — running every {SCHEDULER_INTERVAL_HOURS} hours"
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
