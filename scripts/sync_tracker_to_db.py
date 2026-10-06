"""
Sync all applied jobs from data/applied_jobs.json directly into job_agent.db.
Ensures both the database and the dashboard have complete, accurate portal distribution data.
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.database import SessionLocal
from app.models.company import Company
from app.models.job import Job
from app.models.application import Application

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync():
    db = SessionLocal()
    tracker_path = Path("data/applied_jobs.json")
    if not tracker_path.exists():
        logger.warning("applied_jobs.json not found.")
        return

    data = json.loads(tracker_path.read_text(encoding="utf-8"))
    history = data.get("history", [])
    applied_keys = data.get("applied_keys", [])
    logger.info(f"Loaded {len(history)} history entries and {len(applied_keys)} applied keys.")

    added = 0

    # 1. Sync from history
    for item in history:
        status = item.get("status", "APPLIED")
        if status not in ("APPLIED", "DRY_RUN", "SUBMITTED", "DRY_RUN_COMPLETED"):
            continue
        portal = (item.get("portal") or "browser").lower()
        co_name = (item.get("company") or "Unknown Company")[:255]
        title = (item.get("title") or "Software Engineer")[:255]
        jid = str(item.get("job_id") or "")
        job_url = item.get("job_url") or f"https://{portal}.com/jobs/{jid}"
        ts_str = item.get("timestamp")
        created_at = datetime.utcnow()
        if ts_str:
            try:
                created_at = datetime.fromisoformat(ts_str.replace("Z", ""))
            except Exception:
                pass

        co = db.query(Company).filter(Company.name == co_name).first()
        if not co:
            co = Company(name=co_name)
            db.add(co)
            db.flush()

        job = db.query(Job).filter(Job.job_url == job_url).first()
        if not job:
            job = Job(
                company_id=co.id,
                title=title,
                job_url=job_url,
                status="APPLIED",
                match_score=85.0,
                created_at=created_at,
            )
            db.add(job)
            db.flush()

        app = db.query(Application).filter(Application.job_id == job.id).first()
        if not app:
            app = Application(
                job_id=job.id,
                application_method=portal.upper(),
                status=status,
                notes=f"Auto-applied via {portal.title()} Browser Agent",
                created_at=created_at,
            )
            db.add(app)
            added += 1

    # 2. Sync from applied_keys
    for k in applied_keys:
        parts = k.split("_", 2)
        if len(parts) >= 2:
            portal = parts[0].lower()
            if portal in ("linkedin", "ycombinator", "hirist", "cutshort", "indeed", "wellfound"):
                co_raw = parts[1].replace("-", " ")
                co_name = " ".join(w.capitalize() for w in co_raw.split())[:255] or f"{portal.title()} Employer"
                ti_raw = parts[2].replace("-", " ") if len(parts) > 2 else "Software Engineer"
                title = " ".join(w.capitalize() for w in ti_raw.split())[:255]
                job_url = f"https://{portal}.com/application/{k}"

                job = db.query(Job).filter(Job.job_url == job_url).first()
                if not job:
                    co = db.query(Company).filter(Company.name == co_name).first()
                    if not co:
                        co = Company(name=co_name)
                        db.add(co)
                        db.flush()

                    job = Job(
                        company_id=co.id,
                        title=title,
                        job_url=job_url,
                        status="APPLIED",
                        match_score=88.0,
                        created_at=datetime.utcnow(),
                    )
                    db.add(job)
                    db.flush()

                    app = Application(
                        job_id=job.id,
                        application_method=portal.upper(),
                        status="APPLIED",
                        notes=f"Applied via {portal.title()} Browser Agent",
                        created_at=datetime.utcnow(),
                    )
                    db.add(app)
                    added += 1

    db.commit()
    logger.info(f"Sync complete! Added {added} browser agent applications to DB. Total DB applications: {db.query(Application).count()}")

if __name__ == "__main__":
    sync()
