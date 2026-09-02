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
    """APScheduler job function — runs the agent pipeline and LinkedIn recruiter feed scanner."""
    import asyncio
    from app.agents.orchestrator import run_agent_sync
    from app.services.linkedin_feed_scanner import LinkedInFeedScanner

    logger.info("⏰ Scheduled agent run starting (Job Boards & ATS Pipeline)...")
    try:
        result = run_agent_sync()
        logger.info(
            f"✅ Scheduled run complete — "
            f"new: {result.get('new_jobs_count', 0)}, "
            f"qualified: {len(result.get('qualified_job_ids', []))}"
        )
    except Exception as e:
        logger.error(f"❌ Scheduled ATS run failed: {e}")

    logger.info("🔍 Scheduled LinkedIn Recruiter Feed & Outreach starting...")
    try:
        scanner = LinkedInFeedScanner()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        recruiter_result = loop.run_until_complete(scanner.scan_posts_and_outreach(dry_run=False))
        loop.close()
        logger.info(
            f"✅ Scheduled LinkedIn Outreach complete — "
            f"posts: {recruiter_result.get('posts_scanned', 0)}, "
            f"sent: {recruiter_result.get('emails_sent', 0)}"
        )
    except Exception as e:
        logger.error(f"❌ Scheduled LinkedIn feed scan failed: {e}")


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
    logger.info(
        "⏰ Scheduler started — 24/7 fixed runs scheduled at 06:00 AM, 12:00 PM, 06:00 PM, 12:00 AM IST"
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
