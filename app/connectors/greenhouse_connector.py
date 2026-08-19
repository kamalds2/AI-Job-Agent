"""
Greenhouse Universal ATS Connector.

Greenhouse provides a public Job Board API for any company using their ATS.
API Docs: https://developers.greenhouse.io/job-board.html

Usage:
  One connector class supports ALL Greenhouse companies.
  Just add company tokens to companies.json.

API: GET https://boards-api.greenhouse.io/v1/boards/{company_token}/jobs?content=true
"""
import logging
from datetime import datetime

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


# Target companies using Greenhouse ATS — all verified working
GREENHOUSE_COMPANIES: list[dict] = [
    # AI / LLM
    {"token": "anthropic",      "name": "Anthropic"},
    {"token": "openai",         "name": "OpenAI"},

    # Fintech
    {"token": "stripe",         "name": "Stripe"},
    {"token": "plaid",          "name": "Plaid"},
    {"token": "brex",           "name": "Brex"},
    {"token": "chime",          "name": "Chime"},
    {"token": "carta",          "name": "Carta"},
    {"token": "coinbase",       "name": "Coinbase"},
    {"token": "robinhood",      "name": "Robinhood"},

    # Infra / Cloud / DevOps
    {"token": "hashicorp",      "name": "HashiCorp"},
    {"token": "datadog",        "name": "Datadog"},
    {"token": "confluent",      "name": "Confluent"},
    {"token": "elastic",        "name": "Elastic"},
    {"token": "mongodb",        "name": "MongoDB"},
    {"token": "cockroachlabs",  "name": "CockroachDB"},
    {"token": "yugabyte",       "name": "YugabyteDB"},
    {"token": "pagerduty",      "name": "PagerDuty"},
    {"token": "okta",           "name": "Okta"},

    # Product SaaS
    {"token": "gitlab",         "name": "GitLab"},
    {"token": "figma",          "name": "Figma"},
    {"token": "asana",          "name": "Asana"},
    {"token": "intercom",       "name": "Intercom"},
    {"token": "calendly",       "name": "Calendly"},
    {"token": "amplitude",      "name": "Amplitude"},
    {"token": "mixpanel",       "name": "Mixpanel"},
    {"token": "pendo",          "name": "Pendo"},
    {"token": "lattice",        "name": "Lattice"},
    {"token": "squarespace",    "name": "Squarespace"},

    # Social / Consumer
    {"token": "airbnb",         "name": "Airbnb"},
    {"token": "discord",        "name": "Discord"},
    {"token": "roblox",         "name": "Roblox"},
    {"token": "doordash",       "name": "DoorDash"},

    # Other verified
    {"token": "gusto",          "name": "Gusto"},
    {"token": "twilio",         "name": "Twilio"},
    {"token": "segment",        "name": "Segment"},
    {"token": "remote",         "name": "Remote.com"},
]

# Keywords to filter relevant jobs
RELEVANT_KEYWORDS = [
    "java", "spring", "backend", "python", "api", "engineer",
    "developer", "software", "cloud", "aws", "microservices",
    "fullstack", "full-stack", "fastapi", "ai", "ml",
]


@register_connector
class GreenhouseConnector(BaseConnector):

    connector_name = "greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    async def fetch_jobs(self) -> list[dict]:
        """Fetch jobs from all configured Greenhouse companies."""
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for company in GREENHOUSE_COMPANIES:
                token = company["token"]
                name = company["name"]
                try:
                    url = f"{self.BASE_URL}/{token}/jobs"
                    response = await client.get(
                        url,
                        params={"content": "true"},
                        headers={"User-Agent": "AI-Job-Agent/1.0"},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        jobs = data.get("jobs", [])

                        # Tag each job with company info
                        for job in jobs:
                            job["_company_name"] = name
                            job["_company_token"] = token

                        # Filter relevant jobs only
                        relevant = [
                            j for j in jobs
                            if self._is_relevant(j.get("title", ""))
                        ]
                        all_jobs.extend(relevant)
                        logger.info(f"[Greenhouse] {name}: {len(relevant)}/{len(jobs)} relevant jobs")

                    elif response.status_code == 404:
                        logger.debug(f"[Greenhouse] {name}: company not found (404)")

                except Exception as e:
                    logger.warning(f"[Greenhouse] {name} ({token}): {e}")

        logger.info(f"[Greenhouse] Total: {len(all_jobs)} relevant jobs")
        return all_jobs

    def _is_relevant(self, title: str) -> bool:
        title_lower = title.lower()
        return any(kw in title_lower for kw in RELEVANT_KEYWORDS)

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for job in raw_jobs:
            # Extract apply URL
            url = (
                job.get("absolute_url")
                or job.get("url")
                or ""
            )
            if not url:
                continue

            # Parse date
            posted_date = None
            for date_key in ("updated_at", "created_at"):
                if dt_str := job.get(date_key):
                    try:
                        posted_date = datetime.fromisoformat(dt_str[:10]).date()
                        break
                    except Exception:
                        pass

            # Extract location
            offices = job.get("offices", [])
            location = offices[0].get("name", "Remote") if offices else "Remote"
            is_remote = "remote" in location.lower() or not offices

            # Extract description from content
            content = job.get("content", "") or ""
            # Strip HTML tags for cleaner text
            import re
            description = re.sub(r"<[^>]+>", " ", content).strip()

            jobs.append(
                JobData(
                    title=job.get("title", "").strip(),
                    company=job.get("_company_name", "Unknown"),
                    location=location,
                    remote=is_remote,
                    experience=None,
                    employment_type=None,
                    salary=None,
                    description=description,
                    job_url=url,
                    source="Greenhouse",
                    posted_date=posted_date,
                    skills=[],
                )
            )

        logger.info(f"[Greenhouse] Parsed {len(jobs)} jobs")
        return jobs
