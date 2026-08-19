"""
Remotive Connector — fetches remote tech jobs from Remotive's public API.
API Docs: https://remotive.com/api/remote-jobs
Free, no auth required.
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class RemotiveConnector(BaseConnector):

    connector_name = "remotive"
    BASE_URL = "https://remotive.com/api/remote-jobs"

    CATEGORIES = [
        "software-dev",
        "devops",
        "data",
    ]

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for category in self.CATEGORIES:
                try:
                    response = await client.get(
                        self.BASE_URL,
                        params={"category": category, "limit": 100},
                        headers={"User-Agent": "AI-Job-Agent/1.0"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    jobs = data.get("jobs", [])
                    all_jobs.extend(jobs)
                    logger.info(f"[Remotive] Category '{category}': {len(jobs)} jobs")
                except Exception as e:
                    logger.warning(f"[Remotive] Category '{category}' failed: {e}")

        logger.info(f"[Remotive] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        import re
        jobs: list[JobData] = []
        seen: set[str] = set()

        for job in raw_jobs:
            url = job.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)

            # Parse ISO date
            posted_date = None
            if pub := job.get("publication_date"):
                try:
                    posted_date = datetime.fromisoformat(pub[:10]).date()
                except Exception:
                    pass

            desc = re.sub(r"<[^>]+>", " ", job.get("description", "")).strip()
            salary_str = job.get("salary") or None
            tags = job.get("tags", [])

            jobs.append(
                JobData(
                    title=job.get("title", "").strip(),
                    company=job.get("company_name", "Unknown"),
                    location=job.get("candidate_required_location") or "Remote",
                    remote=True,
                    experience=None,
                    employment_type=job.get("job_type"),
                    salary=salary_str,
                    description=desc,
                    job_url=url,
                    source="Remotive",
                    posted_date=posted_date,
                    skills=tags,
                )
            )

        logger.info(f"[Remotive] Parsed {len(jobs)} jobs")
        return jobs
