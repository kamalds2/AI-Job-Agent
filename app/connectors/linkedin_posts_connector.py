"""
LinkedIn Hiring Posts Connector.
Searches and extracts daily LinkedIn hiring posts from recruiters and founders
hiring for 0-2 years Java / Python / Backend / AI developer roles with direct contact emails.

Extracts:
  - Role title & requirements from post text
  - Company name
  - Recruiter / HR direct email address (hr@, careers@, recruiter@)
  - Post URL for direct engagement
"""
import asyncio
import logging
import re
from datetime import datetime, date
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.connectors.base_connector import BaseConnector
from app.connectors.registry import register_connector
from app.schemas.job_data import JobData
from app.utils.email_validator import extract_emails_from_text

logger = logging.getLogger(__name__)

# Search queries designed to find hiring posts with direct email IDs for 0-2 years
SEARCH_QUERIES = [
    '"hiring" "Java" "email" "0-2 years" site:linkedin.com/posts',
    '"hiring" "Spring Boot" "resume" site:linkedin.com/posts',
    '"hiring" "Backend Developer" "send your resume" "India" site:linkedin.com/posts',
    '"hiring" "Python" "FastAPI" ("0-2" OR "junior" OR "fresher") site:linkedin.com/posts',
    '"hiring" "AI Engineer" ("email" OR "send CV") site:linkedin.com/posts',
    '"hiring" ("Junior Software Engineer" OR "Associate Software Engineer") "Java" site:linkedin.com/posts',
]


@register_connector
class LinkedInPostsConnector(BaseConnector):
    """
    Scrapes & parses public LinkedIn hiring posts where recruiters/founders
    post job openings and ask candidates to email their resumes directly.
    """
    connector_name = "linkedin_posts"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def _fetch_public_posts_search(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> list[dict]:
        """Fetch public LinkedIn post search results via search feed."""
        posts: list[dict] = []
        encoded_query = quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        try:
            resp = await client.get(search_url, headers=self.headers, timeout=12.0)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.find_all("div", class_="result")

            for res in results[:8]:
                title_elem = res.find("a", class_="result__url") or res.find("a", class_="result__snippet")
                snippet_elem = res.find("a", class_="result__snippet")
                link_elem = res.find("a", class_="result__url")

                raw_url = link_elem.get("href", "") if link_elem else ""
                # Clean duckduckgo redirect URL
                if "uddg=" in raw_url:
                    from urllib.parse import unquote
                    raw_url = unquote(raw_url.split("uddg=")[1].split("&")[0])

                if not raw_url or "linkedin.com/posts" not in raw_url:
                    continue

                snippet_text = snippet_elem.get_text().strip() if snippet_elem else ""
                title_text = res.find("h2").get_text().strip() if res.find("h2") else ""

                combined_text = f"{title_text}\n{snippet_text}"
                emails = extract_emails_from_text(combined_text)

                posts.append({
                    "url": raw_url,
                    "title": title_text,
                    "content": combined_text,
                    "emails": emails,
                })

        except Exception as e:
            logger.debug(f"[LinkedIn Posts] Search error for '{query[:30]}': {e}")

        return posts

    def _extract_company_from_post(self, post_title: str, post_content: str) -> str:
        """Extract company name or recruiter organization from post text."""
        # e.g., "John Doe on LinkedIn: We are hiring Java Developers at TechCorp"
        m = re.search(r"at\s+([A-Za-z0-9\s&]{2,25})", post_content, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in {"least", "present", "our", "a", "an", "the"}:
                return candidate.title()

        # Check title before 'on LinkedIn'
        if "on LinkedIn" in post_title:
            author = post_title.split("on LinkedIn")[0].strip()
            return f"{author} (LinkedIn)"

        return "Hiring Recruiter (LinkedIn)"

    def _extract_role_title(self, post_content: str) -> str:
        """Extract suitable role title from post content."""
        content_lower = post_content.lower()
        if "junior java" in content_lower or "java developer" in content_lower:
            return "Java Developer (0-2 Yrs)"
        elif "spring boot" in content_lower:
            return "Spring Boot Backend Developer"
        elif "python" in content_lower and "fastapi" in content_lower:
            return "Python / FastAPI Developer"
        elif "backend" in content_lower:
            return "Backend Engineer (Early Career)"
        elif "ai" in content_lower or "agent" in content_lower:
            return "AI / Agentic Systems Engineer"
        elif "full stack" in content_lower or "fullstack" in content_lower:
            return "Full Stack Developer (Java/Python)"
        return "Software Engineer (0-2 Yrs)"

    async def fetch_jobs(self) -> list[dict]:
        """Fetch raw LinkedIn post search results."""
        all_posts: list[dict] = []
        seen_urls = set()

        async with httpx.AsyncClient(**self.CLIENT_KWARGS) as client:
            tasks = [self._fetch_public_posts_search(client, q) for q in SEARCH_QUERIES]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, list):
                    for post in res:
                        url = post.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_posts.append(post)

        return all_posts

    async def parse_jobs(self, raw_jobs: list[dict]) -> list[JobData]:
        """Convert raw LinkedIn post items into standard JobData objects."""
        jobs: list[JobData] = []
        for post in raw_jobs:
            content = post.get("content", "")
            title = self._extract_role_title(content)
            company = self._extract_company_from_post(post.get("title", ""), content)
            emails = post.get("emails", [])

            email_note = f"\n\nRecruiter Direct Email: {', '.join(emails)}" if emails else ""
            description = f"LinkedIn Hiring Post:\n{content}{email_note}"

            job_data = JobData(
                title=title,
                company=company,
                location="Remote / India",
                job_url=post.get("url", "https://linkedin.com/feed"),
                description=description,
                source="linkedin_posts",
                remote=True,
                posted_date=date.today(),
            )
            jobs.append(job_data)

        logger.info(f"💼 [LinkedIn Posts] Parsed {len(jobs)} hiring opportunities with recruiter outreach")
        return jobs
