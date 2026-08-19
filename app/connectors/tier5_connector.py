"""
Tier 5 — Custom Company Career Page Scraper.

Directly scrapes career pages of high-value companies that don't use
standard ATS APIs (Greenhouse/Lever/Ashby).

Targets:
  Indian Tech Giants: Razorpay, CRED, Zepto, Meesho, PhonePe, Swiggy,
                      BrowserStack, MoEngage, Freshworks, Zoho
  Global (India offices): Amazon, Microsoft, Google, Uber, Meta
  ATS-specific: Workday-powered companies (Flipkart, Walmart, Infosys)
"""
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


# ── Target Company Definitions ─────────────────────────────────────────────

TIER5_COMPANIES: list[dict] = [
    # ── Indian Unicorns / Funded Startups ─────────────────────────
    {
        "name": "Razorpay",
        "url": "https://razorpay.com/jobs/",
        "type": "html",
        "selectors": {
            "container": ".job-listing, .career-item, [data-job], article.job",
            "title": "h2, h3, .job-title, .position-title",
            "location": ".location, .job-location",
            "link": "a",
        },
    },
    {
        "name": "CRED",
        "url": "https://careers.cred.club/",
        "type": "html",
        "selectors": {
            "container": ".open-position, .job-card, .career-row",
            "title": "h2, h3, .title",
            "location": ".location",
            "link": "a",
        },
    },
    {
        "name": "PhonePe",
        "url": "https://www.phonepe.com/en/careers.html",
        "type": "html",
        "selectors": {
            "container": ".job-item, .career-item, [class*='job']",
            "title": "h3, h4, .job-title",
            "location": ".location, .city",
            "link": "a",
        },
    },
    {
        "name": "Meesho",
        "url": "https://meesho.io/jobs/",
        "type": "html",
        "selectors": {
            "container": ".job-listing, .open-role",
            "title": "h2, h3",
            "location": ".location",
            "link": "a",
        },
    },
    {
        "name": "BrowserStack",
        "url": "https://www.browserstack.com/careers/open-positions",
        "type": "html",
        "selectors": {
            "container": ".job-item, .career-item, li[class*='job']",
            "title": "h3, h4, .job-title, a.job-link",
            "location": ".location, .job-location",
            "link": "a",
        },
    },
    {
        "name": "Freshworks",
        "url": "https://careers.freshworks.com/jobs",
        "type": "html",
        "selectors": {
            "container": ".job-listing, .position, [data-job-id]",
            "title": "h3, h4, .job-title",
            "location": ".location",
            "link": "a",
        },
    },
    {
        "name": "MoEngage",
        "url": "https://moengage.com/careers/",
        "type": "html",
        "selectors": {
            "container": ".job-post, .career-post, [class*='job-listing']",
            "title": "h2, h3, .job-title",
            "location": ".location",
            "link": "a",
        },
    },
    # ── Workday-powered companies (JSON API available) ─────────────
    {
        "name": "Flipkart",
        "url": (
            "https://flipkart.wd1.myworkdayjobs.com/wday/cxs/flipkart/"
            "Flipkart_Careers/jobs"
        ),
        "type": "workday_api",
        "keywords": ["engineer", "developer", "backend", "java", "python"],
    },
    {
        "name": "Walmart Labs India",
        "url": (
            "https://walmart.wd5.myworkdayjobs.com/wday/cxs/walmart/"
            "WalmartExternal/jobs"
        ),
        "type": "workday_api",
        "keywords": ["engineer", "backend", "java", "python", "cloud"],
    },
    # ── Global Companies with India Offices ────────────────────────
    {
        "name": "Uber Engineering",
        "url": "https://www.uber.com/us/en/careers/list/?location=india",
        "type": "html",
        "selectors": {
            "container": "[data-baseweb='card'], .job-card, li[role='listitem']",
            "title": "h3, [data-tracking-name], .job-title",
            "location": ".location, [class*='location']",
            "link": "a",
        },
    },
    {
        "name": "Zepto",
        "url": "https://www.zeptonow.com/careers",
        "type": "html",
        "selectors": {
            "container": ".job-card, .open-role, [class*='job']",
            "title": "h2, h3",
            "location": ".location",
            "link": "a",
        },
    },
    {
        "name": "Swiggy",
        "url": "https://careers.swiggy.com/#careers",
        "type": "html",
        "selectors": {
            "container": ".job-item, .lever-job-listing, [class*='job-listing']",
            "title": "h3, h4, .posting-name",
            "location": ".location, .posting-categories",
            "link": "a",
        },
    },
]

# Keywords relevant to Kamal's profile
TECH_FILTER_KEYWORDS = {
    "java", "spring", "python", "backend", "engineer", "developer",
    "software", "cloud", "aws", "microservice", "api", "platform",
    "fullstack", "full-stack", "devops", "infra", "ai", "ml",
    "data", "architect", "senior", "staff", "principal",
}


