"""
Ashby Universal ATS Connector.

Ashby is popular among tech startups and provides a public job board API.
API: GET https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true

Add companies to ASHBY_COMPANIES list.
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


ASHBY_COMPANIES: list[dict] = [
    {"token": "linear", "name": "Linear"},
    {"token": "retool", "name": "Retool"},
    {"token": "rippling", "name": "Rippling"},
    {"token": "ramp", "name": "Ramp"},
    {"token": "brex", "name": "Brex"},
    {"token": "scale-ai", "name": "Scale AI"},
    {"token": "cohere", "name": "Cohere"},
    {"token": "mistral", "name": "Mistral AI"},
    {"token": "runway", "name": "Runway ML"},
    {"token": "replit", "name": "Replit"},
    {"token": "dbt-labs", "name": "dbt Labs"},
    {"token": "airbyte", "name": "Airbyte"},
    {"token": "prefect", "name": "Prefect"},
    {"token": "modal", "name": "Modal Labs"},
    {"token": "baseten", "name": "Baseten"},
]

RELEVANT_KEYWORDS = [
    "java", "spring", "backend", "python", "api", "engineer",
    "developer", "software", "cloud", "aws", "microservices",
    "fullstack", "full-stack", "fastapi", "ai", "ml", "platform",
    "infra", "infrastructure", "data",
]


@register_connector
class AshbyConnector(BaseConnector):

    connector_name = "ashby"
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for company in ASHBY_COMPANIES:
                token = company["token"]
                name = company["name"]
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/{token}",
                        params={"includeCompensation": "true"},
                        headers={"User-Agent": "AI-Job-Agent/1.0"},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        jobs = data.get("jobs", []) if isinstance(data, dict) else data

                        for job in jobs:
                            job["_company_name"] = name

                        relevant = [
                            j for j in jobs
                            if self._is_relevant(j.get("title", ""))
                        ]
                        all_jobs.extend(relevant)
                        logger.info(f"[Ashby] {name}: {len(relevant)}/{len(jobs)} relevant")

                    elif response.status_code == 404:
                        logger.debug(f"[Ashby] {name}: not found (404)")

                except Exception as e:
                    logger.warning(f"[Ashby] {name} ({token}): {e}")

        logger.info(f"[Ashby] Total: {len(all_jobs)} jobs")
        return all_jobs

    def _is_relevant(self, title: str) -> bool:
        title_lower = title.lower()
        return any(kw in title_lower for kw in RELEVANT_KEYWORDS)

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        import re
        jobs: list[JobData] = []

        for job in raw_jobs:
            # Ashby provides a job board URL
            job_id = job.get("id", "")
            company_token = job.get("_company_name", "unknown").lower().replace(" ", "-")
            url = job.get("jobUrl") or f"https://jobs.ashbyhq.com/{company_token}/{job_id}"

            if not url:
                continue

            # Date
            posted_date = None
            if pub_at := job.get("publishedDate") or job.get("updatedAt"):
                try:
                    posted_date = datetime.fromisoformat(pub_at[:10]).date()
                except Exception:
                    pass

            # Location
            location_list = job.get("locationName") or job.get("location") or "Remote"

            # Compensation
            comp = job.get("compensation") or {}
            salary = None
            if comp:
                min_c = comp.get("minValue")
                max_c = comp.get("maxValue")
                currency = comp.get("currency", "USD")
                if min_c and max_c:
                    salary = f"{currency} {min_c:,} - {max_c:,}"

            # Description
            desc = job.get("descriptionHtml") or job.get("descriptionSafeHtml") or ""
            description = re.sub(r"<[^>]+>", " ", desc).strip()

            is_remote = (
                job.get("isRemote", False)
                or "remote" in location_list.lower()
            )

            jobs.append(
                JobData(
                    title=job.get("title", "").strip(),
                    company=job.get("_company_name", "Unknown"),
                    location=location_list,
                    remote=is_remote,
                    experience=None,
                    employment_type=job.get("employmentType"),
                    salary=salary,
                    description=description,
                    job_url=url,
                    source="Ashby",
                    posted_date=posted_date,
                    skills=[],
                )
            )

        logger.info(f"[Ashby] Parsed {len(jobs)} jobs")
        return jobs
