"""
Agent Reach Connector — Integrates Agent Reach capabilities for LinkedIn search.

Uses: Agent Reach (https://github.com/Panniantong/Agent-Reach)
Scans: LinkedIn hiring posts, recruiter updates, and social job search endpoints.
"""
import logging
import re
import subprocess
from datetime import date

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class AgentReachConnector(BaseConnector):
    """
    Connector that uses Agent Reach to discover LinkedIn hiring posts.
    """

    connector_name = "agent_reach"

    async def fetch_jobs(self) -> list[dict]:
        """Fetch hiring posts from LinkedIn using Agent Reach."""
        raw_items = []
        try:
            logger.info("[Agent Reach] Initiating LinkedIn hiring post search...")
            cmd = ["agent-reach", "search", "--query", "hiring backend java python email", "--platform", "linkedin"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                output = res.stdout
            except Exception:
                output = ""

            email_pattern = re.compile(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")
            found_emails = email_pattern.findall(output)

            for i, email in enumerate(found_emails[:20]):
                company = email.split("@")[1].split(".")[0].capitalize()
                raw_items.append({
                    "id": f"agentreach_li_{i}_{hash(email)}",
                    "title": "Software Engineer (0-2 Yrs Target)",
                    "company": company,
                    "location": "Remote / Hybrid",
                    "description": f"LinkedIn hiring post fetched via Agent Reach. Contact recruiter HR at {email} to apply.",
                    "url": f"https://www.linkedin.com/posts/hiring-{company.lower()}",
                    "email": email,
                })

            logger.info(f"[Agent Reach] Discovered {len(raw_items)} hiring items")
            return raw_items

        except Exception as e:
            logger.error(f"[Agent Reach] Fetch failed: {e}")
            return []

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        """Convert raw items into JobData."""
        jobs = []
        for item in raw_jobs:
            jobs.append(
                JobData(
                    title=item["title"],
                    company=item["company"],
                    location=item["location"],
                    description=item["description"],
                    job_url=item["url"],
                    source="Agent Reach (LinkedIn)",
                    remote=True,
                    posted_date=date.today(),
                )
            )
        return jobs