@register_connector
class Tier5Connector(BaseConnector):
    """
    Scrapes career pages of high-value companies not on standard ATS APIs.
    Uses BeautifulSoup for HTML pages and direct JSON for Workday APIs.
    """

    connector_name = "tier5_careers"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for company in TIER5_COMPANIES:
                try:
                    if company["type"] == "workday_api":
                        jobs = await self._fetch_workday(client, company)
                    else:
                        jobs = await self._fetch_html(client, company)

                    all_jobs.extend(jobs)
                    if jobs:
                        logger.info(f"[Tier5] {company['name']}: {len(jobs)} jobs")
                    else:
                        logger.debug(f"[Tier5] {company['name']}: no jobs found")

                except Exception as e:
                    logger.warning(f"[Tier5] {company['name']}: {e}")

        logger.info(f"[Tier5] Total: {len(all_jobs)} raw jobs")
        return all_jobs

    async def _fetch_html(self, client: httpx.AsyncClient, company: dict) -> list[dict]:
        """Parse career HTML page with BeautifulSoup."""
        try:
            resp = await client.get(
                company["url"],
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    )
                },
            )
            if resp.status_code != 200:
                logger.debug(f"[Tier5] {company['name']} HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            selectors = company.get("selectors", {})
            jobs: list[dict] = []

            # Try container selector
            containers = soup.select(selectors.get("container", ".job, [class*='job']"))

            if not containers:
                # Fallback: find all links with job-like text
                containers = self._fallback_find_jobs(soup, company["url"])
                return containers

            for container in containers[:50]:
                title_el = container.select_one(
                    selectors.get("title", "h2,h3,h4,.title")
                )
                link_el = container.select_one("a")
                loc_el = container.select_one(
                    selectors.get("location", ".location,.city")
                )

                title = title_el.get_text(strip=True) if title_el else ""
                href = link_el.get("href", "") if link_el else ""
                location = loc_el.get_text(strip=True) if loc_el else "India"

                if not title or not href:
                    continue

                # Build absolute URL
                if href.startswith("/"):
                    href = urljoin(company["url"], href)
                elif not href.startswith("http"):
                    href = urljoin(company["url"], "/" + href)

                # Tech relevance filter
                if not any(kw in title.lower() for kw in TECH_FILTER_KEYWORDS):
                    continue

                jobs.append({
                    "title": title,
                    "company": company["name"],
                    "location": location or "India",
                    "job_url": href,
                    "description": f"{title} at {company['name']}",
                    "source": "Tier5",
                })

            return jobs

        except Exception as e:
            logger.debug(f"[Tier5] HTML scrape error for {company['name']}: {e}")
            return []

    def _fallback_find_jobs(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Fallback: find <a> tags with job-like text."""
        jobs = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if (
                len(text) > 10
                and len(text) < 120
                and any(kw in text.lower() for kw in TECH_FILTER_KEYWORDS)
                and any(kw in href.lower() for kw in ["job", "career", "position", "role", "opening"])
            ):
                if href.startswith("/"):
                    href = urljoin(base_url, href)
                jobs.append({
                    "title": text,
                    "company": "Unknown",
                    "location": "India",
                    "job_url": href,
                    "description": text,
                    "source": "Tier5",
                })
        return jobs[:30]

    async def _fetch_workday(self, client: httpx.AsyncClient, company: dict) -> list[dict]:
        """
        Workday ATS has a public JSON API endpoint.
        POST to the jobs URL with search params.
        """
        keywords = company.get("keywords", ["engineer"])
        jobs: list[dict] = []

        for keyword in keywords[:3]:  # Limit API calls
            try:
                resp = await client.post(
                    company["url"],
                    json={
                        "appliedFacets": {},
                        "limit": 20,
                        "offset": 0,
                        "searchText": keyword,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for job in data.get("jobPostings", []):
                        title = job.get("title", "")
                        if not any(kw in title.lower() for kw in TECH_FILTER_KEYWORDS):
                            continue
                        ext_url = job.get("externalPath", "")
                        job_url = (
                            f"https://{company['url'].split('/')[2]}{ext_url}"
                            if ext_url else company["url"]
                        )
                        jobs.append({
                            "title": title,
                            "company": company["name"],
                            "location": job.get("locationsText", "India"),
                            "job_url": job_url,
                            "description": job.get("jobReqId", "") + " " + title,
                            "source": "Tier5-Workday",
                        })
            except Exception as e:
                logger.debug(f"[Tier5-Workday] {company['name']} keyword '{keyword}': {e}")

        return jobs

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []
        seen: set[str] = set()

        for raw in raw_jobs:
            url = raw.get("job_url", "")
            if not url or url in seen:
                continue
            seen.add(url)

            title = raw.get("title", "").strip()
            if not title:
                continue

            jobs.append(
                JobData(
                    title=title,
                    company=raw.get("company", "Unknown"),
                    location=raw.get("location", "India"),
                    remote="remote" in raw.get("location", "").lower(),
                    experience=None,
                    employment_type=None,
                    salary=None,
                    description=raw.get("description", title),
                    job_url=url,
                    source=raw.get("source", "Tier5"),
                    posted_date=date.today(),
                    skills=[],
                )
            )

        logger.info(f"[Tier5] Parsed {len(jobs)} jobs")
        return jobs
