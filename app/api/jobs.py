"""
Jobs API — enhanced with search, scoring, stats endpoints.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.repositories.job_repository import JobRepository

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/")
def get_all_jobs(
    status: Optional[str] = Query(None, description="Filter by status: NEW, APPLIED, SKIPPED"),
    min_score: Optional[float] = Query(None, description="Minimum match score"),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    """Get all jobs with optional filters."""
    repo = JobRepository(db)
    from app.models.job import Job

    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status.upper())
    if min_score is not None:
        query = query.filter(Job.match_score >= min_score)

    return query.order_by(Job.match_score.desc().nullslast()).limit(limit).all()


@router.get("/new")
def get_new_jobs(db: Session = Depends(get_db)):
    """Get unscored new jobs."""
    return JobRepository(db).get_new_jobs()


@router.get("/today")
def get_today_jobs(db: Session = Depends(get_db)):
    """Get jobs posted/added today."""
    return JobRepository(db).get_today_jobs()


@router.get("/qualified")
def get_qualified_jobs(
    threshold: float = Query(65, description="Minimum match score"),
    db: Session = Depends(get_db),
):
    """Get jobs above the match score threshold."""
    from app.models.job import Job
    return (
        db.query(Job)
        .filter(Job.match_score >= threshold)
        .order_by(Job.match_score.desc())
        .all()
    )


@router.get("/stats")
def get_job_stats(db: Session = Depends(get_db)):
    """Get job statistics summary."""
    from app.models.job import Job
    from sqlalchemy import func

    db_session = db
    total = db_session.query(Job).count()
    new = db_session.query(Job).filter(Job.status == "NEW").count()
    applied = db_session.query(Job).filter(Job.status == "APPLIED").count()
    skipped = db_session.query(Job).filter(Job.status == "SKIPPED").count()
    avg_score = db_session.query(func.avg(Job.match_score)).scalar()
    qualified = db_session.query(Job).filter(Job.match_score >= 65).count()

    return {
        "total": total,
        "new": new,
        "applied": applied,
        "skipped": skipped,
        "qualified": qualified,
        "avg_match_score": round(float(avg_score), 1) if avg_score else None,
    }


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get a specific job by ID."""
    return JobRepository(db).get_by_id(job_id)


@router.post("/{job_id}/mark-applied")
def mark_job_applied(job_id: int, db: Session = Depends(get_db)):
    """Manually mark a job as applied."""
    return JobRepository(db).mark_applied(job_id)