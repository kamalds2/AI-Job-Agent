"""
Hirist.tech Connector — India's premier tech-focused job portal.

Uses Hirist's internal search API (reverse-engineered from their web app).
Focuses on: Java, Python, Backend, Cloud, AI/ML, Full-stack tech roles.
API: GET https://www.hirist.tech/api/jobs/search
"""
import logging
from datetime import datetime, date

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

HIRIST_BASE_URL = "https://www.hirist.tech"
HIRIST_SEARCH_URL = f"{HIRIST_BASE_URL}/api/jobs/search"
HIRIST_ALT_URL = "https://api.hirist.com/api/v1/jobs"

HIRIST_QUERIES = [
    {"keyword": "Java Backend Developer",        "experience_min": 3, "experience_max": 10},
    {"keyword": "Spring Boot Microservices",      "experience_min": 3, "experience_max": 10},
    {"keyword": "Python Backend Engineer",        "experience_min": 3, "experience_max": 10},
    {"keyword": "AWS Cloud Engineer",             "experience_min": 3, "experience_max": 10},
    {"keyword": "AI Machine Learning Engineer",   "experience_min": 2, "experience_max": 8},
    {"keyword": "Senior Software Engineer Java",  "experience_min": 5, "experience_max": 12},
    {"keyword": "Full Stack Java React",          "experience_min": 3, "experience_max": 8},
    {"keyword": "DevOps Engineer Kubernetes",     "experience_min": 3, "experience_max": 8},
]

HIRIST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.hirist.tech/",
    "Origin": "https://www.hirist.tech",
}


@register_connector
class HiristConnector(BaseConnector):

    connector_name = "hirist"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for query in HIRIST_QUERIES:
                jobs = await self._fetch_query(client, query, seen_ids)
                all_jobs.extend(jobs)

        logger.info(f"[Hirist] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def _fetch_query(
        self,
        client: httpx.AsyncClient,
        query: dict,
        seen_ids: set,
    ) -> list[dict]:
        keyword = query["keyword"]
        new_jobs: list[dict] = []

        # Try multiple endpoint patterns Hirist might use
        endpoints = [
            {
                "url": HIRIST_SEARCH_URL,
                "params": {
                    "keyword": keyword,
                    "experience_min": query["experience_min"],
                    "experience_max": query["experience_max"],
                    "page": 1,
                    "limit": 20,
                },
            },
            {
                "url": f"{HIRIST_BASE_URL}/api/v1/jobs/search",
                "params": {
                    "q": keyword,
                    "exp_min": query["experience_min"],
                    "exp_max": query["experience_max"],
                },
            },
            {
                "url": f"{HIRIST_BASE_URL}/api/jobs",
                "params": {
                    "search": keyword,
                    "min_exp": query["experience_min"],
                    "max_exp": query["experience_max"],
                    "page": 1,
                },
            },
        ]

        for ep in endpoints:
            try:
                resp = await client.get(
                    ep["url"],
                    params=ep["params"],
                    headers=HIRIST_HEADERS,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Handle various response shapes
                    raw = (
                        data.get("data", {}).get("jobs", [])
                        or data.get("jobs", [])
                        or data.get("results", [])
                        or (data if isinstance(data, list) else [])
                    )
                    for job in raw:
                        jid = str(job.get("id") or job.get("job_id") or job.get("_id") or "")
                        if jid and jid not in seen_ids:
                            seen_ids.add(jid)
                            new_jobs.append(job)
                    if new_jobs:
                        logger.info(f"[Hirist] '{keyword}': {len(new_jobs)} jobs via {ep['url']}")
                        break
                elif resp.status_code == 404:
                    continue  # Try next endpoint pattern
                else:
                    logger.debug(f"[Hirist] '{keyword}': HTTP {resp.status_code} at {ep['url']}")
            except Exception as e:
                logger.debug(f"[Hirist] Endpoint {ep['url']} error: {e}")
                continue

        return new_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            try:
                title = (
                    job.get("title")
                    or job.get("job_title")
                    or job.get("designation")
                    or ""
                ).strip()

                company = (
                    job.get("company_name")
                    or job.get("company", {}).get("name", "")
                    if isinstance(job.get("company"), dict)
                    else job.get("company", "Unknown")
                ).strip()

                job_url = (
                    job.get("job_url")
                    or job.get("url")
                    or job.get("apply_url")
                    or ""
                )
                # Build hirist URL from slug/id if needed
                if not job_url:
                    slug = job.get("slug") or job.get("id") or ""
                    if slug:
                        job_url = f"{HIRIST_BASE_URL}/jobs/{slug}"

                if not title or not job_url:
                    continue

                # Location
                location = (
                    job.get("location")
                    or job.get("city")
                    or job.get("work_location")
                    or "India"
                )
                if isinstance(location, list):
                    location = ", ".join(location)

                # Experience
                exp_min = job.get("min_experience") or job.get("experience_min") or 0
                exp_max = job.get("max_experience") or job.get("experience_max") or ""
                experience = f"{exp_min}-{exp_max} years" if exp_max else f"{exp_min}+ years"

                # Salary
                salary_min = job.get("min_salary") or job.get("salary_min")
                salary_max = job.get("max_salary") or job.get("salary_max")
                salary = None
                if salary_min and salary_max:
                    salary = f"₹{salary_min}L - ₹{salary_max}L"
                elif salary_min:
                    salary = f"₹{salary_min}L+"

                # Skills
                skills_raw = job.get("skills") or job.get("key_skills") or []
                if isinstance(skills_raw, str):
                    skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
                else:
                    skills = [str(s) for s in skills_raw]

                # Description
                description = (
                    job.get("description")
                    or job.get("job_description")
                    or job.get("short_description")
                    or ""
                )

                # Date
                posted_date = None
                for date_field in ["created_at", "posted_at", "date_posted", "posted_date"]:
                    val = job.get(date_field)
                    if val:
                        try:
                            if isinstance(val, (int, float)):
                                posted_date = datetime.fromtimestamp(val / 1000).date()
                            else:
                                posted_date = datetime.fromisoformat(
                                    str(val).replace("Z", "+00:00")
                                ).date()
                            break
                        except Exception:
                            pass

                is_remote = "remote" in (location or "").lower() or job.get("is_remote", False)

                jobs.append(
                    JobData(
                        title=title,
                        company=company or "Unknown",
                        location=location,
                        remote=is_remote,
                        experience=experience,
                        employment_type=job.get("employment_type") or job.get("job_type"),
                        salary=salary,
                        description=description,
                        job_url=job_url,
                        source="Hirist",
                        posted_date=posted_date,
                        skills=skills,
                    )
                )
            except Exception as e:
                logger.warning(f"[Hirist] Parse error: {e}")

        logger.info(f"[Hirist] Parsed {len(jobs)} jobs")
        return jobs
