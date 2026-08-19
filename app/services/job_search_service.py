from sqlalchemy.orm import Session

from app.connectors.remoteok_connector import RemoteOKConnector
from app.parsers.remoteok_parser import RemoteOKParser
from app.repositories.job_repository import JobRepository
from app.models.job import Job


class SearchService:

    def __init__(self, db: Session):
        self.db = db
        self.job_repository = JobRepository(db)

        # RemoteOK components
        self.connector = RemoteOKConnector()
        self.parser = RemoteOKParser()

    def save_jobs(self, jobs):
        """
        Save parsed jobs into the database while avoiding duplicates.
        """

        saved = 0
        skipped = 0

        for job in jobs:

            if not job.job_url:
                skipped += 1
                continue

            if self.job_repository.exists(job.job_url):
                skipped += 1
                continue

            db_job = Job(
                title=job.title,
                location=job.location,
                remote=job.remote,
                experience=job.experience,
                employment_type=job.employment_type,
                salary=str(job.salary) if job.salary is not None else None,
                description=job.description,
                job_url=job.job_url,
                posted_date=job.posted_date,
                status="NEW"
            )

            self.job_repository.create(db_job)

            saved += 1

        return {
            "saved": saved,
            "duplicates": skipped,
            "total": len(jobs),
        }

    def search_remoteok(self):
        """
        Fetch jobs from RemoteOK,
        parse them,
        and save them into the database.
        """

        raw_jobs = self.connector.fetch_jobs()

        jobs = self.parser.parse_jobs(raw_jobs)

        result = self.save_jobs(jobs)

        return result