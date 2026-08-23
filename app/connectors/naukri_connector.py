"""
Naukri.com Connector — India's largest job portal.

Strategy: Naukri blocks direct API calls with reCAPTCHA.
We use their mobile API endpoint which has lighter bot protection,
combined with proper session/cookie handling.

Fallback: If API still blocked, scrape the search results page HTML.
"""
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

# Target role searches for Kamal's profile
NAUKRI_SEARCHES = [
    {"keyword": "java backend developer",        "exp_min": 3, "exp_max": 8},
    {"keyword": "spring boot microservices",      "exp_min": 3, "exp_max": 8},
    {"keyword": "python backend engineer",        "exp_min": 3, "exp_max": 8},
    {"keyword": "aws cloud engineer india",       "exp_min": 3, "exp_max": 8},
    {"keyword": "senior software engineer java",  "exp_min": 5, "exp_max": 12},
    {"keyword": "ai java developer",              "exp_min": 2, "exp_max": 8},
]

NAUKRI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "appid": "109",
    "systemid": "Naukri",
}


@register_connector
class NaukriConnector(BaseConnector):

    connector_name = "naukri"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            # Get session cookies first
            try:
                await client.get(
                    "https://www.naukri.com/",
                    headers={"User-Agent": NAUKRI_HEADERS["User-Agent"]},
                )
            except Exception:
                pass

            for search in NAUKRI_SEARCHES:
                jobs = await self._fetch_search(client, search, seen_ids)
                all_jobs.extend(jobs)

        logger.info(f"[Naukri] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def _fetch_search(
        self,
        client: httpx.AsyncClient,
        search: dict,
        seen_ids: set,
    ) -> list[dict]:
        keyword = search["keyword"]
        keyword_slug = keyword.replace(" ", "-")
        new_jobs: list[dict] = []

        # Attempt 1: Naukri v3 API with session
        try:
            r = await client.get(
                "https://www.naukri.com/jobapi/v3/search",
                params={
                    "noOfResults": 20,
                    "urlType": "search_by_keyword",
                    "searchType": "adv",
                    "keyword": keyword,
                    "jobAge": 15,
                    "experience": f"{search['exp_min']},{search['exp_max']}",
                    "src": "jobsearchDesk",
                },
                headers=NAUKRI_HEADERS,
            )
            if r.status_code == 200:
                data = r.json()
                for job in data.get("jobDetails", []):
                    jid = str(job.get("jobId", ""))
                    if jid and jid not in seen_ids:
                        seen_ids.add(jid)
                        new_jobs.append(job)
                logger.info(f"[Naukri] API '{keyword}': {len(new_jobs)} jobs")
                return new_jobs
        except Exception as e:
            logger.debug(f"[Naukri] API attempt failed: {e}")

        # Attempt 2: Scrape search results HTML
        try:
            url = (
                f"https://www.naukri.com/{keyword_slug}-jobs"
                f"?experience={search['exp_min']}&to={search['exp_max']}"
            )
            r = await client.get(
                url,
                headers={
                    "User-Agent": NAUKRI_HEADERS["User-Agent"],
                    "Accept": "text/html",
                },
            )
            if r.status_code == 200 and "jobTuple" in r.text:
                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select("article.jobTuple, .jobTupleHeader")
                for card in cards[:20]:
                    title_el = card.select_one(".title, .jobTitle, h2 a")
                    company_el = card.select_one(".companyName, .company-name")
                    loc_el = card.select_one(".location, .locWdth")
                    link_el = card.select_one("a.title, a.jobTitle, h2 a")

                    title = title_el.get_text(strip=True) if title_el else ""
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    location = loc_el.get_text(strip=True) if loc_el else "India"
                    href = link_el.get("href", "") if link_el else ""

                    if title and href:
                        uid = href.split("-")[-1].replace(".htm", "")
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            new_jobs.append({
                                "title": title,
                                "companyName": company,
                                "placeholders": [{"type": "location", "label": location}],
                                "jdURL": href if href.startswith("http") else f"https://www.naukri.com{href}",
                                "jobDescription": f"{title} at {company} - {location}",
                                "tagsAndSkills": keyword,
                            })
                logger.info(f"[Naukri] HTML '{keyword}': {len(new_jobs)} jobs")
        except Exception as e:
            logger.debug(f"[Naukri] HTML scrape failed: {e}")

        return new_jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            try:
                title = (
                    job.get("title")
                    or job.get("jobTitle")
                    or ""
                ).strip()
                company = job.get("companyName", "Unknown").strip()
                job_url = job.get("jdURL") or job.get("url") or ""

                if not title or not job_url:
                    continue

                # Location from placeholders or direct field
                location = "India"
                for ph in job.get("placeholders", []):
                    if ph.get("type") == "location":
                        location = ph.get("label", "India")
                        break
                if not location:
                    location = job.get("location", "India")

                # Salary
                salary = None
                for ph in job.get("placeholders", []):
                    if ph.get("type") == "salary":
                        salary = ph.get("label")
                        break

                # Experience
                experience = None
                for ph in job.get("placeholders", []):
                    if ph.get("type") == "experience":
                        experience = ph.get("label")
                        break

                # Skills
                tags = job.get("tagsAndSkills", "") or ""
                skills = [s.strip() for s in tags.split(",") if s.strip()]

                description = job.get("jobDescription", "") or ""
                is_remote = "remote" in location.lower() or "work from home" in location.lower()

                # Date
                posted_date = None
                if ts := job.get("createdDate"):
                    try:
                        posted_date = datetime.fromtimestamp(int(ts) / 1000).date()
                    except Exception:
                        pass

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
