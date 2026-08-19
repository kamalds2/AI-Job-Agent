"""
Himalayas Connector — fetches remote tech jobs from Himalayas.app.
Uses their public API: https://himalayas.app/jobs/api
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class HimalayasConnector(BaseConnector):

    connector_name = "himalayas"
    BASE_URL = "https://himalayas.app/jobs/api"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            try:
                response = await client.get(
                    self.BASE_URL,
                    params={"limit": 100},
                    headers={"User-Agent": "AI-Job-Agent/1.0"},
                )
                response.raise_for_status()
                data = response.json()
                jobs = data.get("jobs", []) if isinstance(data, dict) else data
                all_jobs.extend(jobs)
                logger.info(f"[Himalayas] Fetched {len(jobs)} jobs")
            except Exception as e:
                logger.warning(f"[Himalayas] Fetch failed: {e}")

        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        import re
        jobs: list[JobData] = []
        seen: set[str] = set()

        for job in raw_jobs:
            url = job.get("url") or job.get("applyUrl") or ""
            if not url or url in seen:
                continue
            seen.add(url)

            # Date
            posted_date = None
            for key in ("publishedAt", "createdAt", "postedAt"):
                if dt := job.get(key):
                    try:
                        posted_date = datetime.fromisoformat(dt[:10]).date()
                        break
                    except Exception:
                        pass

            # Salary
            salary = None
            if sal := job.get("salary"):
                salary = str(sal)

            desc = re.sub(r"<[^>]+>", " ", job.get("description") or "").strip()

            # Company
            company_info = job.get("company") or {}
            company_name = (
                company_info.get("name")
                if isinstance(company_info, dict)
                else str(company_info)
            ) or "Unknown"

            jobs.append(
                JobData(
                    title=job.get("title", "").strip(),
                    company=company_name,
                    location="Remote",
                    remote=True,
                    experience=None,
                    employment_type=job.get("type"),
                    salary=salary,
                    description=desc,
                    job_url=url,
                    source="Himalayas",
                    posted_date=posted_date,
                    skills=job.get("skills", []),
                )
            )

        logger.info(f"[Himalayas] Parsed {len(jobs)} jobs")
        return jobs
