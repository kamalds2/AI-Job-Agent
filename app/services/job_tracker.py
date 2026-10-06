"""
Persistent Job Application & Email Tracker for Multi-Portal Job Agent.
Prevents duplicate applications and duplicate direct apply emails across runs.
Only blocks jobs that were ACTUALLY applied to or emailed to the candidate.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TRACKING_FILE = Path("data/applied_jobs.json")


class JobTracker:
    """Persistent tracker storing applied and emailed jobs."""

    @staticmethod
    def _normalize_key(portal: str, company: str, title: str) -> str:
        clean_p = (portal or "").lower().strip()
        clean_co = re.sub(r"[^\w]", "", (company or "").lower())
        clean_ti = re.sub(r"[^\w]", "", (title or "").lower())
        return f"{clean_p}_{clean_co}_{clean_ti}"

    @classmethod
    def load_data(cls) -> dict:
        if TRACKING_FILE.exists():
            try:
                with open(TRACKING_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Note loading tracking file: {e}")
        return {"applied_keys": [], "emailed_keys": [], "history": []}

    @classmethod
    def is_applied_or_emailed(cls, portal: str, company: str, title: str, job_id: str = "") -> bool:
        """Check if job was already applied or emailed. Does NOT block skipped/incomplete jobs."""
        data = cls.load_data()
        applied_set = set(data.get("applied_keys", []))
        emailed_set = set(data.get("emailed_keys", []))

        # Backward compatibility with legacy "keys"
        legacy_keys = set(data.get("keys", []))

        norm_key = cls._normalize_key(portal, company, title)
        short_key = f"{re.sub(r'[^\\w]', '', (company or '').lower())}_{re.sub(r'[^\\w]', '', (title or '').lower())}"
        jid_key = f"{portal}_{job_id}".lower() if job_id else ""

        for s in (applied_set, emailed_set):
            if norm_key in s or short_key in s:
                return True
            if jid_key and jid_key in s:
                return True

        return False

    @classmethod
    def is_processed(cls, portal: str, company: str, title: str, job_id: str = "") -> bool:
        """Alias for is_applied_or_emailed."""
        return cls.is_applied_or_emailed(portal, company, title, job_id)

    @classmethod
    def record_job(
        cls,
        portal: str,
        company: str,
        title: str,
        job_id: str = "",
        status: str = "APPLIED",
        job_url: str = "",
    ):
        """Record job in history, and add to deduplication keys ONLY if applied or emailed."""
        TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = cls.load_data()

        applied_keys = set(data.get("applied_keys", []))
        emailed_keys = set(data.get("emailed_keys", []))
        history = data.get("history", [])

        norm_key = cls._normalize_key(portal, company, title)
        jid_key = f"{portal}_{job_id}".lower() if job_id else ""

        # Only register permanent duplicate lock if actually APPLIED or EMAILED
        if status in ("APPLIED", "SUBMITTED", "DRY_RUN_COMPLETED"):
            applied_keys.add(norm_key)
            if jid_key:
                applied_keys.add(jid_key)
        elif status in ("EXTERNAL_LINK_EMAILED", "DIRECT_APPLY_EMAILED"):
            emailed_keys.add(norm_key)
            if jid_key:
                emailed_keys.add(jid_key)

        history.append({
            "portal": portal,
            "company": company,
            "title": title,
            "job_id": job_id,
            "status": status,
            "job_url": job_url,
            "timestamp": datetime.now().isoformat(),
        })

        try:
            with open(TRACKING_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "applied_keys": list(applied_keys),
                    "emailed_keys": list(emailed_keys),
                    "history": history[-1000:],
                }, f, indent=2)
            logger.info(f"💾 [JobTracker] Recorded '{title}' @ {company} [{status}]")
        except Exception as e:
            logger.warning(f"Could not update tracking file: {e}")

        # Also persist directly into SQLite database for dashboard metrics
        try:
            from app.database.database import SessionLocal
            from app.models.company import Company
            from app.models.job import Job
            from app.models.application import Application

            db = SessionLocal()
            co_name = (company or "Unknown Company")[:255]
            co = db.query(Company).filter(Company.name == co_name).first()
            if not co:
                co = Company(name=co_name)
                db.add(co)
                db.flush()

            clean_url = job_url or f"https://{portal}.com/jobs/{job_id}"
            job_obj = db.query(Job).filter(Job.job_url == clean_url).first()
            if not job_obj:
                job_obj = Job(
                    company_id=co.id,
                    title=(title or "Software Engineer")[:255],
                    job_url=clean_url,
                    status=status,
                    match_score=85.0,
                    created_at=datetime.utcnow(),
                )
                db.add(job_obj)
                db.flush()

            app_obj = db.query(Application).filter(Application.job_id == job_obj.id).first()
            if not app_obj:
                app_obj = Application(
                    job_id=job_obj.id,
                    application_method=(portal or "browser").upper(),
                    status=status,
                    notes=f"Applied via {(portal or 'browser').title()} Browser Agent",
                    created_at=datetime.utcnow(),
                )
                db.add(app_obj)
            else:
                app_obj.status = status
            db.commit()
            db.close()
        except Exception as dbe:
            logger.debug(f"[JobTracker] DB sync note: {dbe}")
