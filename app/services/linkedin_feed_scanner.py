"""
LinkedIn Feed & Hiring Post Scanner Service.

Dedicated module to search and scan LinkedIn feed and hiring posts for:
  - Recruiter / HR hiring announcements (e.g., "We are Hiring", "Send CV at recruiter@...")
  - Target tech stack: Java, Spring Boot, Microservices, Python, FastAPI, Cloud (0-2 Yrs / 1+ Yrs)
  - Direct recruiter email extraction & validation
  - Clickable LinkedIn post links
  - Cold email outreach with tailored ATS resume
  - Dedicated Recruiter & HR Excel report generation & email dispatch
"""
import asyncio
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.config.settings import (
    CANDIDATE_NAME,
    EMAIL_ADDRESS,
    MATCH_SCORE_THRESHOLD,
    REPORTS_DIR,
)
from app.services.email_service import EmailService
from app.services.report_service import ReportService
from app.services.resume_service import ResumeService
from app.utils.email_validator import extract_emails_from_text

logger = logging.getLogger(__name__)

# Search queries for direct hiring posts with contact emails on LinkedIn
LINKEDIN_FEED_QUERIES = [
    'site:linkedin.com/posts "We are hiring" "Java" "email" "resume"',
    'site:linkedin.com/posts "Hiring" "Spring Boot" ("send resume" OR "send CV" OR "email to")',
    'site:linkedin.com/posts "Hiring" "Python" "FastAPI" ("email" OR "CV")',
    'site:linkedin.com/posts "Hiring" ("Backend Developer" OR "Java Developer") ("0-2 years" OR "1+ years" OR "Fresher")',
    'site:linkedin.com/posts "Hiring" "Associate Software Engineer" "email" "resume"',
    'site:linkedin.com/posts "Hiring" ("Cloud Engineer" OR "AWS") "send CV"',
]


