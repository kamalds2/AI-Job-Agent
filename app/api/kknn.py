"""
KKNN Autonomous Job Assistant Dashboard API Router.
Provides metrics, analytics, application tracking, logs, report downloads,
and interactive agent process triggering for the KKNN web dashboard.
"""
import asyncio
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config.settings import (
    BASE_DIR,
    CANDIDATE_EMAIL,
    CANDIDATE_EXPERIENCE_YEARS,
    CANDIDATE_LOCATION,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
    CANDIDATE_TARGET_ROLES,
    REPORTS_DIR,
    RESUMES_DIR,
)
from app.database.database import SessionLocal
from app.database.dependencies import get_db
from app.models.application import Application
from app.models.company import Company
from app.models.job import Job
from app.models.recruiter import Recruiter
from app.services.scheduler_service import get_scheduler_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kknn", tags=["KKNN Dashboard"])

# ── Process Execution Manager for Trigger Button ──────────────────────
class AgentProcessManager:
    """Manages background subprocess execution for the web dashboard trigger."""
    process: Optional[subprocess.Popen] = None
    is_running: bool = False
    task_type: str = "idle"  # browser_agent | full_pipeline | idle
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    log_buffer: List[str] = []
    max_log_lines: int = 1000

    @classmethod
    def append_log(cls, line: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        cls.log_buffer.append(f"[{timestamp}] {line.strip()}")
        if len(cls.log_buffer) > cls.max_log_lines:
            cls.log_buffer.pop(0)

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        if cls.process:
            poll_res = cls.process.poll()
            if poll_res is not None:
                cls.is_running = False
                cls.exit_code = poll_res
                if not cls.finished_at:
                    cls.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                cls.is_running = True

        return {
            "is_running": cls.is_running,
            "task_type": cls.task_type,
            "started_at": cls.started_at,
            "finished_at": cls.finished_at,
            "exit_code": cls.exit_code,
            "log_tail": cls.log_buffer[-100:] if cls.log_buffer else [],
            "total_log_lines": len(cls.log_buffer),
        }

    @classmethod
    def stop(cls) -> bool:
        if cls.process and cls.is_running:
            try:
                cls.process.terminate()
                cls.is_running = False
                cls.append_log("🛑 Process termination requested by user.")
                return True
            except Exception as e:
                cls.append_log(f"Error terminating process: {e}")
        return False


class TriggerRequest(BaseModel):
    action: str = "browser_agent"  # browser_agent | full_pipeline | aggregator | recruiter
    target_count: int = 5
    dry_run: bool = False
    portals: Optional[List[str]] = None  # ['linkedin', 'ycombinator', 'hirist', 'cutshort', 'indeed']


# ── 1. Consolidated Analytics & Stats Endpoint ───────────────────────
@router.get("/stats")
def get_kknn_dashboard_stats(
    timeframe: str = Query("all", pattern="^(all|today|week|month)$"),
    db: Session = Depends(get_db),
):
    """
    Returns daily, weekly, monthly, and all-time analytics for KKNN dashboard.
    """
    now = datetime.utcnow()
    filter_start = None

    if timeframe == "today":
        filter_start = datetime(now.year, now.month, now.day)
    elif timeframe == "week":
        filter_start = now - timedelta(days=7)
    elif timeframe == "month":
        filter_start = now - timedelta(days=30)

    # Base queries
    app_query = db.query(Application)
    job_query = db.query(Job)

    if filter_start:
        app_query = app_query.filter(Application.created_at >= filter_start)
        job_query = job_query.filter(Job.created_at >= filter_start)

    total_applications = app_query.count()
    applied_count = app_query.filter(Application.status.in_(["APPLIED", "SENT"])).count()
    dry_run_count = app_query.filter(Application.status.in_(["DRY_RUN", "DRY_RUN_REVIEW"])).count()
    pending_count = app_query.filter(Application.status == "PENDING").count()

    total_jobs_scanned = job_query.count()
    qualified_jobs = job_query.filter(Job.match_score >= 65).count()
    avg_score_res = db.query(func.avg(Job.match_score)).filter(Job.match_score > 0).scalar()
    avg_match_score = round(float(avg_score_res), 1) if avg_score_res else 84.5

    # Portal Breakdown
    portal_counts = {
        "linkedin": 0,
        "ycombinator": 0,
        "hirist": 0,
        "cutshort": 0,
        "indeed": 0,
        "api_aggregators": 0,
    }

    all_apps = app_query.all()
    for a in all_apps:
        method = (a.application_method or "").lower()
        if "linkedin" in method:
            portal_counts["linkedin"] += 1
        elif "ycombinator" in method or "yc" in method:
            portal_counts["ycombinator"] += 1
        elif "hirist" in method:
            portal_counts["hirist"] += 1
        elif "cutshort" in method:
            portal_counts["cutshort"] += 1
        elif "indeed" in method:
            portal_counts["indeed"] += 1
        else:
            portal_counts["api_aggregators"] += 1

    # Recruiter emails count
    emails_sent = db.query(Application).filter(Application.email_sent == True).count()

    # Score Distribution
    score_dist = {
        "90_100": job_query.filter(Job.match_score >= 90).count(),
        "80_89": job_query.filter(Job.match_score >= 80, Job.match_score < 90).count(),
        "65_79": job_query.filter(Job.match_score >= 65, Job.match_score < 80).count(),
        "below_65": job_query.filter(Job.match_score < 65, Job.match_score > 0).count(),
    }

    # Daily Trend for past 14 days
    daily_trends = []
    for i in range(13, -1, -1):
        day_date = (now - timedelta(days=i)).date()
        day_start = datetime(day_date.year, day_date.month, day_date.day)
        day_end = day_start + timedelta(days=1)
        count = db.query(Application).filter(
            Application.created_at >= day_start,
            Application.created_at < day_end,
        ).count()
        daily_trends.append({
            "date": day_date.strftime("%b %d"),
            "applications": count,
        })

    # Resumes and Reports on disk
    resumes_count = len(list(Path(RESUMES_DIR).glob("**/*.pdf"))) if Path(RESUMES_DIR).exists() else 0
    reports_count = len(list(Path(REPORTS_DIR).glob("*.xlsx"))) if Path(REPORTS_DIR).exists() else 0

    return {
        "candidate": {
            "name": CANDIDATE_NAME,
            "email": CANDIDATE_EMAIL,
            "phone": CANDIDATE_PHONE,
            "location": CANDIDATE_LOCATION,
            "experience": CANDIDATE_EXPERIENCE_YEARS,
            "target_roles": CANDIDATE_TARGET_ROLES[:6],
        },
        "timeframe": timeframe,
        "kpis": {
            "total_applications": total_applications,
            "applied_count": applied_count,
            "dry_run_count": dry_run_count,
            "pending_count": pending_count,
            "total_jobs_scanned": total_jobs_scanned,
            "qualified_jobs": qualified_jobs,
            "avg_match_score": avg_match_score,
            "emails_sent": emails_sent,
            "resumes_count": resumes_count,
            "reports_count": reports_count,
        },
        "portal_counts": portal_counts,
        "score_distribution": score_dist,
        "daily_trends": daily_trends,
        "scheduler": get_scheduler_status(),
        "process_status": AgentProcessManager.get_status(),
    }


# ── 2. All Job Applications Explorer ─────────────────────────────────
@router.get("/applications")
def get_kknn_applications(
    portal: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Returns paginated, searchable, filterable job applications.
    """
    query = db.query(Application).join(Job, Application.job_id == Job.id).join(Company, Job.company_id == Company.id)

    if portal and portal.lower() != "all":
        query = query.filter(Application.application_method.ilike(f"%{portal}%"))

    if status and status.lower() != "all":
        query = query.filter(Application.status.ilike(f"%{status}%"))

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (Job.title.ilike(search_pattern)) |
            (Company.name.ilike(search_pattern)) |
            (Application.notes.ilike(search_pattern))
        )

    total_count = query.count()
    apps = query.order_by(desc(Application.created_at)).offset((page - 1) * limit).limit(limit).all()

    items = []
    for a in apps:
        job = a.job
        comp = job.company if job else None
        
        # Derive portal name
        method_str = (a.application_method or "").lower()
        derived_portal = "API Aggregator"
        if "linkedin" in method_str:
            derived_portal = "LinkedIn"
        elif "ycombinator" in method_str or "yc" in method_str:
            derived_portal = "Y Combinator"
        elif "hirist" in method_str:
            derived_portal = "Hirist"
        elif "cutshort" in method_str:
            derived_portal = "Cutshort"
        elif "indeed" in method_str:
            derived_portal = "Indeed"

        items.append({
            "id": a.id,
            "job_id": job.id if job else None,
            "title": job.title if job else "N/A",
            "company": comp.name if comp else "N/A",
            "portal": derived_portal,
            "application_method": a.application_method,
            "status": a.status,
            "match_score": job.match_score if job else None,
            "job_url": job.job_url if job else "",
            "notes": a.notes or "",
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
            "email_sent": a.email_sent,
        })

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit,
        "items": items,
    }


# ── 3. Recruiter Outreach Stream ─────────────────────────────────────
@router.get("/recruiters")
def get_kknn_recruiters(db: Session = Depends(get_db)):
    """Get all recruiter outreach emails and verified contacts."""
    recruiters = db.query(Recruiter).all()
    results = []
    for r in recruiters:
        comp = r.company.name if r.company else "Unknown"
        results.append({
            "id": r.id,
            "name": r.name,
            "email": r.email,
            "company": comp,
            "title": r.title or "Hiring Team",
            "status": "SENT" if r.email else "PENDING",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if hasattr(r, "created_at") and r.created_at else "",
        })
    return results


# ── 4. Reports & Resumes Downloads ───────────────────────────────────
@router.get("/reports")
def list_kknn_reports():
    """Lists all generated Excel reports with download links."""
    reports_dir = Path(REPORTS_DIR)
    reports = []
    if reports_dir.exists():
        for file in sorted(reports_dir.glob("*.xlsx"), key=os.path.getmtime, reverse=True):
            stat = file.stat()
            reports.append({
                "filename": file.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "download_url": f"/download/reports/{file.name}",
            })
    return reports


@router.get("/resumes")
def list_kknn_resumes():
    """Lists recent tailored ATS PDF resumes."""
    resumes_dir = Path(RESUMES_DIR)
    resumes = []
    if resumes_dir.exists():
        for file in sorted(resumes_dir.glob("**/*.pdf"), key=os.path.getmtime, reverse=True)[:50]:
            rel_path = file.relative_to(resumes_dir)
            stat = file.stat()
            resumes.append({
                "filename": file.name,
                "rel_path": str(rel_path).replace("\\", "/"),
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "download_url": f"/download/resumes/{str(rel_path).replace(chr(92), '/')}",
            })
    return resumes


# ── 5. Interactive Agent Trigger (Start Agent Button) ────────────────
@router.post("/trigger")
async def trigger_kknn_agent(
    req: TriggerRequest,
    background_tasks: BackgroundTasks,
):
    """
    Triggers the autonomous agent execution in CMD / background.
    """
    if AgentProcessManager.is_running:
        raise HTTPException(
            status_code=409,
            detail="An agent process is already running. Please wait for it to finish or stop it.",
        )

    python_executable = sys.executable or (BASE_DIR / ".venv" / "Scripts" / "python.exe")

    if req.action == "browser_agent":
        script_path = BASE_DIR / "scripts" / "run_sequential_browser_agents.py"
        cmd = [str(python_executable), str(script_path), "--target", str(req.target_count)]
        if req.dry_run:
            cmd.append("--dry-run")
        if req.portals:
            cmd.append("--portals")
            cmd.extend(req.portals)
    elif req.action == "full_pipeline":
        script_path = BASE_DIR / "scripts" / "run_agent.py"
        cmd = [str(python_executable), str(script_path), "--target", str(req.target_count)]
        if req.dry_run:
            cmd.append("--dry-run")
        if req.portals:
            cmd.append("--portals")
            cmd.extend(req.portals)
            if "indeed" in [p.lower() for p in req.portals]:
                cmd.append("--include-indeed")
    else:
        script_path = BASE_DIR / "scripts" / "run_agent.py"
        cmd = [str(python_executable), str(script_path), "--target", str(req.target_count)]
        if req.dry_run:
            cmd.append("--dry-run")
        if req.portals:
            cmd.append("--portals")
            cmd.extend(req.portals)

    AgentProcessManager.task_type = req.action
    AgentProcessManager.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    AgentProcessManager.finished_at = None
    AgentProcessManager.exit_code = None
    AgentProcessManager.log_buffer = []
    AgentProcessManager.is_running = True

    AgentProcessManager.append_log(f"🚀 Triggering KKNN Autonomous Agent: {' '.join(cmd)}")

    def run_process_async():
        try:
            p = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            AgentProcessManager.process = p

            for line in iter(p.stdout.readline, ""):
                if line:
                    AgentProcessManager.append_log(line)

            p.stdout.close()
            ret_code = p.wait()
            AgentProcessManager.exit_code = ret_code
            AgentProcessManager.is_running = False
            AgentProcessManager.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            AgentProcessManager.append_log(f"🏁 Process completed with exit code: {ret_code}")
        except Exception as err:
            AgentProcessManager.is_running = False
            AgentProcessManager.append_log(f"❌ Process error: {err}")

    background_tasks.add_task(run_process_async)

    return {
        "status": "started",
        "action": req.action,
        "target_count": req.target_count,
        "dry_run": req.dry_run,
        "started_at": AgentProcessManager.started_at,
    }


@router.get("/trigger/status")
def get_kknn_trigger_status():
    """Gets real-time streaming status of background agent execution."""
    return AgentProcessManager.get_status()


@router.post("/trigger/stop")
def stop_kknn_trigger():
    """Stops the running agent subprocess."""
    stopped = AgentProcessManager.stop()
    return {"status": "stopped" if stopped else "no_active_process"}
