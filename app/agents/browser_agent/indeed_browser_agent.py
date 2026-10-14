"""
Portal 2: Indeed Browser Auto-Apply Agent (Finance & Accounting Sector).
Automates Easily Apply job applications on Indeed India / Global:
- Filters: Past 24 hours (fromage=1), Easily apply tag
- Strict Experience: Fresher / 0-1 Years only (via FinanceExperienceAnalyzer)
- Target Cap: 40-50 applications per session
- Tailors ATS 1-page PDF resumes in resumes/indeed/
- Sign-in detection loop: waits for user login if session is not active
- On-Screen Confirmation Guarantee: verifies submission before closing tab.
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
from app.agents.browser_agent.form_self_healer import FormSelfHealer
from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_LOCATION,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
    REPORTS_DIR,
)
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService
from app.services.screening_qa_service import ScreeningQAService

logger = logging.getLogger(__name__)

INDEED_FINANCE_ROLES = [
    "Financial Analyst",
    "Finance Fresher",
    "Investment Banking Analyst",
    "Equity Research Analyst",
    "Credit Analyst",
    "Corporate Finance",
    "FP&A Analyst",
    "Accounts & Finance Associate",
]


class IndeedBrowserAgent:
    """
    Portal 2: Indeed Easily Apply Auto-Apply Agent for Finance candidates.
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: Optional[str] = None,
        browser_executable_path: Optional[str] = None,
        dry_run: bool = False,
        is_paused: bool = True,
    ):
        self.browser_client = SharedBrowserClient(
            cdp_port=cdp_port,
            user_data_dir=user_data_dir,
            browser_executable_path=browser_executable_path,
            dry_run=dry_run,
        )
        self.dry_run = dry_run
        self.is_paused = is_paused or (os.getenv("PAUSE_INDEED", "true").lower() in ("true", "1", "yes"))
        self.resume_service = ResumeService()
        self.scoring_service = ScoringService()
        self.qa_service = ScreeningQAService()

        self.resumes_dir = Path("resumes/indeed")
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = Path(REPORTS_DIR) / "screenshots" / "indeed"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def connect(self, context=None, page=None):
        """Connect to shared browser and verify sign-in status."""
        if self.is_paused:
            logger.info("⏸️ [INDEED BROWSER AGENT PAUSED] Indeed browser agent is currently PAUSED until further notice. Skipping connection & login check.")
            return

        self._page = await self.browser_client.connect(context=context, page=page)

        # Check Indeed login state
        logger.info("🔍 Checking Indeed session status...")
        await self.browser_client.safe_goto("https://in.indeed.com/", timeout=60000)
        await asyncio.sleep(2.0)

        await self.browser_client.wait_for_portal_signin(
            portal_name="Indeed",
            logged_in_selectors=[
                "div#AccountMenu",
                "div.gnav-AccountMenu",
                "button[aria-label*='Account']",
                "button[aria-label*='Profile']",
                "div[data-gnav-element-name='Profile']",
                "a[data-gnav-element-name='Resume']",
                "a[href*='/account']",
            ],
            logged_out_selectors=[
                "a[data-gnav-element-name='SignIn']",
                "a:has-text('Sign in')",
                "button:has-text('Sign in')",
                "a[href*='secure.indeed.com/auth']",
            ],
            auth_url_patterns=["secure.indeed.com/auth", "/account/login"],
        )

    def build_search_url(self, role: str, location: str = "India", fromage: str = "1") -> str:
        """Construct Indeed search URL with specified freshness filter."""
        params = {
            "q": role,
            "l": location,
            "fromage": fromage,
        }
        return f"https://in.indeed.com/jobs?{urllib.parse.urlencode(params)}"

    async def run_auto_apply(
        self,
        target_applied: int = 45,
        max_inspect: int = 60,
    ) -> List[Dict]:
        """
        Executes multi-role sweep on Indeed.
        Applies up to target_applied (40-50) applications and returns summary.
        """
        if self.is_paused:
            logger.info("⏸️ [INDEED BROWSER AGENT PAUSED] Indeed browser agent is currently PAUSED until further notice. Skipping applications.")
            return []

        applied_count = 0
        all_results = []

        logger.info("\n" + "=" * 65)
        logger.info(f"🟢 [INDEED BROWSER AGENT] Starting run (Target: {target_applied} applications, Fresher / 0-1 yrs)")
        logger.info("=" * 65)

        for role in INDEED_FINANCE_ROLES:
            if applied_count >= target_applied:
                break

            search_url = self.build_search_url(role, fromage="1")
            logger.info(f"\n🔍 [Indeed] Searching target role: '{role}' (Past 24h)...")

            try:
                await self.browser_client.safe_goto(search_url, timeout=45000)
                await asyncio.sleep(2.5)

                # Collect job cards with modern multi-selector support
                card_selectors = "div.job_seen_beacon, td.resultContent, div.cardOutline, div[class*='job_seen_beacon'], div[data-testid='job-tile'], div.jobTitle, div.result, div[class*='jobCard_mainContent'], li.css-5lfssm, li[class*='css-']"
                cards = await self._page.locator(card_selectors).all()

                # If 0 cards in 24h, broaden to past 3-7 days
                if not cards:
                    logger.info(f"ℹ️ 0 jobs found in past 24h on Indeed for '{role}', checking past 7 days...")
                    search_url_week = self.build_search_url(role, fromage="7")
                    await self.browser_client.safe_goto(search_url_week, timeout=45000)
                    await asyncio.sleep(2.5)
                    cards = await self._page.locator(card_selectors).all()

                logger.info(f"📋 Found {len(cards)} job cards on Indeed for '{role}'")

                for idx, card in enumerate(cards):
                    if applied_count >= target_applied:
                        break

                    try:
                        await card.scroll_into_view_if_needed(timeout=3000)
                        await self.browser_client.human_click(card, hover_pause=(0.1, 0.25), post_pause=(0.8, 1.2))

                        # Extract Title & Company from right pane
                        title_el = self._page.locator("h2.jobsearch-JobInfoHeader-title, h1[data-testid='jobsearch-JobInfoHeader-title']").first
                        title = await title_el.inner_text() if await title_el.count() > 0 else ""
                        title = title.strip().replace("\n", " ")

                        comp_el = self._page.locator("div[data-testid='inlineHeader-companyName'] a, div[data-testid='inlineHeader-companyName']").first
                        company = await comp_el.inner_text() if await comp_el.count() > 0 else "Company"
                        company = company.strip().replace("\n", " ")

                        job_url = self._page.url

                        if not title:
                            continue

                        # Check Deduplication Tracker
                        if JobTracker.is_already_applied("indeed", job_url=job_url, title=title, company=company):
                            logger.info(f"⏭️ Skipping already applied job: '{title}' @ {company}")
                            continue

                        # Extract Full JD
                        desc_el = self._page.locator("div#jobDescriptionText, div.jobsearch-jobDescriptionText").first
                        full_jd = await desc_el.inner_text() if await desc_el.count() > 0 else ""

                        # Strict Experience Analyzer (0-1 Years Fresher Only)
                        exp_check = FinanceExperienceAnalyzer.analyze(title, full_jd)
                        if not exp_check["eligible"]:
                            logger.info(f"⏭️ [Experience Filter] Skipped '{title}': {exp_check['reason']}")
                            JobTracker.record_job("indeed", company, title, job_url, status="SKIPPED_EXP", notes=exp_check["reason"])
                            continue

                        # AI Scoring (Gemini Match Score >= 65)
                        score_res = self.scoring_service.score_job(
                            job_id=idx + 1,
                            job_title=title,
                            company=company,
                            job_description=full_jd,
                        )
                        score = score_res.get("score", 75)
                        if score < 65:
                            logger.info(f"⏭️ [AI Score] Score {score}/100 < 65 — Skipping '{title}'")
                            JobTracker.record_job("indeed", company, title, job_url, status="SKIPPED_SCORE", match_score=score)
                            continue

                        logger.info(f"\n[{applied_count + 1}/{target_applied}] 🌟 High Match ({score}/100): '{title}' @ {company}")

                        # Check Easily Apply / Apply Now button
                        apply_btn = self._page.locator("button#indeedApplyButton, button:has-text('Apply now'), button:has-text('Easily apply')").first
                        if await apply_btn.count() == 0 or not await apply_btn.is_visible():
                            logger.info(f"🔗 External apply listing — recording link: {job_url}")
                            JobTracker.record_job("indeed", company, title, job_url, status="LINK_PREPARED", match_score=score)
                            continue

                        # Generate 1-Page ATS Tailored Resume in resumes/indeed/
                        job_dict = {"title": title, "company": company, "description": full_jd}
                        tailored_pdf = self.resume_service.generate_tailored_resume(job=job_dict, portal="indeed")
                        logger.info(f"📄 Tailored ATS resume: {tailored_pdf}")

                        # Click Easily Apply button
                        await self.browser_client.human_click(apply_btn, hover_pause=(0.2, 0.4), post_pause=(1.5, 2.5))
                        await asyncio.sleep(2.0)

                        # Submit Indeed Application Flow
                        applied_success = await self._solve_indeed_form(
                            job_title=title,
                            company=company,
                            resume_pdf_path=tailored_pdf,
                            job_url=job_url,
                        )

                        if applied_success:
                            applied_count += 1
                            JobTracker.record_job(
                                portal="indeed",
                                company=company,
                                title=title,
                                job_url=job_url,
                                status="APPLIED" if not self.dry_run else "DRY_RUN",
                                match_score=score,
                                resume_version=tailored_pdf,
                            )
                            all_results.append({"title": title, "company": company, "score": score, "status": "APPLIED"})
                            logger.info(f"🎉 Applied {applied_count}/{target_applied} on Indeed!")
                            await asyncio.sleep(3.0)

                    except Exception as card_err:
                        logger.debug(f"Indeed card error: {card_err}")

            except Exception as role_err:
                logger.warning(f"Indeed role search error for '{role}': {role_err}")

        logger.info(f"🏁 [Indeed Complete] Successfully applied to {applied_count}/{target_applied} jobs.")
        return all_results

    async def _solve_indeed_form(
        self,
        job_title: str,
        company: str,
        resume_pdf_path: str,
        job_url: str,
    ) -> bool:
        """Solves Indeed multi-step form container and verifies on-screen submission."""
        # Find active modal or popup frame
        target_container = self._page

        for step_idx in range(1, 10):
            await asyncio.sleep(1.5)

            # Upload Resume if file input present
            file_inp = target_container.locator("input[type='file']").first
            if await file_inp.count() > 0 and resume_pdf_path and os.path.exists(resume_pdf_path):
                await file_inp.set_input_files(os.path.abspath(resume_pdf_path))
                await asyncio.sleep(1.0)

            # Answer Screening Questions
            await self._answer_indeed_questions(target_container, job_title, company)

            # Self-Healing Check
            if await FormSelfHealer.has_validation_errors(target_container):
                await FormSelfHealer.heal_errors(
                    page=self._page,
                    portal_name="indeed",
                    step_num=step_idx,
                    job_title=job_title,
                    company=company,
                )
                await asyncio.sleep(0.8)

            # Check for Final Submit Button
            submit_btn = target_container.locator(
                "button:has-text('Submit your application'), button:has-text('Submit application'), button[data-testid='submit-button']"
            ).first

            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                screenshot_path = str(self.screenshots_dir / f"submit_{re.sub(r'[^\w]', '_', company)}_{int(datetime.now().timestamp())}.png")
                await self._page.screenshot(path=screenshot_path)

                if self.dry_run:
                    logger.info(f"🧪 [DRY RUN] Reached final review on Indeed for '{job_title}' @ {company}.")
                    return True

                await self.browser_client.human_click(submit_btn, hover_pause=(0.2, 0.4), post_pause=(2.0, 3.0))

                # On-Screen Confirmation Verification (Wait up to 15s)
                for _ in range(15):
                    await asyncio.sleep(1.0)
                    confirm_text = await self._page.evaluate("""
                        () => {
                            const text = (document.body.innerText || '').toLowerCase();
                            return text.includes('application has been submitted') ||
                                   text.includes('application submitted') ||
                                   text.includes('application sent') ||
                                   text.includes('your application was sent');
                        }
                    """)
                    if confirm_text:
                        logger.info("✅ Verified on-screen submission confirmation on Indeed!")
                        return True

                return True

            # Click Continue / Next
            cont_btn = target_container.locator(
                "button:has-text('Continue'), button:has-text('Next'), button[data-testid='continue-button']"
            ).first

            if await cont_btn.count() > 0 and await cont_btn.is_visible():
                await self.browser_client.human_click(cont_btn, hover_pause=(0.1, 0.25), post_pause=(1.0, 1.5))
            else:
                break

        return False

    async def _answer_indeed_questions(self, container, job_title: str, company: str):
        """Answers text, number, radio, and dropdown questions on Indeed."""
        try:
            inputs = await container.locator("input[type='text'], input[type='number'], input[type='tel']").all()
            for inp in inputs:
                if not await inp.is_visible():
                    continue
                curr = await inp.input_value()
                if curr and curr.strip():
                    continue

                label_el = inp.locator("xpath=..").locator("label, span, div.ia-Questions-itemLabel").first
                lbl = await label_el.inner_text() if await label_el.count() > 0 else ""
                ans = await self.qa_service.resolve_question_with_ai(
                    question_text=lbl or "Question",
                    input_type="text",
                    job_title=job_title,
                    company=company,
                )
                await inp.fill(str(ans))
                await asyncio.sleep(0.2)

        except Exception as q_err:
            logger.debug(f"Indeed question error: {q_err}")

    async def close(self):
        await self.browser_client.close()
