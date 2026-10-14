"""
Portal 3: Y Combinator (Work at a Startup) Auto-Apply Agent (Finance & Strategy).
Automates startup job discovery and applications:
- Target: Early-stage & growth YC startups hiring in Finance, Business Operations, Analytics
- Generates tailored 1-page ATS PDF resumes in resumes/ycombinator/
- Drafts customized founder pitches highlighting financial modeling, ratio analysis, and immediate availability
- Sign-in detection loop: pauses and waits for user sign-in.
"""
import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.agents.browser_agent.browser_client import SharedBrowserClient
from app.agents.browser_agent.experience_analyzer import FinanceExperienceAnalyzer
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
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

YC_PITCH_PROMPT = """Act as an expert early-career finance professional applying to a Y Combinator startup.
Write a punchy, high-impact first-person pitch (under 100 words) addressed to the founders.

Candidate Profile:
- Name: Meesala Srinivas Rao
- Education: MBA (Finance) from CSI Institute of PG Studies (Expected 2026), B.Com from Osmania University (CGPA 7.5)
- Core Competencies: Financial Analysis, Corporate Accounting, Investment Analysis, Ratio Analysis, Valuation, Financial Modeling, MS Excel
- Academic Project: Investment Analysis and Portfolio Management at Infosys Limited
- Availability: Immediate joiner (0 days notice)

Rules:
1. Under 100 words.
2. Directly reference 2 specific requirements from the Job Description.
3. Highlight quantitative rigor, attention to detail, and rapid execution.
4. Strictly first-person ("I", "my").
5. Return ONLY the raw pitch text.
"""


