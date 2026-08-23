"""
Arbeitnow Connector — Free global job board API.

No authentication required. Returns 175 jobs per page across all categories.
API: GET https://www.arbeitnow.com/api/job-board-api

Used as a replacement for Hirist.tech which requires auth.
Focuses on remote-friendly tech roles globally.
"""
import logging
from datetime import datetime, date

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"

# Tech keywords to filter relevant jobs from the global feed
TECH_KEYWORDS = {
    "java", "spring", "python", "backend", "software", "engineer",
    "developer", "aws", "cloud", "microservice", "api", "platform",
    "fullstack", "full-stack", "devops", "infrastructure", "ai",
    "machine learning", "ml", "data", "architect", "senior", "staff",
    "golang", "kotlin", "scala", "fastapi", "django", "flask",
    "kubernetes", "docker", "terraform", "ci/cd", "sre",
}


@register_connector
class ArbeitnowConnector(BaseConnector):
    """
    Arbeitnow.com job board API — free, no auth, 175 jobs/page.
    Primarily remote-friendly global tech roles.
    """

    connector_name = "arbeitnow"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []
        seen_slugs: set[str] = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            # Fetch first 3 pages (525 max jobs)
            for page in range(1, 4):
                try:
                    r = await client.get(
                        ARBEITNOW_URL,
                        params={"page": page},
                    )
                    if r.status_code == 200:
                        data = r.json()
                        jobs = data.get("data", [])
                        if not jobs:
                            break  # No more pages

                        new = 0
                        for job in jobs:
                            slug = job.get("slug", "")
                            title = (job.get("title") or "").lower()

                            # Filter: only tech-relevant jobs
                            if not any(kw in title for kw in TECH_KEYWORDS):
                                continue

                            if slug and slug not in seen_slugs:
                                seen_slugs.add(slug)
                                all_jobs.append(job)
                                new += 1

                        logger.info(f"[Arbeitnow] Page {page}: {new} tech jobs")
                    else:
                        logger.warning(f"[Arbeitnow] HTTP {r.status_code}")
                        break
                except Exception as e:
                    logger.warning(f"[Arbeitnow] Page {page}: {e}")
                    break

        logger.info(f"[Arbeitnow] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            try:
                title = job.get("title", "").strip()
                company = job.get("company_name", "Unknown").strip()
                job_url = job.get("url", "")

                if not title or not job_url:
                    continue

                location = job.get("location") or "Remote"
                is_remote = job.get("remote", False)

                # Tags / skills
                tags = job.get("tags", []) or []
                job_types = job.get("job_types", []) or []
                skills = [str(t) for t in tags]

                # Employment type
                employment_type = ", ".join(str(j) for j in job_types) if job_types else None

                # Description
                description = job.get("description", "") or ""

                # Date
                posted_date = None
                if ts := job.get("created_at"):
                    try:
                        posted_date = datetime.fromtimestamp(int(ts)).date()
                    except Exception:
                        try:
                            posted_date = datetime.fromisoformat(
                                str(ts).replace("Z", "+00:00")
                            ).date()
                        except Exception:
                            pass

                jobs.append(
                    JobData(
                        title=title,
                        company=company,
                        location=location,
                        remote=is_remote,
                        experience=None,
                        employment_type=employment_type,
                        salary=None,
                        description=description[:3000],
                        job_url=job_url,
                        source="Arbeitnow",
                        posted_date=posted_date or date.today(),
                        skills=skills,
                    )
                )
            except Exception as e:
                logger.warning(f"[Arbeitnow] Parse error: {e}")

        logger.info(f"[Arbeitnow] Parsed {len(jobs)} jobs")
        return jobs