class LinkedInFeedScanner:
    """
    Dedicated scanner for LinkedIn hiring feeds & recruiter posts.
    """

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.email_service = EmailService()
        self.resume_service = ResumeService()
        self.report_service = ReportService()

    async def scan_posts_and_outreach(self, dry_run: bool = False, use_browser: bool = True) -> dict:
        """
        Scan LinkedIn hiring posts, extract genuine recruiter emails,
        match with candidate profile, dispatch cold emails, and generate report.
        """
        logger.info("🔍 [LinkedIn HR Scanner] Starting dedicated recruiter feed scan...")
        discovered_posts: list[dict] = []
        seen_urls: set[str] = set()

        # ── Step 1: Live Browser Feed Extraction (If requested) ──
        if use_browser:
            browser_posts = await self._scan_via_browser()
            for p in browser_posts:
                if p["post_url"] not in seen_urls:
                    seen_urls.add(p["post_url"])
                    discovered_posts.append(p)

        # ── Step 2: Fallback / Search Stream for Public LinkedIn Posts ──
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for q in LINKEDIN_FEED_QUERIES:
                try:
                    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
                    resp = await client.get(search_url, headers=self.headers)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    results = soup.find_all("div", class_="result")

                    for res in results:
                        link_elem = res.find("a", class_="result__url")
                        snippet_elem = res.find("a", class_="result__snippet")
                        title_elem = res.find("h2")

                        raw_url = link_elem.get("href", "") if link_elem else ""
                        if "uddg=" in raw_url:
                            from urllib.parse import unquote
                            raw_url = unquote(raw_url.split("uddg=")[1].split("&")[0])

                        if not raw_url or "linkedin.com/posts" not in raw_url:
                            continue

                        if raw_url in seen_urls:
                            continue
                        seen_urls.add(raw_url)

                        snippet_text = snippet_elem.get_text().strip() if snippet_elem else ""
                        title_text = title_elem.get_text().strip() if title_elem else ""
                        full_text = f"{title_text}\n{snippet_text}"

                        # Extract recruiter email
                        emails = extract_emails_from_text(full_text)
                        primary_email = emails[0] if emails else None

                        # Extract role & company
                        clean_title = self._extract_role_title(full_text)
                        company_name = self._extract_company_name(title_text, snippet_text)

                        discovered_posts.append({
                            "title": clean_title,
                            "company": company_name,
                            "post_url": raw_url,
                            "raw_text": full_text,
                            "hr_email": primary_email,
                            "score": 85 if ("java" in full_text.lower() or "python" in full_text.lower() or "backend" in full_text.lower()) else 65,
                        })
                except Exception as e:
                    logger.warning(f"[LinkedIn HR Scanner] Query '{q}' error: {e}")

        logger.info(f"📊 [LinkedIn HR Scanner] Total {len(discovered_posts)} relevant LinkedIn hiring posts collected.")

        # ── Step 3: Process Posts & Perform Cold Outreach ──
        outreach_entries = []
        emails_sent_count = 0
        direct_links_count = 0

        for post in discovered_posts:
            title = post["title"]
            company = post["company"]
            hr_email = post["hr_email"]
            score = post["score"]
            post_url = post["post_url"]

            resume_path = None
            sent = False
            subject = f"Application: {title} — Kamal Kumar (1+ Years Experience)"

            if hr_email:
                try:
                    # Generate tailored 1-page ATS resume
                    resume_path = self.resume_service.generate_tailored_resume(
                        job_id=f"linkedin_{len(outreach_entries)}",
                        job_title=title,
                        company=company,
                        job_description=post["raw_text"],
                    )
                except Exception as res_err:
                    logger.warning(f"Failed to generate resume for {title}: {res_err}")

                # Draft personalized email tailored for 0-2 yrs
                draft = self.email_service.draft_email(
                    job_title=title,
                    company=company,
                    job_description=post["raw_text"],
                    resume_text=self.resume_service.get_resume_text(),
                    match_score=score,
                )
                cover_letter = draft.get("body", "")
                subject = draft.get("subject", subject)

                if not dry_run:
                    sent = self.email_service.send_email(
                        to_email=hr_email,
                        subject=subject,
                        body=cover_letter,
                        pdf_attachment_path=resume_path,
                    )
                    if sent:
                        emails_sent_count += 1
                        logger.info(f"📧 [LinkedIn HR Outreach] Sent email to {hr_email} for '{title}' @ {company}")
            else:
                direct_links_count += 1

            outreach_entries.append({
                "title": title,
                "company": company,
                "score": f"{score}/100",
                "route": "Stream A (Recruiter Outreach)" if hr_email else "Stream B (LinkedIn Post Link)",
                "hr_email": hr_email,
                "to_email": hr_email or "None Found (Post Link)",
                "job_url": post_url,
                "email_sent": sent,
                "resume_path": resume_path,
                "subject": subject,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

        # ── Step 4: Generate Dedicated Excel Report ──
        run_stats = {
            "posts_scanned_for_hr": len(discovered_posts),
            "recruiter_emails_found": len([p for p in discovered_posts if p.get("hr_email")]),
            "emails_sent": emails_sent_count,
            "direct_applied": direct_links_count,
        }

        report_path = self.report_service.generate_recruiter_report(
            recruiter_entries=outreach_entries,
            stats=run_stats,
        )

        # ── Step 5: Dispatch Dedicated Email to Candidate ──
        if EMAIL_ADDRESS and os.path.exists(report_path) and not dry_run:
            try:
                today_str = date.today().strftime("%Y-%m-%d")
                email_subject = f"📬 [AI Job Agent] LinkedIn Recruiter & HR Outreach Report — {today_str}"
                email_body = f"""Hi {CANDIDATE_NAME},

Here is your dedicated LinkedIn Recruiter & HR Hiring Post Outreach Report for {today_str}.

📊 LinkedIn Recruiter Feed Discovery & Outreach Metrics:
• Total LinkedIn Hiring Posts Scanned: {run_stats['posts_scanned_for_hr']}
• Verified Recruiter / HR Contact Emails Discovered: {run_stats['recruiter_emails_found']}
• Cold Outreach Dispatched with Tailored ATS Resume: {run_stats['emails_sent']}
• Direct LinkedIn Post Links Prepared: {run_stats['direct_applied']}

📎 Attached Excel Workbook:
The dedicated report ({os.path.basename(report_path)}) is attached containing direct clickable LinkedIn post URLs, recruiter email IDs, cover letters, and outreach delivery confirmations.

Best regards,
AI Job Agent Orchestrator
"""
                self.email_service.send_email(
                    to_email=EMAIL_ADDRESS,
                    subject=email_subject,
                    body=email_body,
                    attachment_path=report_path,
                )
                logger.info(f"✅ LinkedIn Recruiter HR report emailed to {EMAIL_ADDRESS}")
            except Exception as mail_err:
                logger.warning(f"Failed to email LinkedIn Recruiter HR report: {mail_err}")

        return {
            "posts_scanned": len(discovered_posts),
            "recruiter_emails_found": run_stats["recruiter_emails_found"],
            "emails_sent": emails_sent_count,
            "direct_links_prepared": direct_links_count,
            "report_path": report_path,
        }

    async def _scan_via_browser(self) -> list[dict]:
        """Use Playwright to scan LinkedIn feed & hiring posts from user's logged-in session."""
        posts = []
        try:
            from playwright.async_api import async_playwright
            user_chrome_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
            session_dir = os.path.join(os.path.expanduser("~"), ".ai_job_agent_linkedin_session")

            async with async_playwright() as p:
                logger.info("🌐 [LinkedIn Browser] Launching browser to scan https://www.linkedin.com/feed/ ...")
                
                # Launch persistent browser context
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=session_dir,
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                    ],
                )
                page = await context.new_page()
                await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(3)

                # Scroll and click "see more" and "Load more" buttons
                for scroll_idx in range(6):
                    # Click all "...see more" buttons on posts to expand full descriptions containing emails
                    see_more_buttons = await page.query_selector_all("button.feed-shared-inline-show-more-text__see-more-less-toggle, button:has-text('...more'), button:has-text('see more')")
                    for btn in see_more_buttons[:10]:
                        try:
                            if await btn.is_visible():
                                await btn.click(timeout=1000)
                        except Exception:
                            pass

                    # Click any "Load more posts" / "Show more results" buttons
                    load_more_buttons = await page.query_selector_all("button:has-text('Load more'), button:has-text('Show more results'), button:has-text('Load new posts')")
                    for lmb in load_more_buttons:
                        try:
                            if await lmb.is_visible():
                                await lmb.click(timeout=1500)
                                logger.info("🖱️ [LinkedIn Browser] Clicked 'Load more posts' button")
                        except Exception:
                            pass

                    # Scroll down
                    await page.evaluate("window.scrollBy(0, 1200)")
                    await asyncio.sleep(1.5)

                content = await page.content()
                soup = BeautifulSoup(content, "html.parser")
                feed_items = soup.find_all("div", class_=re.compile(r"feed-shared-update-v2"))

                logger.info(f"🔍 [LinkedIn Browser] Found {len(feed_items)} feed post items on page.")

                for item in feed_items:
                    text = item.get_text(separator="\n").strip()
                    emails = extract_emails_from_text(text)
                    if emails:
                        primary_email = emails[0]
                        title = self._extract_role_title(text)

                        # Extract poster / author name
                        actor_elem = item.find("span", class_=re.compile(r"update-components-actor__name|feed-shared-actor__name"))
                        company_name = actor_elem.get_text().strip() if actor_elem else "LinkedIn Recruiter"

                        # Extract post URL
                        post_link_elem = item.find("a", href=re.compile(r"/feed/update/urn:li:activity:|/posts/"))
                        post_url = "https://www.linkedin.com/feed/"
                        if post_link_elem and post_link_elem.get("href"):
                            href = post_link_elem["href"]
                            post_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"

                        posts.append({
                            "title": title,
                            "company": company_name,
                            "post_url": post_url,
                            "raw_text": text[:2500],
                            "hr_email": primary_email,
                            "score": 95 if ("java" in text.lower() or "python" in text.lower() or "backend" in text.lower()) else 70,
                        })
                        logger.info(f"✨ [LinkedIn Browser] Discovered HR email {primary_email} for '{title}' @ {company_name}")

                await context.close()
        except Exception as be:
            logger.info(f"[LinkedIn Browser] Browser scan status: {be}")

        return posts

    def _extract_role_title(self, text: str) -> str:
        """Extract or infer role title from post snippet."""
        patterns = [
            r"(?:hiring|looking for|opening for|role of|position of)\s*:?\s*([A-Za-z0-9\+\#\s\/\-\(\)]{4,40})",
            r"(Java\s*(?:Full\s*Stack|Backend)?\s*Developer)",
            r"(Python\s*(?:Backend)?\s*(?:Developer|Engineer))",
            r"(Spring\s*Boot\s*Developer)",
            r"(FastAPI\s*(?:Backend)?\s*Engineer)",
            r"(Associate\s*Software\s*Engineer)",
            r"(Backend\s*Engineer)",
        ]
        for pat in patterns:
            if match := re.search(pat, text, re.IGNORECASE):
                cand = match.group(1).strip()
                if len(cand) > 3 and "\n" not in cand:
                    return cand
        return "Backend Software Engineer"

    def _extract_company_name(self, title: str, snippet: str) -> str:
        """Extract company name from post title or snippet."""
        if " at " in title:
            return title.split(" at ")[-1].split("|")[0].split("-")[0].strip()
        if " @ " in title:
            return title.split(" @ ")[-1].split("|")[0].split("-")[0].strip()
        if " on LinkedIn" in title:
            poster = title.split(" on LinkedIn")[0].strip()
            return poster
        return "Hiring Organization"
