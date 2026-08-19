"""
RemoteOK Connector — fetches remote jobs from remoteok.com public API.
Docs: https://remoteok.com/api
"""
import asyncio
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class RemoteOKConnector(BaseConnector):

    connector_name = "remoteok"
    BASE_URL = "https://remoteok.com/api"

    async def fetch_jobs(self) -> list[dict]:
        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            response = await client.get(
                self.BASE_URL,
                headers={"User-Agent": "AI-Job-Agent/1.0 (job search automation)"},
            )
            response.raise_for_status()
            return response.json()

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        # First element is API metadata — skip it
        for job in raw_jobs[1:]:
            if not isinstance(job, dict):
                continue

            # Parse epoch timestamp
            posted_date = None
            if epoch := job.get("epoch"):
                try:
                    posted_date = datetime.utcfromtimestamp(int(epoch)).date()
                except Exception:
                    posted_date = datetime.utcnow().date()

            jobs.append(
                JobData(
                    title=job.get("position", "").strip(),
                    company=job.get("company", "").strip(),
                    location=job.get("location") or "Remote",
                    remote=True,
                    experience=None,
                    employment_type=None,
                    salary=str(job.get("salary_min", "")) or None,
                    description=job.get("description", ""),
                    job_url=job.get("url", ""),
                    source="RemoteOK",
                    posted_date=posted_date,
                    skills=job.get("tags", []),
                )
            )

        logger.info(f"[RemoteOK] Parsed {len(jobs)} jobs")
        return jobs
