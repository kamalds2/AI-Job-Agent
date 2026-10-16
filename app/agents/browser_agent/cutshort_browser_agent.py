"""
Portal 5: Cutshort Browser Auto-Apply Agent (cutshort.io) for Finance Candidates.
Automates job discovery and applications on Cutshort:
- Configures filters: Profile Matcher ON, Experience range (0-1 yrs), Hiring activity (1 Days)
- Expands full JD via 'Read more'
- Tailors 1-page ATS PDF resume in resumes/cutshort/
- Uploads resume via native Windows file dialog and Playwright file chooser
- Generates personalized recruiter pitch highlighting financial analysis, modeling, and immediate availability
- Sign-in detection loop: pauses and waits for user sign-in.
"""
import asyncio
import logging
import os
import random
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.agents.browser_agent.browser_client import SharedBrowserClient, handle_windows_file_dialog
from app.agents.browser_agent.experience_analyzer import FinanceExperienceAnalyzer
from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    REPORTS_DIR,
)
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

CUTSHORT_FINANCE_PITCH_PROMPT = """Act as an expert early-career Software & Backend engineer.
Write a highly targeted, punchy, and confident application message to the recruiter on Cutshort.

Candidate Profile:
- Name: Doddi Kamal Kumar
- Education: B.Tech in CSE (2024, CGPA 8.0)
- Core Competencies: Java, Spring Boot, Microservices, Python, FastAPI, AI Agents, AWS, Docker, REST APIs
- Availability: Immediate joiner (0 days notice)
- Location: Open to remote and relocation worldwide

RULES FOR THE MESSAGE:
1. Keep it short and punchy (under 110 words).
2. Start with a warm greeting (e.g. "Hi [Recruiter Name]," or "Hi Team,").
3. Connect 2 specific requirements from the Job Description to the candidate's financial analytical skills.
4. Highlight quantitative rigor, attention to detail, and immediate availability (0 days notice).
5. Write strictly in first-person ("I", "my"). NEVER use third-person pronouns.
6. Use the EXACT Company Name provided.
7. Output ONLY the raw message text without quotes or markdown fences.
"""


CUTSHORT_SEARCH_URL = "https://cutshort.io/profile/all-jobs?tags=financial_accounting-financial_research-general_finance&minexp=0&maxexp=1&hiringActivityOnJob=1-days"


class CutshortBrowserAgent:
    """
    Portal 5: Cutshort Auto-Apply Agent for Finance candidates.
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
        self.gemini_client = get_gemini_client()

        self.resumes_dir = Path("resumes/cutshort")
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = Path(REPORTS_DIR) / "screenshots" / "cutshort"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def connect(self, context=None, page=None):
        """Connect to shared browser and verify sign-in status."""
        self._page = await self.browser_client.connect(context=context, page=page)

        logger.info("🔍 Checking Cutshort session status...")
        await self.browser_client.safe_goto(CUTSHORT_SEARCH_URL, timeout=60000)
        await asyncio.sleep(2.0)

        await self.browser_client.wait_for_portal_signin(
            portal_name="Cutshort",
            logged_in_selectors=[
                "a[href*='candidate-dashboard']",
                "a:has-text('Dashboard')",
                "a:has-text('View jobs')",
                "a:has-text('Messages')",
                "a[href*='candidate-settings']",
                "button:has-text('Apply now')",
                "div:has-text('Profile matcher is ON')",
                "div:has-text('Profile matcher is OFF')",
                "a[href*='/profile/all-jobs']",
                "button[aria-label*='user']",
                "div[class*='user-avatar']",
            ],
            logged_out_selectors=[
                "a[href*='/login']",
                "a[href*='/auth']",
            ],
            auth_url_patterns=["/login", "/auth"],
        )

    def generate_pitch(self, company: str, job_title: str, job_description: str, recruiter_name: str = "") -> str:
        """Generate high-converting recruiter pitch for Cutshort in first-person."""
        clean_company = company.replace("•", "").strip() if company else "your team"
        greeting_name = recruiter_name.split()[0].capitalize() if recruiter_name else "Team"

        user_prompt = f"""Recruiter Name: {greeting_name}
Company Name: {clean_company}
Target Role: {job_title}
JOB DESCRIPTION:
{job_description[:2500]}

