"""
YCombinator Jobs Connector — via Hacker News Firebase API.

YC's old jobs.json endpoint is gone. We now use the HN Firebase API:
  - GET https://hacker-news.firebaseio.com/v0/jobstories.json  → list of job IDs
  - GET https://hacker-news.firebaseio.com/v0/item/{id}.json   → job details

Also scrapes the monthly "Who is Hiring?" HN threads for additional tech jobs.
No authentication required.
"""
import asyncio
import logging
import re
from datetime import datetime, date
from typing import Optional

import httpx

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData

logger = logging.getLogger(__name__)

HN_BASE = "https://hacker-news.firebaseio.com/v0"
HN_JOB_STORIES = f"{HN_BASE}/jobstories.json"
HN_ITEM = f"{HN_BASE}/item/{{}}.json"

# Tech keywords for filtering HN "Who is Hiring?" posts
TECH_KEYWORDS = {
    "java", "spring", "python", "backend", "engineer", "developer",
    "software", "cloud", "aws", "api", "microservices", "fullstack",
    "full-stack", "fastapi", "django", "flask", "kotlin", "scala",
    "golang", "rust", "typescript", "node", "devops", "sre",
    "machine learning", "ml", "ai", "data", "architect", "platform",
    "kubernetes", "docker", "terraform", "distributed",
}


