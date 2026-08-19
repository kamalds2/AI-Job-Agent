"""
Applications API — view and manage job applications.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.repositories.application_repository import ApplicationRepository

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.get("/")
def get_all_applications(db: Session = Depends(get_db)):
    """Get all job applications."""
    repo = ApplicationRepository(db)
    return repo.get_all()


@router.get("/stats")
def get_application_stats(db: Session = Depends(get_db)):
    """Get application statistics."""
    repo = ApplicationRepository(db)
    return repo.get_stats()


@router.get("/pending")
def get_pending_applications(db: Session = Depends(get_db)):
    """Get applications waiting to be sent."""
    repo = ApplicationRepository(db)
    return repo.get_pending()


@router.get("/today")
def get_today_applications(db: Session = Depends(get_db)):
    """Get today's applications."""
    repo = ApplicationRepository(db)
    return repo.get_today()


@router.get("/{app_id}")
def get_application(app_id: int, db: Session = Depends(get_db)):
    """Get a specific application by ID."""
    repo = ApplicationRepository(db)
    return repo.get_by_id(app_id)