class YCombinatorBrowserAgent:
    """
    Portal 3: Y Combinator Work at a Startup Auto-Apply Agent.
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
        self.gemini_client = get_gemini_client()

        self.resumes_dir = Path("resumes/ycombinator")
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = Path(REPORTS_DIR) / "screenshots" / "ycombinator"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def connect(self, context=None, page=None):
        """Connect to shared browser and verify sign-in status."""
        self._page = await self.browser_client.connect(context=context, page=page)

        logger.info("🔍 Checking Y Combinator (Work at a Startup) session status...")
        await self.browser_client.safe_goto("https://www.workatastartup.com/jobs", timeout=60000)
        await asyncio.sleep(2.0)

        await self.browser_client.wait_for_portal_signin(
            portal_name="Y Combinator",
            logged_in_selectors=[
                "a:has-text('My profile')",
                ":has-text('My profile')",
                ":has-text('srinivas rao')",
                "a[href*='/candidate/']",
                "a[href*='/profile']",
                "div.user-menu",
                "div.avatar",
                "button[aria-label*='user']",
                "a:has-text('Saved jobs')",
            ],
            logged_out_selectors=[
                "a[href*='/users/sign_in']",
                "a[href*='/candidate/sign_in']",
            ],
            auth_url_patterns=["/users/sign_in", "/login"],
        )

    def generate_pitch(self, company: str, job_title: str, job_description: str) -> str:
        """Generates tailored founder pitch using Gemini."""
        prompt = (
            f"Company: {company}\n"
            f"Role: {job_title}\n"
            f"Job Description: {job_description[:2500]}\n"
            f"Write the direct founder pitch now:"
        )
        try:
            if self.gemini_client:
                resp = self.gemini_client.generate_content(
                    prompt=prompt,
                    system_instruction=YC_PITCH_PROMPT,
                    max_output_tokens=300,
                )
                if resp and len(resp.strip()) >= 30:
                    return resp.strip().replace("```", "").strip()
        except Exception as e:
            logger.warning(f"AI YC pitch generation note: {e}")

        # High quality fallback pitch
        return (
            f"Hi Team,\n\n"
            f"I am excited to apply for the {job_title} role at {company}. "
            f"With a strong foundation in financial analysis, corporate accounting, ratio analysis, and financial modeling (MBA Finance 2026), "
            f"I bring deep quantitative rigor and data-driven insights to support your financial planning and operations. "
            f"As an immediate joiner (0 days notice), I would welcome the chance to contribute to {company}."
        )

    async def run_auto_apply(
        self,
        target_applied: int = 40,
        max_inspect: int = 50,
    ) -> List[Dict]:
        """
        Applies to YC startup listings matching candidate Finance profile.
        """
        applied_count = 0
        all_results = []

        logger.info("\n" + "=" * 65)
        logger.info(f"🟠 [Y COMBINATOR BROWSER AGENT] Starting run (Target: {target_applied} applications, Fresher / 0-1 yrs)")
        logger.info("=" * 65)

        try:
            self._page = await self.browser_client.ensure_active_page()
            await self._page.goto("https://www.workatastartup.com/jobs", wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.0)

            # Filter or search Finance / Operations roles
            job_cards = await self._page.locator("div.job-details, div.job-card, div.w-full.border-b").all()
            logger.info(f"📋 Found {len(job_cards)} job cards on YC Work at a Startup")

            for idx, card in enumerate(job_cards):
                if applied_count >= target_applied:
                    break

                try:
                    # Guard against candidate profile redirect or blank tabs
                    self._page = await self.browser_client.ensure_active_page()
                    if any(p in self._page.url.lower() for p in ["/candidate", "/profile", "/users/edit"]):
                        logger.warning(f"⚠️ [YC Guard] Detected profile page ('{self._page.url}'). Navigating back to jobs search...")
                        await self._page.goto("https://www.workatastartup.com/jobs", wait_until="domcontentloaded", timeout=45000)
                        await asyncio.sleep(2.5)
                        job_cards = await self._page.locator("div.job-details, div.job-card, div.w-full.border-b").all()

                    await card.scroll_into_view_if_needed(timeout=3000)
                    title_el = card.locator("a.job-name, h3, div.font-bold").first
                    title = await title_el.inner_text() if await title_el.count() > 0 else "Finance Analyst"
                    title = title.strip().replace("\n", " ")

                    comp_el = card.locator("a.company-name, div.company-name, span.company-name").first
                    company = await comp_el.inner_text() if await comp_el.count() > 0 else "YC Startup"
                    company = company.strip().replace("\n", " ")

                    # Check Finance relevance
                    if not any(kw in (title + " ").lower() for kw in ["finance", "analyst", "accounting", "operations", "strategy", "fp&a", "risk", "investment"]):
                        continue

                    job_url = self._page.url
                    if JobTracker.is_already_applied("ycombinator", job_url=job_url, title=title, company=company):
                        continue

                    full_jd = (await card.inner_text()).strip()

                    exp_check = FinanceExperienceAnalyzer.analyze(title, full_jd)
                    if not exp_check["eligible"]:
                        continue

                    logger.info(f"\n[{applied_count + 1}/{target_applied}] 🚀 Processing YC Job: '{title}' @ {company}...")

                    # Tailor ATS Resume
                    job_dict = {"title": title, "company": company, "description": full_jd}
                    tailored_pdf = self.resume_service.generate_tailored_resume(job=job_dict, portal="ycombinator")

                    # Open Apply modal
                    apply_btn = card.locator("button:has-text('Apply'), a:has-text('Apply')").first
                    if await apply_btn.count() > 0 and await apply_btn.is_visible():
                        await self.browser_client.human_click(apply_btn, hover_pause=(0.2, 0.4), post_pause=(1.0, 1.5))
                        await asyncio.sleep(1.5)

                        pitch = self.generate_pitch(company, title, full_jd)
                        textarea = self._page.locator("textarea[name='note'], textarea").first
                        if await textarea.count() > 0 and await textarea.is_visible():
                            await self.browser_client.human_type(textarea, pitch)

                        # File upload if file input exists
                        file_inp = self._page.locator("input[type='file']").first
                        if await file_inp.count() > 0 and os.path.exists(tailored_pdf):
                            await file_inp.set_input_files(os.path.abspath(tailored_pdf))
                            await asyncio.sleep(1.0)

                        send_btn = self._page.locator("button:has-text('Send application'), button:has-text('Submit'), button[type='submit']").first

                        if self.dry_run:
                            logger.info(f"🧪 [DRY RUN] Prepared YC pitch for '{title}' @ {company}.")
                            applied_count += 1
                            continue

                        if await send_btn.count() > 0 and await send_btn.is_visible():
                            await self.browser_client.human_click(send_btn, hover_pause=(0.2, 0.4), post_pause=(2.0, 3.0))
                            applied_count += 1
                            JobTracker.record_job("ycombinator", company, title, job_url, status="APPLIED", resume_version=tailored_pdf)
                            all_results.append({"title": title, "company": company, "status": "APPLIED"})
                            logger.info(f"🎉 Successfully applied to '{title}' @ {company} on YC!")
                            await asyncio.sleep(3.0)

                except Exception as card_err:
                    logger.debug(f"YC card error: {card_err}")

        except Exception as e:
            logger.error(f"YC run error: {e}")

        logger.info(f"🏁 [YC Complete] Successfully applied to {applied_count}/{target_applied} jobs.")
        return all_results

    async def close(self):
        await self.browser_client.close()