@register_connector
class YCombinatorConnector(BaseConnector):

    connector_name = "ycombinator"

    async def fetch_jobs(self) -> list[dict]:
        all_jobs: list[dict] = []

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            # 1. YC Job Stories (official YC-funded startups hiring)
            yc_jobs = await self._fetch_yc_job_stories(client)
            all_jobs.extend(yc_jobs)

            # 2. Latest "Who is Hiring?" thread items (broader community)
            hn_jobs = await self._fetch_who_is_hiring(client)
            all_jobs.extend(hn_jobs)

        logger.info(f"[YC] Total: {len(all_jobs)} jobs")
        return all_jobs

    async def _fetch_yc_job_stories(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch official YC job posts from HN job board."""
        try:
            r = await client.get(HN_JOB_STORIES)
            if r.status_code != 200:
                return []

            job_ids = r.json()[:50]  # Latest 50 job posts
            logger.info(f"[YC] Fetching {len(job_ids)} HN job stories...")

            # Fetch all job details concurrently (batches of 10)
            jobs = []
            for i in range(0, len(job_ids), 10):
                batch = job_ids[i:i+10]
                tasks = [client.get(HN_ITEM.format(jid)) for jid in batch]
                try:
                    responses = await asyncio.gather(*tasks, return_exceptions=True)
                    for resp in responses:
                        if isinstance(resp, Exception):
                            continue
                        if resp.status_code == 200:
                            item = resp.json()
                            if item and item.get("type") == "job":
                                jobs.append({
                                    "_source": "hn_jobstories",
                                    **item,
                                })
                except Exception as e:
                    logger.debug(f"[YC] Batch fetch error: {e}")

            logger.info(f"[YC] HN job stories: {len(jobs)} fetched")
            return jobs

        except Exception as e:
            logger.warning(f"[YC] Job stories failed: {e}")
            return []

    async def _fetch_who_is_hiring(self, client: httpx.AsyncClient) -> list[dict]:
        """
        Find the current 'Ask HN: Who is hiring?' thread and parse top comments.
        These contain actual job listings from tech companies.
        """
        try:
            # Search for the monthly thread via Algolia HN search
            r = await client.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": "Ask HN: Who is hiring?",
                    "tags": "story,ask_hn",
                    "hitsPerPage": 3,
                },
            )
            if r.status_code != 200:
                return []

            hits = r.json().get("hits", [])
            if not hits:
                return []

            # Use the most recent thread
            thread_id = hits[0].get("objectID")
            if not thread_id:
                return []

            logger.info(f"[YC] Found 'Who is Hiring?' thread: {thread_id}")

            # Get top-level comments (job listings) via Algolia
            r2 = await client.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "tags": f"comment,story_{thread_id}",
                    "hitsPerPage": 100,
                },
            )
            if r2.status_code != 200:
                return []

            comments = r2.json().get("hits", [])
            jobs = []

            for comment in comments:
                text = comment.get("comment_text") or comment.get("text") or ""
                # Strip HTML
                text_clean = re.sub(r"<[^>]+>", " ", text).strip()

                # Skip if not tech-relevant
                text_lower = text_clean.lower()
                if not any(kw in text_lower for kw in TECH_KEYWORDS):
                    continue

                # Skip if too short (not a real job post)
                if len(text_clean) < 100:
                    continue

                jobs.append({
                    "_source": "hn_who_is_hiring",
                    "id": comment.get("objectID", ""),
                    "text": text_clean[:2000],
                    "by": comment.get("author", ""),
                    "time": comment.get("created_at_i"),
                    "url": f"https://news.ycombinator.com/item?id={comment.get('objectID', '')}",
                })

            logger.info(f"[YC] Who is Hiring? tech posts: {len(jobs)}")
            return jobs

        except Exception as e:
            logger.warning(f"[YC] Who is Hiring? failed: {e}")
            return []

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        jobs: list[JobData] = []

        for item in raw_jobs:
            try:
                source = item.get("_source", "")

                if source == "hn_jobstories":
                    job = self._parse_hn_job(item)
                elif source == "hn_who_is_hiring":
                    job = self._parse_who_is_hiring_post(item)
                else:
                    continue

                if job:
                    jobs.append(job)

            except Exception as e:
                logger.debug(f"[YC] Parse error: {e}")

        logger.info(f"[YC] Parsed {len(jobs)} jobs")
        return jobs

    def _parse_hn_job(self, item: dict) -> Optional[JobData]:
        """Parse an official HN job story."""
        title = (item.get("title") or "").strip()
        url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id', '')}"

        if not title:
            return None

        # Filter tech-relevant
        if not any(kw in title.lower() for kw in TECH_KEYWORDS):
            return None

        # Extract company from title (common format: "Company (YC XX) is hiring...")
        company = "YC Company"
        match = re.match(r"^([^(|–\-]+)", title)
        if match:
            company = match.group(1).strip()

        text = re.sub(r"<[^>]+>", " ", item.get("text") or "").strip()

        posted_date = None
        if ts := item.get("time"):
            try:
                posted_date = datetime.fromtimestamp(int(ts)).date()
            except Exception:
                pass

        return JobData(
            title=title,
            company=company,
            location="Remote / USA",
            remote=True,
            experience=None,
            employment_type="Full-time",
            salary=None,
            description=text[:2000],
            job_url=url,
            source="HackerNews",
            posted_date=posted_date or date.today(),
            skills=[],
        )

    def _parse_who_is_hiring_post(self, item: dict) -> Optional[JobData]:
        """Parse a comment from 'Who is Hiring?' thread."""
        text = item.get("text", "")
        url = item.get("url", "")
        if not text:
            return None

        # Try to extract job title from first line
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        first_line = lines[0] if lines else text[:100]

        # Common format: "Company | Role | Location | Remote | Salary"
        parts = re.split(r"\s*[\|·•]\s*", first_line)
        company = parts[0].strip() if parts else "Unknown"
        title = parts[1].strip() if len(parts) > 1 else "Software Engineer"

        # Check if role is tech-relevant
        if not any(kw in (title + " " + text[:200]).lower() for kw in TECH_KEYWORDS):
            return None

        # Detect remote
        is_remote = any(w in text.lower() for w in ["remote", "wfh", "anywhere"])

        # Detect location
        location = "Remote" if is_remote else "USA"
        for line in lines[:3]:
            if any(loc in line.lower() for loc in ["san francisco", "new york", "london", "bangalore", "india", "remote"]):
                location = line
                break

        posted_date = None
        if ts := item.get("time"):
            try:
                posted_date = datetime.fromtimestamp(int(ts)).date()
            except Exception:
                pass

        from app.utils.email_validator import extract_emails_from_text
        emails = extract_emails_from_text(text)
        email_str = f"\n\nDirect Contact Emails: {', '.join(emails)}" if emails else ""
        clean_desc = f"{text[:2000]}{email_str}"

        return JobData(
            title=title[:120],
            company=company[:100],
            location=location,
            remote=is_remote,
            experience=None,
            employment_type=None,
            salary=None,
            description=clean_desc,
            job_url=url or f"https://news.ycombinator.com/item?id={item.get('id')}",
            source="HN-WhoIsHiring",
            posted_date=posted_date or date.today(),
            skills=[],
        )
