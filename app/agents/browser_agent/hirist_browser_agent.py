"""
Portal 4: Hirist Browser Auto-Apply Agent (Finance & Business Analyst Sector).
Automates job discovery and applications on Hirist (hirist.tech / hirist.com):
- Strict Experience: Fresher / 0-1 Years only (via FinanceExperienceAnalyzer)
- Target Cap: 40-50 applications per session
- Tailors ATS 1-page PDF resumes in resumes/hirist/
- Sign-in detection loop: waits for user login if session is not active.
"""
import asyncio
import logging
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.agents.browser_agent.browser_client import SharedBrowserClient
from app.agents.browser_agent.experience_analyzer import FinanceExperienceAnalyzer
from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
    REPORTS_DIR,
)
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService

logger = logging.getLogger(__name__)

HIRIST_SEARCH_URL = "https://www.hirist.tech/search/fintech-jobs?query=fintech-jobs&minexp=0&maxexp=1&loc=&sort=&page=0&industry=&posting=3"


class HiristBrowserAgent:
    """
    Portal 4: Hirist Browser Auto-Apply Agent for Finance candidates.
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: Optional[str] = None,
        browser_executable_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.browser_client = SharedBrowserClient(
            cdp_port=cdp_port,
            user_data_dir=user_data_dir,
            browser_executable_path=browser_executable_path,
            dry_run=dry_run,
        )
        self.dry_run = dry_run
        self.resume_service = ResumeService()
        self.scoring_service = ScoringService()

        self.resumes_dir = Path("resumes/hirist")
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = Path(REPORTS_DIR) / "screenshots" / "hirist"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def connect(self, context=None, page=None):
        """Connect to shared browser and verify sign-in status."""
        self._page = await self.browser_client.connect(context=context, page=page)

        logger.info("🔍 Checking Hirist session status...")
        await self.browser_client.safe_goto(HIRIST_SEARCH_URL, timeout=60000)
        await asyncio.sleep(2.0)

        await self.browser_client.wait_for_portal_signin(
            portal_name="Hirist",
            logged_in_selectors=[
                "img[src*='userpics']",
                "img[src*='notification']",
                "header img[src*='media']",
                "div.user-profile",
                "a[href*='my-account']",
                "a[href*='candidate-dashboard']",
                "a[href*='profile']",
                "div.profile-icon",
                "a:has-text('Dashboard')",
                "a:has-text('Applied Jobs')",
                "a:has-text('My Profile')",
                "a:has-text('Logout')",
                "button:has-text('Logout')",
            ],
            logged_out_selectors=[
                "a[href*='/candidate-login']",
                "a[href*='/login']",
            ],
            auth_url_patterns=["/login", "/candidate-login"],
        )

    async def run_auto_apply(
        self,
        target_applied: int = 45,
        max_inspect: int = 60,
    ) -> List[Dict]:
        """
        Iterates through Hirist Fintech listings matching Finance profile.
        Applies up to target_applied (40-50) applications.
        """
        applied_count = 0
        all_results = []
        consecutive_empty_scrolls = 0
        max_scroll_attempts = 4
        inspected_keys: set[str] = set()

        logger.info("\n" + "=" * 65)
        logger.info(f"🟣 [HIRIST BROWSER AGENT] Starting run (Target: {target_applied} applications, Fresher / 0-1 yrs)")
        logger.info(f"🔗 Search URL: {HIRIST_SEARCH_URL}")
        logger.info("=" * 65)

        self._page = await self.browser_client.ensure_active_page()
        if "fintech-jobs" not in self._page.url:
            await self.browser_client.safe_goto(HIRIST_SEARCH_URL, timeout=45000)
            await asyncio.sleep(2.5)

        while applied_count < target_applied and consecutive_empty_scrolls < max_scroll_attempts:
            try:
                self._page = await self.browser_client.ensure_active_page()

                # Robust job card selectors on Hirist — only elements that contain job links or job-card classes
                card_selectors = (
                    "div.job-item, div.feed-item, div.job-card, div[class*='jobCard'], "
                    "div[class*='job-card'], div[class*='JobCard'], "
                    "div[class*='MuiPaper-root']:has(a[href*='/j/']), "
                    "div[class*='MuiPaper-root']:has(a.job-title)"
                )
                cards = await self._page.locator(card_selectors).all()

                # Fallback: locate job link anchors directly if container classes changed
                if not cards:
                    job_link_anchors = await self._page.locator("a[href*='/j/']").all()
                    cards = [a for a in job_link_anchors]

                if not cards:
                    consecutive_empty_scrolls += 1
                    logger.info(f"📜 Scrolling Hirist feed ({consecutive_empty_scrolls}/{max_scroll_attempts})...")
                    await self._page.evaluate("window.scrollBy(0, 1000);")
                    await asyncio.sleep(2.5)
                    continue

                processed_in_pass = 0

                for idx, card in enumerate(cards):
                    if applied_count >= target_applied:
                        break

                    try:
                        # 1. Extract Title
                        title_el = card.locator("a[href*='/j/'], a.job-title, h3, h2, div[class*='jobTitle'], span[class*='jobTitle']").first
                        if await title_el.count() == 0:
                            tag = await card.evaluate("el => el.tagName.toLowerCase()")
                            if tag == "a":
                                title_el = card
                            else:
                                continue

                        title = (await title_el.inner_text()).strip().replace("\n", " ")
                        if not title or len(title) < 4 or title.lower() in [
                            "company", "apply", "view", "search", "filter", "hirist", "fintech", "jobs", "home"
                        ]:
                            continue

                        # 2. Extract Company
                        comp_el = card.locator(
                            "a.company-name, div.recruiter-name, span.company, div[class*='company'], span[class*='company']"
                        ).first
                        company = (await comp_el.inner_text()).strip().replace("\n", " ") if await comp_el.count() > 0 else ""
                        if not company or company.lower() in ["company", "confidential"]:
                            card_text = (await card.inner_text()).strip()
                            m = re.search(r'(?:at|company:)\s*([A-Za-z0-9&.,\-\s]{2,40})', card_text, re.IGNORECASE)
                            company = m.group(1).strip() if m else "Hiring Company"

                        # 3. Deduplication Key (by job URL or title+company)
                        job_link_el = card.locator("a[href*='/j/']").first
                        job_href = await job_link_el.get_attribute("href") if await job_link_el.count() > 0 else ""
                        card_key = job_href if job_href else f"{title.lower()}::{company.lower()}"

                        if card_key in inspected_keys:
                            continue
                        inspected_keys.add(card_key)

                        job_url = urllib.parse.urljoin("https://www.hirist.tech", job_href) if job_href and not job_href.startswith("http") else (job_href or self._page.url)

                        # Verify Finance domain relevance
                        if not any(kw in (title + " ").lower() for kw in [
                            "finance", "analyst", "accounting", "banking", "equity", "credit", "audit", "fp&a", "accounts", "fintech"
                        ]):
                            continue

                        # Check tracker deduplication
                        if JobTracker.is_already_applied("hirist", job_url=job_url, title=title, company=company):
                            logger.info(f"⏭️ Skipping already applied job: '{title}' @ {company}")
                            continue

                        full_jd = (await card.inner_text()).strip()

                        # 4. Strict Experience Analyzer (0-1 Years Fresher Only)
                        exp_check = FinanceExperienceAnalyzer.analyze(title, full_jd)
                        if not exp_check["eligible"]:
                            logger.info(f"⏭️ [Experience Filter] Skipped '{title}': {exp_check['reason']}")
                            JobTracker.record_job("hirist", company, title, job_url, status="SKIPPED_EXP", notes=exp_check["reason"])
                            continue

                        # 5. Check if already marked applied in card text
                        if "applied" in full_jd.lower() and not ("apply now" in full_jd.lower() or "apply" in full_jd.lower()):
                            logger.info(f"⏭️ Already applied to '{title}' @ {company}")
                            JobTracker.record_job("hirist", company, title, job_url, status="ALREADY_APPLIED")
                            continue

                        # 6. Verify Apply Button is VISIBLE BEFORE invoking Gemini resume generation
                        apply_btn = card.locator(
                            "button:has-text('Apply'), a:has-text('Apply Now'), button.btn-apply, a:has-text('Apply'), button[class*='apply']"
                        ).first
                        if await apply_btn.count() == 0 or not await apply_btn.is_visible():
                            logger.debug(f"⏭️ No visible Apply button for '{title}' @ {company}")
                            continue

                        # 7. Apply button confirmed! Now generate ATS Tailored PDF Resume
                        logger.info(f"\n[{applied_count + 1}/{target_applied}] 🚀 Processing Hirist Job: '{title}' @ {company}...")
                        job_dict = {"title": title, "company": company, "description": full_jd}
                        tailored_pdf = self.resume_service.generate_tailored_resume(job=job_dict, portal="hirist")

                        # 8. Click Apply Button
                        await card.scroll_into_view_if_needed(timeout=3000)
                        await self.browser_client.human_click(apply_btn, hover_pause=(0.2, 0.4), post_pause=(1.5, 2.5))
                        await asyncio.sleep(1.0)

                        # Handle resume upload if modal appears
                        file_inp = self._page.locator("input[type='file']").first
                        if await file_inp.count() > 0 and os.path.exists(tailored_pdf):
                            await file_inp.set_input_files(os.path.abspath(tailored_pdf))
                            await asyncio.sleep(1.0)

                        confirm_apply = self._page.locator(
                            "button:has-text('Confirm Apply'), button:has-text('Submit'), button.btn-primary, button:has-text('Confirm')"
                        ).first

                        if self.dry_run:
                            logger.info(f"🧪 [DRY RUN] Prepared Hirist application for '{title}' @ {company}.")
                            applied_count += 1
                            processed_in_pass += 1
                            continue

                        if await confirm_apply.count() > 0 and await confirm_apply.is_visible():
                            await self.browser_client.human_click(confirm_apply, hover_pause=(0.2, 0.4), post_pause=(2.0, 3.0))

                        applied_count += 1
                        processed_in_pass += 1
                        consecutive_empty_scrolls = 0
                        JobTracker.record_job("hirist", company, title, job_url, status="APPLIED", resume_version=tailored_pdf)
                        all_results.append({"title": title, "company": company, "status": "APPLIED"})
                        logger.info(f"🎉 Applied to '{title}' @ {company} on Hirist! ({applied_count}/{target_applied})")
                        await asyncio.sleep(3.0)

                    except Exception as card_err:
                        logger.debug(f"Hirist card processing error: {card_err}")

                if processed_in_pass == 0:
                    consecutive_empty_scrolls += 1
                    logger.info(f"📜 No new applications in this pass, scrolling Hirist feed ({consecutive_empty_scrolls}/{max_scroll_attempts})...")
                else:
                    consecutive_empty_scrolls = 0

                # Scroll down for next page / lazy loading
                await self._page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(2.5)

            except Exception as e:
                logger.error(f"Hirist run error: {e}")
                break

        logger.info(f"🏁 [Hirist Complete] Successfully applied to {applied_count}/{target_applied} jobs.")
        return all_results

    async def close(self):
        await self.browser_client.close()