Generate the targeted application message for {clean_company} to {greeting_name} now:"""

        if self.gemini_client:
            try:
                resp = self.gemini_client.generate_content(
                    prompt=user_prompt,
                    system_instruction=CUTSHORT_FINANCE_PITCH_PROMPT,
                    max_output_tokens=300,
                )
                if resp and len(resp.strip()) >= 40:
                    return resp.strip().replace("```", "").strip()
            except Exception as e:
                logger.warning(f"Cutshort pitch AI note: {e}")

        return (
            f"Hi {greeting_name},\n\n"
            f"I am excited to apply for the {job_title} role at {clean_company}. "
            f"With an MBA in Finance (2026) and strong foundation in corporate accounting, ratio analysis, financial modeling, and MS Excel, "
            f"I provide rigorous quantitative evaluation and data-driven insights. "
            f"As an immediate joiner (0 days notice), I would welcome the opportunity to connect and discuss how I can contribute to {clean_company}."
        )

    async def _upload_resume_in_modal(self, tailored_pdf_path: str) -> bool:
        """Upload tailored resume PDF in Cutshort application modal."""
        abs_path = os.path.abspath(tailored_pdf_path)
        if not os.path.exists(abs_path):
            return False

        # Clean standard filename for Cutshort S3 signedUrl compatibility
        clean_upload_path = os.path.join(os.path.dirname(abs_path), "Kamal_Kumar_Resume.pdf")
        try:
            shutil.copy2(abs_path, clean_upload_path)
            target_path = clean_upload_path
        except Exception:
            target_path = abs_path

        uploaded = False
        dialog_task = asyncio.create_task(asyncio.to_thread(handle_windows_file_dialog, target_path, 6.0))

        # Click 'Upload another resume' link
        try:
            upload_trigger = self._page.get_by_text("Upload another resume", exact=False)
            if await upload_trigger.count() > 0:
                try:
                    async with self._page.expect_file_chooser(timeout=3500) as fc_info:
                        await self.browser_client.human_click(upload_trigger.first, hover_pause=(0.1, 0.2), post_pause=(0.5, 1.0))
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(target_path)
                    uploaded = True
                except Exception:
                    pass
        except Exception:
            pass

        try:
            await dialog_task
        except Exception:
            pass

        # Fallback file input attach
        if not uploaded:
            try:
                file_inputs = await self._page.query_selector_all("input[type='file']")
                for fi in file_inputs:
                    try:
                        await fi.set_input_files(target_path)
                        uploaded = True
                        break
                    except Exception:
                        pass
            except Exception:
                pass

        # Wait for upload confirmation
        await asyncio.sleep(2.0)
        return uploaded

    async def configure_filters(self):
        """Navigates to Cutshort jobs feed with Finance tags, 0-1 yrs exp, and 1-day hiring activity."""
        self._page = await self.browser_client.ensure_active_page()
        logger.info(f"⚙️ Navigating to Cutshort filtered jobs feed: {CUTSHORT_SEARCH_URL}")
        await self._page.goto(CUTSHORT_SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3.0)

    async def run_auto_apply(
        self,
        target_applied: int = 45,
        max_inspect: int = 60,
    ) -> List[Dict]:
        """
        Extracts and applies to matched jobs on Cutshort.
        """
        all_results = []
        applied_count = 0
        inspected_keys = set()
        consecutive_empty_scrolls = 0
        max_scroll_attempts = 3

        logger.info("\n" + "=" * 65)
        logger.info(f"💜 [CUTSHORT BROWSER AGENT] Starting run (Target: {target_applied} applications, Fresher / 0-1 yrs)")
        logger.info("=" * 65)

        await self.configure_filters()

        while applied_count < target_applied and consecutive_empty_scrolls < max_scroll_attempts:
            self._page = await self.browser_client.ensure_active_page()
            # Count Apply now buttons
            total_cards = await self._page.evaluate("""
                () => {
                    const allButtons = Array.from(document.querySelectorAll("button, a"));
                    return allButtons.filter(b => (b.innerText || '').trim().toLowerCase() === 'apply now').length;
                }
            """)

            if total_cards == 0:
                consecutive_empty_scrolls += 1
                logger.info(f"📜 Scrolling Cutshort feed ({consecutive_empty_scrolls}/{max_scroll_attempts})...")
                await self._page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(3.0)
                continue

            found_new = False
            for card_idx in range(total_cards):
                if applied_count >= target_applied:
                    break

                try:
                    # Click Read more
                    await self._page.evaluate("""
                        (cardIdx) => {
                            const applyButtons = Array.from(document.querySelectorAll("button, a")).filter(b => (b.innerText || '').trim().toLowerCase() === 'apply now');
                            const btn = applyButtons[cardIdx];
                            if (btn) {
                                const card = btn.closest("div.border, div.rounded-lg, div.shadow, div.p-4") || btn.parentElement;
                                if (card) {
                                    const readMore = Array.from(card.querySelectorAll("button, a, span")).find(b => (b.innerText || '').toLowerCase().startsWith('read more'));
                                    if (readMore) readMore.click();
                                }
                            }
                        }
                    """, card_idx)
                    await asyncio.sleep(1.0)

                    # Extract card meta
                    card_meta = await self._page.evaluate("""
                        (cardIdx) => {
                            const applyButtons = Array.from(document.querySelectorAll("button, a")).filter(b => (b.innerText || '').trim().toLowerCase() === 'apply now');
                            const btn = applyButtons[cardIdx];
                            if (!btn) return null;
                            const card = btn.closest("div.border, div.rounded-lg, div.shadow, div.p-4") || btn.parentElement;
                            if (!card) return null;

                            const titleEl = card.querySelector("h1, h2, h3, h4, a[href*='/job/'], div.font-bold");
                            const title = titleEl ? (titleEl.innerText || '').trim().split('\\n')[0] : "Financial Analyst";
                            const fullText = (card.innerText || '').trim();

                            let company = "Company";
                            const compMatch = fullText.match(/Company:\\s*([^\\n\\r]+)/i) || fullText.match(/\\bat\\s+([A-Za-z0-9&.,\\-\\s]{2,40})/i);
                            if (compMatch) company = compMatch[1].trim().split('\\n')[0];

                            let recruiter = "";
                            const recMatch = fullText.match(/Posted by\\s+([^\\n\\r•]+)/i);
                            if (recMatch) recruiter = recMatch[1].replace(/via Cutshort.*/gi, '').trim().split('\\n')[0];

                            return { title: title, company: company, recruiter: recruiter, fullJd: fullText, key: (company + "_" + title).toLowerCase() };
                        }
                    """, card_idx)

                    if not card_meta:
                        continue

                    key = card_meta["key"]
                    if key in inspected_keys:
                        continue

                    inspected_keys.add(key)
                    found_new = True

                    title = card_meta["title"]
                    company = card_meta["company"]
                    recruiter = card_meta["recruiter"]
                    full_jd = card_meta["fullJd"]
                    job_url = self._page.url

                    # Strict Experience Analyzer (0-1 Years Fresher Only)
                    exp_check = FinanceExperienceAnalyzer.analyze(title, full_jd)
                    if not exp_check["eligible"]:
                        continue

                    logger.info(f"\n[{applied_count + 1}/{target_applied}] 🔎 [Cutshort] Processing job: '{title}' @ {company}...")

                    # Click Apply now
                    clicked_apply = await self._page.evaluate("""
                        (cardIdx) => {
                            const applyButtons = Array.from(document.querySelectorAll("button, a")).filter(b => (b.innerText || '').trim().toLowerCase() === 'apply now');
                            const btn = applyButtons[cardIdx];
                            if (btn) { btn.scrollIntoView({ behavior: 'smooth', block: 'center' }); btn.click(); return true; }
                            return false;
                        }
                    """, card_idx)
                    if not clicked_apply:
                        continue

                    await asyncio.sleep(2.0)

                    # Tailor ATS Resume
                    job_dict = {"title": title, "company": company, "description": full_jd}
                    tailored_pdf = self.resume_service.generate_tailored_resume(job=job_dict, portal="cutshort")

                    # Upload resume in modal
                    await self._upload_resume_in_modal(tailored_pdf)

                    # Generate and type recruiter message
                    pitch = self.generate_pitch(company, title, full_jd, recruiter)
                    textarea = await self._page.query_selector("textarea, textarea[placeholder*='message' i]")
                    if textarea and await textarea.is_visible():
                        await self.browser_client.human_type(textarea, pitch)
                        await asyncio.sleep(0.8)

                    send_btn = await self._page.query_selector("button:has-text('Send'), button[type='submit']:has-text('Send')")
                    if self.dry_run:
                        logger.info(f"🧪 [DRY RUN] Prepared Cutshort application for '{title}' @ {company}.")
                        await self._close_modal()
                        applied_count += 1
                        continue

                    if send_btn and await send_btn.is_visible():
                        await self.browser_client.human_click(send_btn, hover_pause=(0.2, 0.4), post_pause=(2.0, 3.0))
                        await asyncio.sleep(2.0)
                        await self._close_modal()

                        applied_count += 1
                        JobTracker.record_job("cutshort", company, title, job_url, status="APPLIED", resume_version=tailored_pdf)
                        all_results.append({"title": title, "company": company, "status": "APPLIED"})
                        logger.info(f"🎉 Successfully applied to '{title}' @ {company} on Cutshort! ({applied_count}/{target_applied})")
                        await asyncio.sleep(3.0)

                except Exception as card_err:
                    logger.debug(f"Cutshort card error: {card_err}")
                    await self._close_modal()

            if applied_count < target_applied:
                if not found_new:
                    consecutive_empty_scrolls += 1
                else:
                    consecutive_empty_scrolls = 0
                await self._page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(2.5)

        logger.info(f"🏁 [Cutshort Complete] Successfully applied to {applied_count}/{target_applied} jobs.")
        return all_results

    async def _close_modal(self):
        """Close open modal."""
        try:
            close_btn = await self._page.query_selector("button[aria-label='Close'], button.close, button:has-text('Cancel')")
            if close_btn and await close_btn.is_visible():
                await close_btn.click()
            else:
                await self._page.keyboard.press("Escape")
        except Exception:
            await self._page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

    async def close(self):
        await self.browser_client.close()
