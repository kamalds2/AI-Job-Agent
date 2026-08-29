"""
Search Manager — orchestrates all registered connectors.

This is the central coordinator that runs all connectors concurrently,
collects JobData results, deduplicates, and saves to the database.
"""
import asyncio
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.connectors.registry import CONNECTORS
from app.models.job import Job
from app.repositories.job_repository import JobRepository
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


class SearchManager:
    """
    Runs all registered connectors concurrently.
    Architecture:
        SearchManager
            ├── RemoteOKConnector
            ├── WellfoundConnector
            ├── YCombinatorConnector
            ├── GreenhouseConnector (multi-company)
            ├── LeverConnector     (multi-company)
            ├── AshbyConnector     (multi-company)
            ├── WeWorkRemotelyConnector
            ├── RemotiveConnector
            └── HimalayasConnector
    """

    def __init__(self, db: Session):
        self.db = db
        self.job_repo = JobRepository(db)

    async def run_all(self) -> dict:
        """Run all connectors concurrently and save results."""

        # Import connectors so they self-register via @register_connector
        from app.connectors import (  # noqa: F401
            remoteok_connector,
            wellfound_connector,
            yc_connector,
            greenhouse_connector,
            lever_connector,
            ashby_connector,
            weworkremotely_connector,
            remotive_connector,
            himalayas_connector,
            naukri_connector,
            hirist_connector,
            tier5_connector,
            adzuna_connector,
            linkedin_posts_connector,
            jobicy_connector,
            agent_reach_connector,
        )

        logger.info(f"🔍 Starting search across {len(CONNECTORS)} connectors...")

        # Run all connectors concurrently
        tasks = []
        connector_names = []

        for name, connector_class in CONNECTORS.items():
            connector = connector_class()
            tasks.append(self._run_connector(name, connector))
            connector_names.append(name)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all jobs
        all_jobs: list[JobData] = []
        connector_stats: dict[str, int] = {}

        for name, result in zip(connector_names, results):
            if isinstance(result, Exception):
                logger.error(f"❌ Connector '{name}' failed: {result}")
                connector_stats[name] = 0
            else:
                connector_stats[name] = len(result)
                all_jobs.extend(result)
                logger.info(f"✅ '{name}': {len(result)} jobs")

        logger.info(f"📦 Total raw jobs fetched: {len(all_jobs)}")

        # Save to DB
        save_result = self._save_jobs(all_jobs)
        save_result["connector_stats"] = connector_stats
        save_result["total_raw"] = len(all_jobs)

        return save_result

    async def _run_connector(self, name: str, connector) -> list[JobData]:
        """Run a single connector's full pipeline with error handling."""
        try:
            logger.info(f"🔄 Running connector: {name}")
            return await connector.search_jobs()
        except Exception as e:
            logger.error(f"[{name}] Connector error: {e}")
            raise

    def _get_or_create_company(self, name: str) -> int | None:
        """Get or create a Company record, return its ID."""
        if not name or name == "Unknown":
            return None
        from app.models.company import Company
        company = self.db.query(Company).filter(Company.name == name[:255]).first()
        if not company:
            company = Company(name=name[:255])
            self.db.add(company)
            self.db.commit()
            self.db.refresh(company)
        return company.id

    def _save_jobs(self, jobs: list[JobData]) -> dict:
        """Deduplicate and save jobs to SQLite."""
        saved = 0
        skipped_dup = 0
        skipped_invalid = 0
        new_job_ids: list[int] = []

        for job in jobs:
            # Validate
            if not job.job_url or not job.title:
                skipped_invalid += 1
                continue

            # Deduplicate by URL
            if self.job_repo.exists(job.job_url):
                skipped_dup += 1
                continue

            try:
                # Create/get company record
                company_id = self._get_or_create_company(job.company or "Unknown")

                db_job = Job(
                    title=job.title[:255],
                    company_id=company_id,
                    location=job.location[:255] if job.location else "Remote",
                    remote=job.remote,
                    experience=job.experience,
                    employment_type=job.employment_type,
                    salary=str(job.salary)[:100] if job.salary else None,
                    description=job.description,
                    job_url=job.job_url[:1000],
                    posted_date=job.posted_date or date.today(),
                    status="NEW",
                    match_score=None,
                )
                created = self.job_repo.create(db_job)
                new_job_ids.append(created.id)
                saved += 1

            except Exception as e:
                logger.warning(f"Failed to save job '{job.title}': {e}")
                skipped_invalid += 1

        logger.info(
            f"💾 Saved: {saved} | Duplicates: {skipped_dup} | Invalid: {skipped_invalid}"
        )

        return {
            "saved": saved,
            "duplicates_skipped": skipped_dup,
            "invalid_skipped": skipped_invalid,
            "new_job_ids": new_job_ids,
        }