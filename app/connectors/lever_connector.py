"""
Lever Universal ATS Connector.

Lever provides a public job listing API for any company using their ATS.
API: GET https://api.lever.co/v0/postings/{company}?mode=json

Add companies to LEVER_COMPANIES list.
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


# Companies using Lever ATS (verified working with api.lever.co/v0)
# To find more: check jobs.lever.co/{company} in browser
LEVER_COMPANIES: list[dict] = [
    {"token": "pipedrive", "name": "Pipedrive"},
    {"token": "bazaarvoice", "name": "Bazaarvoice"},
    {"token": "wealthsimple", "name": "Wealthsimple"},
    {"token": "15five", "name": "15Five"},
    # Add more verified tokens below as you find them
    # Format: go to https://jobs.lever.co/<company> and check URL
]

RELEVANT_KEYWORDS = [
    "java", "spring", "backend", "python", "api", "engineer",
    "developer", "software", "cloud", "aws", "microservices",
    "fullstack", "full-stack", "fastapi", "ai", "ml", "platform",
]


@register_connector
class LeverConnector(BaseConnector):

    connector_name = "lever"
    BASE_URL = "https://api.lever.co/v0/postings"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for company in LEVER_COMPANIES:
                token = company["token"]
                name = company["name"]
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/{token}",
                        params={"mode": "json", "limit": 100},
                        headers={"User-Agent": "AI-Job-Agent/1.0"},
                    )

                    if response.status_code == 200:
                        jobs: list[dict] = response.json()

                        for job in jobs:
                            job["_company_name"] = name

                        relevant = [
                            j for j in jobs
                            if self._is_relevant(j.get("text", "") or j.get("title", ""))
                        ]
                        all_jobs.extend(relevant)
                        logger.info(f"[Lever] {name}: {len(relevant)}/{len(jobs)} relevant")

                    elif response.status_code == 404:
                        logger.debug(f"[Lever] {name}: not found (404)")

                except Exception as e:
                    logger.warning(f"[Lever] {name} ({token}): {e}")

        logger.info(f"[Lever] Total: {len(all_jobs)} jobs")
        return all_jobs

    def _is_relevant(self, title: str) -> bool:
        title_lower = title.lower()
        return any(kw in title_lower for kw in RELEVANT_KEYWORDS)

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        import re
        jobs: list[JobData] = []

        for job in raw_jobs:
            url = job.get("hostedUrl") or job.get("applyUrl") or ""
            if not url:
                continue

            # Parse date — Lever uses millisecond epoch
            posted_date = None
            if created_at := job.get("createdAt"):
                try:
                    posted_date = datetime.utcfromtimestamp(int(created_at) / 1000).date()
                except Exception:
                    pass

            # Location
            categories = job.get("categories", {})
            location = categories.get("location") or "Remote"
            commitment = categories.get("commitment", "")

            # Description
            description_list = job.get("descriptionPlain") or job.get("description") or ""
            description = re.sub(r"<[^>]+>", " ", description_list).strip()

            # Remote check
            is_remote = (
                "remote" in location.lower()
                or "remote" in commitment.lower()
            )

            jobs.append(
                JobData(
                    title=job.get("text", "").strip(),
                    company=job.get("_company_name", "Unknown"),
                    location=location,
                    remote=is_remote,
                    experience=None,
                    employment_type=commitment or None,
                    salary=None,
                    description=description,
                    job_url=url,
                    source="Lever",
                    posted_date=posted_date,
                    skills=[],
                )
            )

        logger.info(f"[Lever] Parsed {len(jobs)} jobs")
        return jobs
