"""
We Work Remotely Connector — scrapes WWR's public RSS feeds.
RSS is a reliable, lightweight way to fetch jobs without scraping HTML.
Feeds: https://weworkremotely.com/remote-jobs.rss
"""
import logging
from datetime import datetime
from xml.etree import ElementTree as ET

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)


@register_connector
class WeWorkRemotelyConnector(BaseConnector):

    connector_name = "weworkremotely"

    # RSS feeds — Programming, DevOps/SysAdmin, Full-Stack
    RSS_FEEDS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    ]

    async def fetch_jobs(self) -> list[dict]:
        all_items: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            for feed_url in self.RSS_FEEDS:
                try:
                    response = await client.get(
                        feed_url,
                        headers={"User-Agent": "AI-Job-Agent/1.0"},
                    )
                    response.raise_for_status()

                    items = self._parse_rss(response.text)
                    all_items.extend(items)
                    logger.info(f"[WWR] Feed {feed_url.split('/')[-1]}: {len(items)} items")

                except Exception as e:
                    logger.warning(f"[WWR] Feed failed {feed_url}: {e}")

        logger.info(f"[WWR] Total: {len(all_items)} items")
        return all_items

    def _parse_rss(self, xml_text: str) -> list[dict]:
        items = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"media": "http://search.yahoo.com/mrss/"}

            channel = root.find("channel")
            if channel is None:
                return items

            for item in channel.findall("item"):
                def text(tag: str) -> str:
                    el = item.find(tag)
                    return (el.text or "").strip() if el is not None else ""

                items.append({
                    "title": text("title"),
                    "company": text("author") or "Unknown",
                    "url": text("link") or text("guid"),
                    "description": text("description"),
                    "pubDate": text("pubDate"),
                    "category": text("category"),
                })
        except ET.ParseError as e:
            logger.error(f"[WWR] RSS parse error: {e}")
        return items

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        import re
        jobs: list[JobData] = []
        seen: set[str] = set()

        for job in raw_jobs:
            url = job.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)

            # Parse RFC 2822 date
            posted_date = None
            if pub := job.get("pubDate"):
                try:
                    from email.utils import parsedate_to_datetime
                    posted_date = parsedate_to_datetime(pub).date()
                except Exception:
                    pass

            # Extract company from title (format: "Company: Title")
            title = job.get("title", "")
            company = "Unknown"
            if ": " in title:
                parts = title.split(": ", 1)
                company = parts[0].strip()
                title = parts[1].strip()
            elif " - " in title:
                parts = title.split(" - ", 1)
                company = parts[0].strip()
                title = parts[1].strip()

            desc = re.sub(r"<[^>]+>", " ", job.get("description", "")).strip()

            jobs.append(
                JobData(
                    title=title,
                    company=company,
                    location="Remote",
                    remote=True,
                    experience=None,
                    employment_type=None,
                    salary=None,
                    description=desc,
                    job_url=url,
                    source="WeWorkRemotely",
                    posted_date=posted_date,
                    skills=[],
                )
            )

        logger.info(f"[WWR] Parsed {len(jobs)} jobs")
        return jobs
