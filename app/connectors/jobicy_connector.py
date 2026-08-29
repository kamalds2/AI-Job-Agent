"""
Jobicy Connector — Fetches remote tech and backend engineering jobs from Jobicy API.

API Docs: https://jobicy.com/remote-jobs-api
Endpoint: https://jobicy.com/api/v2/remote-jobs
"""
import logging
from datetime import date
import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"


@register_connector
class JobicyConnector(BaseConnector):
    """Connector for Jobicy Remote Jobs API."""

    connector_name = "jobicy"

    async def fetch_jobs(self) -> list[dict]:
        """Fetch remote jobs matching query from Jobicy API."""
        try:
            params = {
                "count": 50,
                "industry": "engineering",
            }
            async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
                response = await client.get(JOBICY_API_URL, params=params)

            if response.status_code != 200:
                logger.warning(f"[Jobicy] API returned {response.status_code}")
                return []

            data = response.json()
            raw_jobs = data.get("jobs", [])
            logger.info(f"[Jobicy] Retrieved {len(raw_jobs)} remote jobs")
            return raw_jobs

        except Exception as e:
            logger.error(f"[Jobicy] Fetch failed: {e}")
            return []

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        """Convert raw items to JobData."""
        jobs = []
        for item in raw_jobs:
            title = item.get("jobTitle", "").strip()
            company = item.get("companyName", "").strip()
            job_url = item.get("url", "").strip()
            description = item.get("jobDescription") or item.get("jobExcerpt") or title
            location = item.get("jobGeo", "Remote")

            if title and job_url:
                jobs.append(
                    JobData(
                        title=title,
                        company=company,
                        location=location,
                        description=description,
                        job_url=job_url,
                        source="Jobicy",
                        remote=True,
                        posted_date=date.today(),
                    )
                )
        return jobs
