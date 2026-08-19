"""
Naukri.com Connector — India's largest job portal.

Uses Naukri's internal job search API (reverse-engineered from their web app).
Targets: Java, Spring Boot, Python, AWS, Backend Engineer roles.
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

NAUKRI_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"

# Search queries for Kamal's target roles
NAUKRI_QUERIES = [
    {"q": "Java Backend Developer", "exp": "3,8"},
    {"q": "Spring Boot Microservices", "exp": "3,8"},
    {"q": "Python Backend Engineer", "exp": "3,8"},
    {"q": "AWS Cloud Engineer", "exp": "3,8"},
    {"q": "Senior Software Engineer Java", "exp": "5,10"},
    {"q": "AI Java Developer", "exp": "3,8"},
]

NAUKRI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.naukri.com/",
    "appid": "109",
    "systemid": "109",
}


@register_connector
class NaukriConnector(BaseConnector):

    connector_name = "naukri"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for query_params in NAUKRI_QUERIES:
                try:
                    params = {
                        "noOfResults": 20,
                        "urlType": "search_by_keyword",
                        "searchType": "adv",
                        "keyword": query_params["q"],
                        "jobAge": 7,  # Posted in last 7 days
                        "experience": query_params.get("exp", "3,8"),
                        "location": "",
                        "k": query_params["q"],
                        "seoKey": "jobs",
                        "src": "jobsearchDesk",
                        "latLong": "",
                    }

                    response = await client.get(
                        NAUKRI_SEARCH_URL,
                        params=params,
                        headers=NAUKRI_HEADERS,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        jobs = data.get("jobDetails", [])
                        new_jobs = []
                        for job in jobs:
                            job_id = str(job.get("jobId", ""))
                            if job_id and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                new_jobs.append(job)
                        all_jobs.extend(new_jobs)
                        logger.info(f"[Naukri] '{query_params['q']}': {len(new_jobs)} jobs")
                    else:
                        logger.warning(f"[Naukri] '{query_params['q']}': HTTP {response.status_code}")

                except Exception as e:
                    logger.warning(f"[Naukri] Query '{query_params['q']}': {e}")

        logger.info(f"[Naukri] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            try:
                job_id = job.get("jobId", "")
                title = job.get("title", "").strip()
                company = job.get("companyName", "Unknown").strip()

                # Build URL
                job_url = job.get("jdURL") or f"https://www.naukri.com/job-listings-{job_id}"

                if not job_url or not title:
                    continue

                # Date
                posted_date = None
                if ts := job.get("createdDate"):
                    try:
                        posted_date = datetime.fromtimestamp(int(ts) / 1000).date()
                    except Exception:
                        pass

                # Location
                placeholders = job.get("placeholders", [])
                location = "India"
                for p in placeholders:
                    if p.get("type") == "location":
                        location = p.get("label", "India")
                        break

                # Salary
                salary = None
                for p in placeholders:
                    if p.get("type") == "salary":
                        salary = p.get("label")
                        break

                # Experience
                experience = None
                for p in placeholders:
                    if p.get("type") == "experience":
                        experience = p.get("label")
                        break

                # Skills from tags
                tags = job.get("tagsAndSkills", "") or ""
                skills = [s.strip() for s in tags.split(",") if s.strip()]

                description = job.get("jobDescription", "") or ""

                is_remote = "remote" in location.lower() or "work from home" in location.lower()

                jobs.append(
                    JobData(
                        title=title,
                        company=company,
                        location=location,
                        remote=is_remote,
                        experience=experience,
                        employment_type=None,
                        salary=salary,
                        description=description,
                        job_url=job_url,
                        source="Naukri",
                        posted_date=posted_date,
                        skills=skills,
                    )
                )
            except Exception as e:
                logger.warning(f"[Naukri] Parse error: {e}")

        logger.info(f"[Naukri] Parsed {len(jobs)} jobs")
        return jobs
