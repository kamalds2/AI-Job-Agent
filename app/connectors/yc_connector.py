"""
Y Combinator Jobs Connector — scrapes YC's public job board.
URL: https://www.ycombinator.com/jobs
Uses their public API endpoint (no auth needed).
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class YCombinatorConnector(BaseConnector):

    connector_name = "ycombinator"

    # YC's public job API
    BASE_URL = "https://www.ycombinator.com/jobs/role/all/remote"
    API_URL = "https://api.ycombinator.com/v0.1/jobs"

    SEARCH_ROLES = ["engineer", "developer", "backend", "fullstack", "python", "java"]

    async def fetch_jobs(self) -> list[dict]:
        """Fetch jobs from YC public API."""
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            try:
                # Try their API first
                response = await client.get(
                    self.API_URL,
                    params={"page": 1, "per_page": 100, "remote": "true"},
                    headers={"User-Agent": "AI-Job-Agent/1.0"},
                )

                if response.status_code == 200:
                    data = response.json()
                    jobs = data if isinstance(data, list) else data.get("jobs", [])
                    all_jobs.extend(jobs)
                    logger.info(f"[YC] Fetched {len(jobs)} jobs from API")

            except Exception as e:
                logger.warning(f"[YC] API fetch failed: {e}, trying scrape fallback")
                all_jobs = await self._scrape_yc_jobs(client)

        return all_jobs

    async def _scrape_yc_jobs(self, client: httpx.AsyncClient) -> list[dict]:
        """Fallback: scrape YC jobs page."""
        from bs4 import BeautifulSoup

        jobs = []
        try:
            response = await client.get(
                "https://www.ycombinator.com/jobs",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            soup = BeautifulSoup(response.text, "html.parser")

            # Parse job listings from YC's HTML structure
            for card in soup.select("div[class*='JobCard']"):
                title_el = card.select_one("a[class*='title']") or card.select_one("h3")
                company_el = card.select_one("span[class*='company']") or card.select_one("span")
                link_el = card.select_one("a[href*='/jobs/']")

                if title_el and link_el:
                    url = link_el.get("href", "")
                    if url.startswith("/"):
                        url = f"https://www.ycombinator.com{url}"

                    jobs.append({
                        "title": title_el.get_text(strip=True),
                        "company": company_el.get_text(strip=True) if company_el else "YC Company",
                        "url": url,
                        "remote": True,
                    })

        except Exception as e:
            logger.error(f"[YC] Scrape failed: {e}")

        return jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []
        seen: set[str] = set()

        for job in raw_jobs:
            url = job.get("url") or job.get("apply_url") or job.get("job_url", "")
            if not url or url in seen:
                continue
            seen.add(url)

            # Parse date
            posted_date = None
            for date_key in ("created_at", "posted_at", "date"):
                if dt_str := job.get(date_key):
                    try:
                        posted_date = datetime.fromisoformat(dt_str[:10]).date()
                        break
                    except Exception:
                        pass

            # Extract company info
            company_info = job.get("company") or {}
            if isinstance(company_info, str):
                company_name = company_info
            else:
                company_name = company_info.get("name", "YC Company")

            jobs.append(
                JobData(
                    title=job.get("title", "").strip(),
                    company=company_name,
                    location=job.get("location") or "Remote",
                    remote=job.get("remote", True),
                    experience=None,
                    employment_type=job.get("employment_type"),
                    salary=None,
                    description=job.get("description", ""),
                    job_url=url,
                    source="YCombinator",
                    posted_date=posted_date,
                    skills=job.get("skills", []),
                )
            )

        logger.info(f"[YC] Parsed {len(jobs)} jobs")
        return jobs
