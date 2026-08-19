"""
Wellfound (AngelList) Connector — scrapes startup + remote jobs.
Uses their public GraphQL API (no auth required for basic listings).
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class WellfoundConnector(BaseConnector):

    connector_name = "wellfound"

    # Wellfound public job search API endpoint
    BASE_URL = "https://wellfound.com/graphql"

    GRAPHQL_QUERY = """
    query JobSearchResults($query: String!, $remote: Boolean) {
      jobListings(query: $query, remote: $remote, first: 50) {
        edges {
          node {
            id
            title
            description
            applyUrl
            remote
            jobType
            compensation
            minYearsExp
            slug
            createdAt
            startup {
              name
              location
            }
            skills {
              name
            }
          }
        }
      }
    }
    """

    SEARCH_TERMS = [
        "Java Developer",
        "Spring Boot",
        "Backend Engineer",
        "Python Developer",
        "AI Engineer",
    ]

    async def fetch_jobs(self) -> list[dict]:
        """Fetch jobs via Wellfound GraphQL API."""
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for term in self.SEARCH_TERMS:
                try:
                    response = await client.post(
                        self.BASE_URL,
                        json={
                            "query": self.GRAPHQL_QUERY,
                            "variables": {"query": term, "remote": True},
                        },
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0",
                        },
                    )

                    if response.status_code == 200:
                        data = response.json()
                        edges = (
                            data.get("data", {})
                            .get("jobListings", {})
                            .get("edges", [])
                        )
                        all_jobs.extend([e["node"] for e in edges if "node" in e])

                except Exception as e:
                    logger.warning(f"[Wellfound] Search '{term}' failed: {e}")

        logger.info(f"[Wellfound] Fetched {len(all_jobs)} raw jobs")
        return all_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []
        seen_urls: set[str] = set()

        for job in raw_jobs:
            url = job.get("applyUrl") or f"https://wellfound.com/jobs/{job.get('slug', '')}"

            if url in seen_urls or not url:
                continue
            seen_urls.add(url)

            # Parse date
            posted_date = None
            if created := job.get("createdAt"):
                try:
                    posted_date = datetime.fromisoformat(created[:10]).date()
                except Exception:
                    pass

            startup = job.get("startup") or {}
            skills = [s["name"] for s in job.get("skills", []) if "name" in s]

            jobs.append(
                JobData(
                    title=job.get("title", "").strip(),
                    company=startup.get("name", "Unknown"),
                    location=startup.get("location") or "Remote",
                    remote=job.get("remote", True),
                    experience=f"{job.get('minYearsExp', '')} years" if job.get("minYearsExp") else None,
                    employment_type=job.get("jobType"),
                    salary=job.get("compensation"),
                    description=job.get("description", ""),
                    job_url=url,
                    source="Wellfound",
                    posted_date=posted_date,
                    skills=skills,
                )
            )

        logger.info(f"[Wellfound] Parsed {len(jobs)} unique jobs")
        return jobs
