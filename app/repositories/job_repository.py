from datetime import date

from sqlalchemy.orm import Session

from app.models.job import Job
from app.repositories.base_repository import BaseRepository


class JobRepository(BaseRepository[Job]):

    def __init__(self, db: Session):
        super().__init__(db, Job)

    def get_by_url(self, job_url: str):
        return (
            self.db.query(Job)
            .filter(Job.job_url == job_url)
            .first()
        )

    def exists(self, job_url: str) -> bool:
        return self.get_by_url(job_url) is not None

    def get_today_jobs(self):
        today = date.today()

        return (
            self.db.query(Job)
            .filter(Job.posted_date == today)
            .all()
        )

    def get_new_jobs(self):
        return (
            self.db.query(Job)
            .filter(Job.status == "NEW")
            .all()
        )

    def mark_applied(self, job_id: int):

        job = self.get_by_id(job_id)

        if job:

            job.status = "APPLIED"

            self.db.commit()

            self.db.refresh(job)

        return job