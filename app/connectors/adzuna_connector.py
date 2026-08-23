"""
Adzuna India Connector — Free job search API with India coverage.

Sign up FREE at: https://developer.adzuna.com/admin/applications
Free tier: 250 API calls/day, no credit card required.

API: GET https://api.adzuna.com/v1/api/jobs/in/search/{page}
     ?app_id=YOUR_APP_ID&app_key=YOUR_APP_KEY&what=java+backend&where=India

Set in .env:
  ADZUNA_APP_ID=your_app_id
  ADZUNA_APP_KEY=your_app_key

If keys not set, connector is skipped gracefully (no error).
"""
import logging
import os
from datetime import datetime, date

import httpx
from dotenv import load_dotenv

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

load_dotenv()

logger = logging.getLogger(__name__)

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/in/search"

# Targeted queries for Kamal's profile
ADZUNA_QUERIES = [
    {"what": "java backend developer",       "where": "India"},
    {"what": "spring boot microservices",    "where": "India"},
    {"what": "python backend engineer",      "where": "India"},
    {"what": "aws cloud engineer",           "where": "India"},
    {"what": "senior software engineer java","where": "India"},
    {"what": "ai machine learning engineer", "where": "India"},
    {"what": "java remote",                  "where": ""},     # Remote worldwide
    {"what": "backend engineer remote",      "where": ""},
]


@register_connector
class AdzunaConnector(BaseConnector):

    connector_name = "adzuna"

    async def fetch_jobs(self) -> list[dict]:
        if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
            logger.info(
                "[Adzuna] Skipping — ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env. "
                "Get free keys at: https://developer.adzuna.com/admin/applications"
            )
            return []

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for query in ADZUNA_QUERIES:
                try:
                    params = {
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_APP_KEY,
                        "results_per_page": 20,
                        "what": query["what"],
                        "content-type": "application/json",
                        "max_days_old": 14,
                        "sort_by": "date",
                    }
                    if query.get("where"):
                        params["where"] = query["where"]

                    r = await client.get(f"{ADZUNA_BASE}/1", params=params)

                    if r.status_code == 200:
                        data = r.json()
                        results = data.get("results", [])
                        new = 0
                        for job in results:
                            jid = str(job.get("id", ""))
                            if jid and jid not in seen_ids:
                                seen_ids.add(jid)
                                all_jobs.append(job)
                                new += 1
                        logger.info(f"[Adzuna] '{query['what']}': {new} jobs")
                    elif r.status_code == 401:
                        logger.error("[Adzuna] Invalid API credentials — check ADZUNA_APP_ID/KEY in .env")
                        break
                    else:
                        logger.warning(f"[Adzuna] '{query['what']}': HTTP {r.status_code}")

                except Exception as e:
                    logger.warning(f"[Adzuna] '{query['what']}': {e}")

        logger.info(f"[Adzuna] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            try:
                title = (job.get("title") or "").strip()
                company = (
                    job.get("company", {}).get("display_name", "Unknown")
                    if isinstance(job.get("company"), dict)
                    else str(job.get("company") or "Unknown")
                ).strip()

                job_url = job.get("redirect_url") or job.get("adref") or ""
                if not title or not job_url:
                    continue

                location_data = job.get("location", {})
                location = (
                    location_data.get("display_name", "India")
                    if isinstance(location_data, dict)
                    else str(location_data or "India")
                )

                # Salary
                salary = None
                sal_min = job.get("salary_min")
                sal_max = job.get("salary_max")
                if sal_min and sal_max:
                    salary = f"₹{int(sal_min):,} - ₹{int(sal_max):,}"
                elif sal_min:
                    salary = f"₹{int(sal_min):,}+"

                # Date
                posted_date = None
                if created := job.get("created"):
                    try:
                        posted_date = datetime.fromisoformat(
                            str(created).replace("Z", "+00:00")
                        ).date()
                    except Exception:
                        pass

                description = job.get("description") or ""
                is_remote = "remote" in (title + " " + description).lower()

                # Category / skills
                cat = job.get("category", {})
                category_label = cat.get("label", "") if isinstance(cat, dict) else ""
                skills = [category_label] if category_label else []

                jobs.append(
                    JobData(
                        title=title,
                        company=company,
                        location=location,
                        remote=is_remote,
                        experience=None,
                        employment_type=job.get("contract_type"),
                        salary=salary,
                        description=description[:2000],
                        job_url=job_url,
                        source="Adzuna",
                        posted_date=posted_date or date.today(),
                        skills=skills,
                    )
                )
            except Exception as e:
                logger.warning(f"[Adzuna] Parse error: {e}")

        logger.info(f"[Adzuna] Parsed {len(jobs)} jobs")
        return jobs
