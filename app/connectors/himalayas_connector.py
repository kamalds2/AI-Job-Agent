"""
Himalayas.app Connector — Remote-first job board with public API.

API: GET https://himalayas.app/jobs/api
Docs: https://himalayas.app/api (public, no auth)
"""
import logging
from datetime import datetime, date

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

HIMALAYAS_BASE = "https://himalayas.app/jobs/api"

# Targeted queries for Kamal's profile
HIMALAYAS_QUERIES = [
    {"q": "java",         "limit": 50},
    {"q": "spring boot",  "limit": 50},
    {"q": "python backend","limit": 50},
    {"q": "aws engineer", "limit": 30},
    {"q": "backend",      "limit": 50},
]


@register_connector
class HimalayasConnector(BaseConnector):

    connector_name = "himalayas"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for query in HIMALAYAS_QUERIES:
                try:
                    r = await client.get(
                        HIMALAYAS_BASE,
                        params=query,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        jobs = data.get("jobs", [])
                        new = 0
                        for job in jobs:
                            jid = str(job.get("id") or job.get("slug") or "")
                            if jid and jid not in seen_ids:
                                seen_ids.add(jid)
                                all_jobs.append(job)
                                new += 1
                        logger.info(f"[Himalayas] '{query['q']}': {new} jobs")
                    else:
                        logger.warning(f"[Himalayas] '{query['q']}': HTTP {r.status_code}")
                except Exception as e:
                    logger.warning(f"[Himalayas] '{query['q']}': {e}")

        logger.info(f"[Himalayas] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            try:
                title = (job.get("title") or "").strip()
                company_data = job.get("company") or {}
                company = (
                    company_data.get("name")
                    if isinstance(company_data, dict)
                    else str(company_data)
                ) or "Unknown"

                job_url = job.get("url") or job.get("applyUrl") or ""
                if not job_url:
                    slug = job.get("slug", "")
                    if slug:
                        job_url = f"https://himalayas.app/jobs/{slug}"

                if not title or not job_url:
                    continue

                location = job.get("locationRestrictions") or job.get("location") or "Remote"
                if isinstance(location, list):
                    location = ", ".join(location)

                # Skills / categories
                categories = job.get("categories") or []
                skills = [c.get("name", "") if isinstance(c, dict) else str(c) for c in categories]

                # Date
                posted_date = None
                for field in ["publishedAt", "createdAt", "updated_at"]:
                    val = job.get(field)
                    if val:
                        try:
                            posted_date = datetime.fromisoformat(
                                str(val).replace("Z", "+00:00")
                            ).date()
                            break
                        except Exception:
                            pass

                jobs.append(
                    JobData(
                        title=title,
                        company=company,
                        location=location,
                        remote=True,  # Himalayas is remote-first
                        experience=None,
                        employment_type=job.get("type"),
                        salary=job.get("salary"),
                        description=job.get("description") or job.get("content") or "",
                        job_url=job_url,
                        source="Himalayas",
                        posted_date=posted_date or date.today(),
                        skills=skills,
                    )
                )
            except Exception as e:
                logger.warning(f"[Himalayas] Parse error: {e}")

        logger.info(f"[Himalayas] Parsed {len(jobs)} jobs")
        return jobs
