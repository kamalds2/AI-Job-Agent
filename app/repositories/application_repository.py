from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.application import Application
from app.repositories.base_repository import BaseRepository


class ApplicationRepository(BaseRepository[Application]):

    def __init__(self, db: Session):
        super().__init__(db, Application)

    def create_application(
        self,
        job_id: int,
        resume_id: Optional[int] = None,
        email_sent: bool = False,
        notes: Optional[str] = None,
    ) -> Application:
        app = Application(
            job_id=job_id,
            resume_id=resume_id,
            email_sent=email_sent,
            status="APPLIED" if email_sent else "PENDING",
            notes=notes,
            application_method="EMAIL" if email_sent else "MANUAL",
        )
        return self.create(app)

    def get_by_job(self, job_id: int) -> list[Application]:
        return (
            self.db.query(Application)
            .filter(Application.job_id == job_id)
            .all()
        )

    def get_pending(self) -> list[Application]:
        return (
            self.db.query(Application)
            .filter(Application.status == "PENDING")
            .all()
        )

    def get_today(self) -> list[Application]:
        from datetime import datetime
        start = datetime.utcnow().replace(hour=0, minute=0, second=0)
        return (
            self.db.query(Application)
            .filter(Application.created_at >= start)
            .all()
        )

    def mark_email_sent(self, app_id: int) -> Optional[Application]:
        app = self.get_by_id(app_id)
        if app:
            app.email_sent = True
            app.status = "APPLIED"
            self.db.commit()
            self.db.refresh(app)
        return app

    def get_stats(self) -> dict:
        total = self.db.query(Application).count()
        pending = self.db.query(Application).filter(Application.status == "PENDING").count()
        applied = self.db.query(Application).filter(Application.status == "APPLIED").count()
        return {"total": total, "pending": pending, "applied": applied}
