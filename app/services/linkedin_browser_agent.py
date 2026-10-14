"""
LinkedIn Browser Agent (Agent 3) — Autonomous Chrome DevTools Auto-Apply Agent.

Features:
- Launches / attaches to your active Google Chrome profile ("Profile 7" -> kamal kumar / kamalkumar.doddi@gmail.com).
- Navigates to LinkedIn Jobs with past 24-hour, under 10 applicants, and Easy Apply filters.
- Expands full Job Description, scores candidate match using Gemini.
- If score >= 70%: Dynamically generates an ATS-tailored 1-page PDF resume.
- Automates the Easy Apply modal: uploads tailored resume, fills questionnaires with Gemini AI, and submits application.
"""
import asyncio
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.config.settings import RESUMES_DIR
from app.prompts.form_filler_prompt import FORM_FILLER_SYSTEM_PROMPT, build_form_field_prompt
from app.services.browser_tab_guard import (
    attach_context_blank_tab_monitor,
    clean_and_recover_blank_tabs,
    connect_or_launch_single_chrome,
    is_about_or_blank_url,
    is_blank_url,
)
from app.services.email_service import EmailService
from app.services.form_self_healer import FormSelfHealer
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

# Dedicated Chrome data dir for Agent to enable port 9222 remote debugging
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
AGENT_PROFILE_DATA_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile")
CDP_PORT = 9222


class ExperienceAnalyzer:
    """Analyzes job description to enforce strict experience filtering (0-2 years target) and select resume format."""

    SENIOR_TITLE_PATTERNS = [
        r"\b(?:senior|sr\.?|lead|principal|staff|architect|manager|director|vp|vice\s+president|head\s+of|avp|svp|evp)\b",
        r"\b(?:tech\s*lead|team\s*lead|pod\s*lead|delivery\s*lead|module\s*lead)\b",
        r"\b(?:specialist|engineer|developer|consultant)\s+(?:iii|iv|v|vi|3|4|5|6)\b",
        r"\b(?:level\s*[3-9]|level\s*v|level\s*iv|l[3-9]|band\s*[3-9]|e[3-9])\b",
        r"\b(?:lead\s*(?:i{1,3}|iv|v))\b",
        r"\b(?:[3-9]|\d{2})\s*\+\s*(?:years?|yrs?)\b",
    ]

    MID_EXPERIENCE_PATTERNS = [
        # Explicit 3+ or higher
        r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?|yr)\b",
        # Ranges starting at 3 or higher, or 2 to 4+ years (e.g., 3-5 yrs, 2-5 yrs, 4 to 6 yrs)
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:to|-|–|—)\s*\d+\s*(?:years?|yrs?|yr)\b",
        r"\b2\s*(?:to|-|–|—)\s*([4-9]|\d{2,})\s*(?:years?|yrs?|yr)\b",
        # Minimum / At least 3+ years
        r"\b(?:minimum|min|at\s+least|overall|total|around|above|exceeding|more\s+than|requires?|requiring)\s+(?:of\s+)?([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\b",
        # X years of experience / industry / hands-on / relevant
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)(?:\s+of)?(?:\s+[\w\s]{1,35})?\s+(?:experience|exp|hands-on|industry|relevant)\b",
        r"\b([3-9]|\d{2,})\s*(?:years?|yrs?|yr)\s+(?:experience|exp)\s+(?:required|needed|mandatory|must\s+have)\b",
        r"\b(?:experience|exp)[\s:]*([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\b",
        # Senior / Lead roles mentioned anywhere in JD description body
        r"\b(?:hiring|seeking|looking\s+for|we\s+are\s+hiring|as\s+a)\s+(?:senior|lead|principal|staff|architect|manager)\b",
        r"\b(?:senior|lead|principal|staff|architect)\s+(?:software|platform|backend|frontend|fullstack|data|devops|cloud|systems?|qa|ci\/cd|infrastructure|sre)\s+(?:engineers?|developers?|architects?|specialists?|leads?)\b",
        r"\b(?:senior|lead|principal|staff|architect)\s+(?:engineers?|developers?|architects?|specialists?|consultants?)\b",
    ]

    FRESHER_PATTERNS = [
        r"\b0\s*(?:to|-|–|—)\s*[1-2]\s*(?:years?|yrs?)\b",
        r"\b0\s*\+\s*(?:years?|yrs?)\b",
        r"\b1\s*(?:to|-|–|—)\s*2\s*(?:years?|yrs?)\b",
        r"\b1\s*\+\s*(?:years?|yrs?)\b",
        r"\b2\s*\+\s*(?:years?|yrs?)\b",
        r"\b2\s*(?:years?|yrs?)\b",
        r"\b(?:freshers?|intern|internship|graduate|entry\s*level|junior|associate|trainee)\b",
    ]

    @classmethod
    def analyze_title(cls, job_title: str) -> dict:
        """Fast title screening to reject senior/lead roles."""
        title_lower = (job_title or "").lower()
        for pat in cls.SENIOR_TITLE_PATTERNS:
            m = re.search(pat, title_lower)
            if m:
                matched_kw = m.group(0)
                return {
                    "eligible": False,
                    "reason": f"Title contains senior/lead keyword '{matched_kw}' (exceeds 0-2 yrs)",
                    "exp_years": 0.0,
                }
        return {"eligible": True, "reason": "Title is eligible (0-2 yrs)", "exp_years": 2.0}

    @classmethod
    def analyze(cls, job_title: str, job_description: str) -> dict:
        """
        Criteria:
        - Apply if: 0-2 yrs, 0-1, 1-2, freshers, entry-level, junior, 1+ yrs, 2 yrs, 2+ yrs (strictly <= 2 yrs).
        - Skip if: >= 3 yrs (e.g. 3+ yrs, 3-5 yrs, 4+ yrs, 5+ yrs) or senior/lead/architect in title or description.
        - Fallback: If no explicit high experience mentioned in entire JD, accept as standard entry/mid role with 1.5 yrs template.
        """
        title_lower = (job_title or "").lower()
        desc_lower = (job_description or "").lower()

        # 1. Fast Title Check
        title_res = cls.analyze_title(job_title)
        if not title_res["eligible"]:
            return title_res

        # 2. Check Description for >2 Years Hard Requirements across entire JD body
        for pat in cls.MID_EXPERIENCE_PATTERNS:
            m = re.search(pat, desc_lower)
            if m:
                matched_text = m.group(0)
                # Check if it was part of "0-2 years" or entry level
                if not any(re.search(f_pat, matched_text) for f_pat in cls.FRESHER_PATTERNS):
                    return {
                        "eligible": False,
                        "reason": f"Job description requires '{matched_text}' (exceeds 0-2 yrs)",
                        "exp_years": 0.0,
                    }

        # 3. Check for 2+ Years Signal
        if re.search(r"\b2\s*\+\s*(?:years?|yrs?)", desc_lower) or re.search(r"\b2\s*(?:years?|yrs?)\b", desc_lower):
            return {
                "eligible": True,
                "reason": "Matched 2+ years requirement -> Using 2+ Years Resume Template.",
                "exp_years": 2.0,
            }

        # 4. Check for Fresher / Early Career Signals
        for pat in cls.FRESHER_PATTERNS:
            m = re.search(pat, desc_lower) or re.search(pat, title_lower)
            if m:
                return {
                    "eligible": True,
                    "reason": f"Matched early-career experience signal: '{m.group(0)}'",
                    "exp_years": 1.5,
                }

        # 5. Default fallback: no high experience restriction found in JD
        return {
            "eligible": True,
            "exp_years": 1.5,
            "reason": "Standard developer role (0-2 years eligible) -> Using 1.5 Years Resume Template.",
        }


class LinkedInBrowserAgent:
    """
    Autonomous LinkedIn Chrome Auto-Apply Agent (Agent 3).
    """

    def __init__(
        self,
        chrome_path: str = CHROME_PATH,
        user_data_dir: str = AGENT_PROFILE_DATA_DIR,
        cdp_port: int = CDP_PORT,
        min_score: int = 70,
        dry_run: bool = False,
    ):
        self.chrome_path = chrome_path
        self.user_data_dir = user_data_dir
        self.cdp_port = cdp_port
        self.min_score = min_score
        self.dry_run = dry_run

        self.scoring_service = ScoringService()
        self.resume_service = ResumeService()
        self.email_service = EmailService()
        self.gemini_client = get_gemini_client()

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self.daily_limit_hit = False

    async def _check_daily_limit_reached(self) -> bool:
        """Check if LinkedIn has enforced daily Easy Apply submission limit."""
        if not self._page or self._page.is_closed():
            return False
        try:
            limit_elem = await self._page.query_selector(
                "div:has-text('limit daily submissions'), "
                "p:has-text('limit daily submissions'), "
                "span:has-text('limit daily submissions'), "
                "div:has-text('apply tomorrow'), "
                "p:has-text('Save this job and apply tomorrow'), "
                ".artdeco-inline-feedback:has-text('limit daily submissions'), "
                ".artdeco-toast-item:has-text('limit daily submissions')"
            )
            if limit_elem and await limit_elem.is_visible():
                return True

            has_limit_text = await self._page.evaluate("""
                () => {
                    const bodyText = document.body.innerText || '';
                    return bodyText.includes('We limit daily submissions') || 
                           bodyText.includes('limit daily submissions to maintain quality') ||
                           (bodyText.includes('daily submissions') && bodyText.includes('apply tomorrow'));
                }
            """)
            return bool(has_limit_text)
        except Exception:
            return False

    def is_cdp_port_open(self) -> bool:
        """Check if Chrome debugging port 9222 is already listening."""
        try:
            resp = httpx.get(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1.5)
            return resp.status_code == 200
        except Exception:
            return False

    def _launch_native_chrome(self):
        """Spawns native Google Chrome with remote debugging on port 9222."""
        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ]
        logger.info(f"🚀 Spawning real Google Chrome on port {self.cdp_port}...")
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            logger.warning(f"Note when spawning native Chrome: {e}")

    async def connect(self, context=None, page=None):
        """Connect to live Google Chrome via CDP (Port 9222) in the same window (Rule 2: single Chrome enforced)."""
        if context and page:
            self._context = context
            self._page = page
            self._owns_context = False
            return

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()

        self._context, self._page, self._is_cdp = await connect_or_launch_single_chrome(
            self._playwright,
            cdp_port=self.cdp_port,
            user_data_dir=self.user_data_dir,
            chrome_path=self.chrome_path,
        )

        # Rule 1: Clean any stuck about:blank / about:* tabs and attach context monitor
        self._page, _ = await clean_and_recover_blank_tabs(
            self._context,
            self._page,
            fallback_url="https://www.linkedin.com/jobs/",
            allowed_domains=["linkedin.com"],
            auto_refresh=False,
        )
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url="https://www.linkedin.com/jobs/",
            allowed_domains=["linkedin.com"],
        )

        # Check if LinkedIn session is active
        logger.info("🔍 Checking LinkedIn login status...")
        await self._page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)
        await self._check_and_wait_for_signin()

    async def _check_and_wait_for_signin(self):
        """Check if LinkedIn requires login and pause until the user signs in."""
        for attempt in range(300):
            try:
                current_url = self._page.url.lower()

                # Check for active logged-in indicators on LinkedIn
                is_logged_in = await self._page.query_selector(
                    ".global-nav__me, button[aria-label*='Me'], a[href*='/in/'], img[alt*='Photo of Kamal'], a:has-text('Messaging'), a:has-text('Jobs'), nav.global-nav"
                )
                if is_logged_in and not any(p in current_url for p in ["login", "authwall", "signup", "uas/login"]):
                    if attempt > 0:
                        logger.info("✅ LinkedIn sign-in detected! Resuming agent...")
                    else:
                        logger.info("✅ Logged in to LinkedIn successfully!")
                    return

                # If not logged in yet
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info("🔐  LINKEDIN SIGN-IN REQUIRED!")
                    logger.info("👉  Please log in to your LinkedIn account in the opened Chrome window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email="kamalkumar.doddi@gmail.com",
                                subject="🔐 [ACTION REQUIRED] Please Sign In to LinkedIn",
                                body="Hello Kamal,\n\nThe LinkedIn Auto-Apply Agent requires you to log in.\n\n👉 Please switch to the open Chrome browser window on your computer and sign in.\n\nThe agent will automatically detect that you have signed in and start applying immediately.\n\nBest,\nAI Job Agent"
                            )
                            logger.info("📧 Sent sign-in notification email to kamalkumar.doddi@gmail.com")
                        except Exception as e:
                            logger.warning(f"Could not send sign-in email: {e}")

                await asyncio.sleep(3.0)
            except Exception:
                await asyncio.sleep(2.0)

    def notify_direct_apply_job(
        self,
        job_title: str,
        company: str,
        job_url: str,
        resume_pdf_path: str,
        reason: str = "",
    ):
        """Send email with job link and tailored resume when job has 'Apply on company website'."""
        to_email = "kamalkumar.doddi@gmail.com"
        subject = f"[Direct Apply] {job_title} at {company}"
        body = (
            f"Hello Kamal,\n\n"
            f"The following job requires applying directly on the company website:\n\n"
            f"• Job Title: {job_title}\n"
            f"• Company: {company}\n"
            f"• Experience Match: {reason}\n"
            f"• Direct Job Link: {job_url}\n\n"
            f"Your ATS-tailored 1-page resume has been generated and attached to this email so you can apply directly.\n\n"
            f"Best,\nAI Job Agent"
        )
        try:
            self.email_service.send_email(
                to_email=to_email,
                subject=subject,
                body=body,
                pdf_attachment_path=resume_pdf_path,
            )
            logger.info(f"📧 Sent Direct Apply notification email to {to_email} with attached resume!")
        except Exception as e:
            logger.warning(f"Could not send Direct Apply email: {e}")

    async def answer_form_field(
        self,
        question_text: str,
        field_type: str,
        options: list[str] = None,
        job_title: str = "",
        company: str = "",
        exp_years: float = 2.0,
    ) -> str:
        """Use candidate profile and AI reasoning to intelligently answer application questionnaire fields."""
        q_lower = question_text.lower()

        # Fast rule-based answers (0ms, consumes 0 API calls)
        if "phone" in q_lower or "mobile" in q_lower or "contact" in q_lower:
            return "9398872099"
        if "email" in q_lower:
            return "kamalkumar.doddi@gmail.com"
        if "first name" in q_lower:
            return "Kamal"
        if "last name" in q_lower:
            return "Doddi"
        if "full name" in q_lower or ("name" in q_lower and "company" not in q_lower):
            return "Kamal Doddi"
        if "city" in q_lower or "location" in q_lower or "address" in q_lower:
            return "Hyderabad, India"
        if any(w in q_lower for w in ["relocate", "relocation", "work from", "hybrid", "onsite", "in-office", "commute", "travel", "bengaluru", "bangalore", "pune", "mumbai", "chennai", "noida", "gurgaon", "delhi", "hyderabad"]):
            return "Yes"

        # Notice Period rules
        if "notice" in q_lower or "how soon" in q_lower or "start date" in q_lower or "joining" in q_lower or "period" in q_lower:
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["0 days", "0-15", "0 to 15", "< 15", "15 days", "immediate", "0", "15"]):
                        return opt
                return options[0]
            # For text or numeric input fields, ALWAYS return "0" (numeric)
            # This resolves LinkedIn numeric constraints ("Enter a decimal number larger than 0.0" or whole number)
            return "0"

        if "sponsorship" in q_lower or "visa" in q_lower:
            if "require" in q_lower or "need" in q_lower:
                return "No"
            return "Yes"
        if "authorized" in q_lower or "legally" in q_lower or "eligible to work" in q_lower:
            return "Yes"
        if "years of experience" in q_lower or "how many years" in q_lower or "experience" in q_lower:
            return str(int(exp_years)) if exp_years >= 2.0 else "2"
        if "degree" in q_lower or "education" in q_lower or "qualification" in q_lower:
            # If the field expects a numeric value (e.g. academic score), return GPA
            if field_type in ("number", "tel") or any(w in q_lower for w in ["score", "gpa", "percentage", "marks", "cgpa", "decimal"]):
                return "8.0"
            return "Bachelor's Degree"
        if "gpa" in q_lower or "percentage" in q_lower or "score" in q_lower or "marks" in q_lower or "cgpa" in q_lower or "academic" in q_lower:
            return "8.0"

        # Current CTC rules (Current CTC = 1.4 LPA)
        if "current" in q_lower and any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs", "lac"]):
                return "1.4"
            if any(w in q_lower for w in ["monthly", "per month"]):
                return "12000"
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["1.4", "1-2", "0-2", "1 to 2", "less than 2", "< 2", "140000"]):
                        return opt
            return "140000"

        # Expected CTC rules (Expected CTC = 5 LPA)
        if "expected" in q_lower and any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs", "lac"]):
                return "5"
            if any(w in q_lower for w in ["monthly", "per month"]):
                return "40000"
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["5", "5.0", "4-6", "4 to 6", "500000", "5 lpa"]):
                        return opt
            return "500000"

        # General CTC / Salary (if unspecified)
        if any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs", "lac"]):
                return "5"
            return "500000"

        if "gender" in q_lower:
            return "Male"
        if "disability" in q_lower or "handicap" in q_lower:
            return "No"
        if "veteran" in q_lower:
            return "No"
        if "background" in q_lower or "drug" in q_lower:
            return "Yes"
        if "english" in q_lower or "fluent" in q_lower or "proficiency" in q_lower:
            return "Professional" if "professional" in [o.lower() for o in (options or [])] else "Yes"

        # AI reasoning with multi-agent fallback for complex technical questions
        if self.gemini_client:
            try:
                user_prompt = build_form_field_prompt(
                    question_text=question_text,
                    field_type=field_type,
                    options=options,
                    job_title=job_title,
                    company=company,
                )
                resp = self.gemini_client.generate_content(
                    prompt=user_prompt,
                    system_instruction=FORM_FILLER_SYSTEM_PROMPT,
                    json_mode=True,
                    temperature=0.1,
                    max_output_tokens=256,
                )
                if resp:
                    clean_resp = resp.strip()
                    if "```json" in clean_resp:
                        clean_resp = clean_resp.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_resp:
                        clean_resp = clean_resp.split("```")[1].split("```")[0].strip()

                    try:
                        data = json.loads(clean_resp)
                        answer = str(data.get("answer", "Yes"))
                        logger.info(f"🤖 [AI Form-Filler] '{question_text}' -> '{answer}'")
                        return answer
                    except Exception:
                        m = re.search(r'"answer"\s*:\s*"([^"]+)"', clean_resp)
                        if m:
                            answer = m.group(1).strip()
                            logger.info(f"🤖 [AI Form-Filler (Regex)] '{question_text}' -> '{answer}'")
                            return answer
                        m_num = re.search(r'"answer"\s*:\s*([0-9.]+)', clean_resp)
                        if m_num:
                            answer = str(m_num.group(1)).strip()
                            logger.info(f"🤖 [AI Form-Filler (Num)] '{question_text}' -> '{answer}'")
                            return answer
            except Exception as e:
                logger.warning(f"Form-filler AI fallback error: {e}")

        return "Yes" if "yes" in [o.lower() for o in (options or [])] else "2"

    async def extract_and_apply_jobs(
        self,
        target_applied: int = 20,
        max_inspect_per_page: int = 25,
    ) -> tuple[list[dict], int]:
        """
        Iterate over job cards on the current page using dynamic browser querying (immune to DOM detachment).
        Filters by experience, generates tailored resume, applies via Easy Apply, or emails external apply jobs.
        """
        results = []
        applied_count = 0

        # Dismiss any initial modal overlays or cookie prompts
        try:
            await self._page.keyboard.press("Escape")
            await self._page.evaluate("""
                document.querySelectorAll('.modal__overlay, .artdeco-modal-overlay, .top-level-modal-container, .artdeco-global-alert').forEach(el => {
                    if (el.innerText.includes('Sign in') || el.innerText.includes('cookie') || el.classList.contains('modal__overlay')) {
                        el.remove();
                    }
                });
            """)
        except Exception:
            pass

        # Discover initial count of job cards
        card_count = await self._page.evaluate("""
            () => document.querySelectorAll("li[data-occludable-job-id], div.job-card-container, div[data-job-id], li.jobs-search-results__list-item").length
        """)
        logger.info(f"📋 Discovered {card_count} job listings on current page")

        total_to_inspect = min(card_count if card_count > 0 else max_inspect_per_page, max_inspect_per_page)

        for idx in range(total_to_inspect):
            # Rule 1: Guard against any stuck about:blank or about:* tabs
            search_url = getattr(self, "_current_search_url", "https://www.linkedin.com/jobs/")
            self._page, _ = await clean_and_recover_blank_tabs(
                self._context,
                self._page,
                fallback_url=search_url,
                allowed_domains=["linkedin.com"],
                auto_refresh=False,
            )

            if self.daily_limit_hit:
                logger.warning("⛔ [LinkedIn Daily Limit Reached] Skipping remaining cards on page.")
                break

            if applied_count >= target_applied:
                logger.info(f"🎯 Target of {target_applied} applications reached!")
                break

            # Fast check if daily limit notice is active on page
            if await self._check_daily_limit_reached():
                logger.warning("⛔ [LinkedIn Daily Limit Reached] 'We limit daily submissions to maintain quality and prevent bots. Save this job and apply tomorrow.' detected!")
                logger.info("⏭️ Stopping LinkedIn agent immediately and proceeding to NEXT browser agent (Indeed -> Y Combinator -> Hirist -> Cutshort)...")
                self.daily_limit_hit = True
                break

            try:
                # 1. Scroll container and click the job card dynamically in the live DOM
                click_success = await self._page.evaluate(f"""
                    (i) => {{
                        const container = document.querySelector('.jobs-search-results-list') || document.querySelector('.scaffold-layout__list-container') || window;
                        container.scrollBy(0, 120);
                        const cards = document.querySelectorAll("li[data-occludable-job-id], div.job-card-container, div[data-job-id], li.jobs-search-results__list-item");
                        if (i < cards.length) {{
                            cards[i].scrollIntoView({{ behavior: 'instant', block: 'center' }});
                            // Rule 1: Remove target="_blank" from all links inside card to stay in same tab
                            cards[i].querySelectorAll("a").forEach(a => {{
                                if (a.getAttribute("target") === "_blank") a.removeAttribute("target");
                            }});
                            const link = cards[i].querySelector("a.job-card-list__title, a.job-card-container__link, a");
                            if (link) {{
                                link.removeAttribute("target");
                                link.click();
                            }} else {{
                                cards[i].click();
                            }}
                            return true;
                        }}
                        return false;
                    }}
                """, idx)

                if not click_success:
                    logger.warning(f"Could not click job card {idx + 1} — reaching end of rendered cards")
                    break

                await asyncio.sleep(2.5)

                # Rule 1: If clicking card opened an about tab or secondary window, close it immediately and pick up
                self._page, _ = await clean_and_recover_blank_tabs(
                    self._context,
                    self._page,
                    fallback_url=search_url,
                    allowed_domains=["linkedin.com"],
                    auto_refresh=False,
                )

                # Check if clicking card revealed daily limit feedback
                if await self._check_daily_limit_reached():
                    logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily limit warning displayed on job view!")
                    logger.info("⏭️ Stopping LinkedIn agent immediately and proceeding to NEXT browser agent...")
                    self.daily_limit_hit = True
                    break

                # 2. Extract title & company from details pane
                title_elem = await self._page.query_selector(
                    ".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1.t-24, h2.topcard__title, .jobs-unified-top-card__content--two-pane h1"
                )
                title = (await title_elem.inner_text()).strip() if title_elem else "Unknown Title"

                company_elem = await self._page.query_selector(
                    ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, .jobs-unified-top-card__subtitle-primary-grouping a, a.topcard__org-name-link"
                )
                company = (await company_elem.inner_text()).strip() if company_elem else "Unknown Company"

                logger.info(f"\n[{idx + 1}/{total_to_inspect}] 🔎 Inspecting: '{title}' @ {company}")

                # DEDUPLICATION CHECK: Skip if already applied or emailed
                job_id_match = re.search(r"currentJobId=(\d+)", self._page.url) or re.search(r"/jobs/view/(\d+)", self._page.url)
                current_job_id = job_id_match.group(1) if job_id_match else ""

                if JobTracker.is_applied_or_emailed("linkedin", company, title, current_job_id):
                    logger.info(f"⏭️ Skipping already applied/emailed job: '{title}' @ {company}")
                    continue

                # 3. Expand full JD by clicking "...more" button
                try:
                    expand_btn = await self._page.query_selector(
                        "button.jobs-description__footer-button, button[aria-label*='more'], footer.artdeco-card__actions button, .show-more-less-html__button"
                    )
                    if expand_btn and await expand_btn.is_visible():
                        await expand_btn.click(force=True)
                        await asyncio.sleep(1)
                except Exception:
                    pass

                # 4. Extract full job description text
                desc_selectors = [
                    "#job-details",
                    ".show-more-less-html__markup",
                    ".jobs-description__content",
                    ".jobs-description-content__text",
                    ".jobs-box__html-content",
                    ".jobs-description",
                    ".description__text",
                    "article.jobs-description__container",
                    ".details-pane__content",
                    "section.show-more-less-html",
                    ".jobs-box--fadein",
                ]
                job_desc = ""
                for d_sel in desc_selectors:
                    try:
                        d_elem = await self._page.query_selector(d_sel)
                        if d_elem:
                            txt = (await d_elem.inner_text()).strip()
                            if len(txt) > 40:
                                job_desc = txt
                                break
                    except Exception:
                        pass

                if not job_desc or len(job_desc) < 20:
                    logger.warning("Could not extract job description — skipping")
                    continue

                # 5. Analyze Experience
                analysis = ExperienceAnalyzer.analyze(job_title=title, job_description=job_desc)
                if not analysis["eligible"]:
                    logger.info(f"⏩ Skipping '{title}' — {analysis['reason']}")
                    JobTracker.record_job("linkedin", company, title, current_job_id, status="SKIPPED_EXP", job_url=self._page.url)
                    results.append({"title": title, "company": company, "reason": analysis["reason"], "status": "SKIPPED_EXP"})
                    continue

                exp_years = analysis["exp_years"]
                template_name = "2+ Years Software Engineer" if exp_years >= 2.0 else "1.5 Years Full Stack Developer"
                logger.info(f"✅ Experience Matched: {analysis['reason']}")
                logger.info(f"📑 Selected Resume Template: {template_name} (exp_years={exp_years})")

                # 6. Generate tailored ATS 1-page PDF
                clean_title = re.sub(r"[^\w\-_]", "_", title)[:30]
                clean_comp = re.sub(r"[^\w\-_]", "_", company)[:20]
                job_dict = {
                    "id": f"linkedin_{idx + 1}_{int(time.time())}",
                    "title": title,
                    "company": company,
                    "description": job_desc,
                }
                tailored_pdf_path = self.resume_service.generate_tailored_resume(
                    job=job_dict,
                    candidate_profile={},
                    exp_years=exp_years,
                    portal="linkedin",
                )
                logger.info(f"📄 Tailored ATS PDF Ready ({template_name}): {tailored_pdf_path}")

                # 7. Extract current job URL
                current_page_url = self._page.url
                job_url = current_page_url
                if current_job_id:
                    job_url = f"https://www.linkedin.com/jobs/view/{current_job_id}"

                # 8. Detect Apply Button Type
                # Check if already applied
                already_applied = await self._page.query_selector(
                    ".jobs-s-apply__application-link, span:has-text('Applied'), button:has-text('Applied')"
                )
                if already_applied and await already_applied.is_visible():
                    logger.info(f"ℹ️ Already applied to '{title}' @ {company} — skipping")
                    JobTracker.record_job("linkedin", company, title, current_job_id, status="ALREADY_APPLIED", job_url=job_url)
                    continue

                apply_btn = await self._page.query_selector(
                    ".jobs-apply-button--top-card button, button.jobs-apply-button, .jobs-unified-top-card button[aria-label*='Apply']"
                )
                if not apply_btn or not await apply_btn.is_visible():
                    apply_btn = await self._page.query_selector("button:has-text('Easy Apply'), button:has-text('Apply')")

                if not apply_btn or not await apply_btn.is_visible():
                    # Check if button is missing/disabled because daily limit was reached
                    if await self._check_daily_limit_reached():
                        logger.warning("⛔ [LinkedIn Daily Limit Reached] Easy Apply blocked due to daily limit. Advancing to next portal!")
                        self.daily_limit_hit = True
                        break
                    logger.info("ℹ️ No Apply button found on this post — skipping")
                    JobTracker.record_job("linkedin", company, title, current_job_id, status="NO_APPLY_BUTTON", job_url=job_url)
                    results.append({"title": title, "company": company, "resume": tailored_pdf_path, "status": "NO_APPLY_BUTTON"})
                    continue

                btn_text = ((await apply_btn.inner_text()) or "").strip()
                btn_aria = ((await apply_btn.get_attribute("aria-label")) or "").strip()
                btn_full = f"{btn_text} {btn_aria}".lower()

                # Handle "Apply on company website" (External Apply)
                if "easy apply" not in btn_full:
                    logger.info(f"🌐 Job has '{btn_text}' (External Apply). Sending direct apply email ONCE...")
                    self.notify_direct_apply_job(
                        job_title=title,
                        company=company,
                        job_url=job_url,
                        resume_pdf_path=tailored_pdf_path,
                        reason=analysis["reason"],
                    )
                    JobTracker.record_job("linkedin", company, title, current_job_id, status="EXTERNAL_LINK_EMAILED", job_url=job_url)
                    results.append({
                        "title": title,
                        "company": company,
                        "job_url": job_url,
                        "resume": tailored_pdf_path,
                        "template": template_name,
                        "status": "EXTERNAL_LINK_EMAILED",
                    })
                    continue

                # Handle Easy Apply
                logger.info("🎯 Clicking 'Easy Apply'...")
                await apply_btn.click()
                await asyncio.sleep(2)

                # Check if click exposed daily limit warning
                if await self._check_daily_limit_reached():
                    logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily limit warning detected after clicking Easy Apply!")
                    self.daily_limit_hit = True
                    break

                apply_status = await self._handle_easy_apply_modal(
                    job_title=title,
                    company=company,
                    resume_pdf_path=tailored_pdf_path,
                    exp_years=exp_years,
                )

                if apply_status == "DAILY_LIMIT_REACHED" or self.daily_limit_hit:
                    logger.warning("⛔ [LinkedIn Daily Limit Reached] Exiting LinkedIn immediately!")
                    self.daily_limit_hit = True
                    break

                if apply_status in ("APPLIED", "DRY_RUN_COMPLETED"):
                    applied_count += 1
                    logger.info(f"🎉 Application Recorded! (Total applied: {applied_count}/{target_applied})")

                JobTracker.record_job("linkedin", company, title, current_job_id, status=apply_status, job_url=job_url)
                results.append({
                    "title": title,
                    "company": company,
                    "job_url": job_url,
                    "resume": tailored_pdf_path,
                    "template": template_name,
                    "status": apply_status,
                })

                # Humanized random delay between applications
                delay = random.uniform(3.5, 6.0)
                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing job card {idx + 1}: {e}")

        return results, applied_count

    async def _handle_easy_apply_modal(
        self,
        job_title: str,
        company: str,
        resume_pdf_path: str,
        exp_years: float = 2.0,
    ) -> str:
        """Handle the multi-step LinkedIn Easy Apply popup modal with strict confirmation."""
        # 1. Wait explicitly for the Easy Apply modal to appear
        modal = None
        for _ in range(8):
            if await self._check_daily_limit_reached():
                logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily submission limit detected!")
                self.daily_limit_hit = True
                return "DAILY_LIMIT_REACHED"
            await asyncio.sleep(0.8)
            modal = await self._page.query_selector("div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal")
            if modal and await modal.is_visible():
                break

        if not modal or not await modal.is_visible():
            if await self._check_daily_limit_reached():
                logger.warning("⛔ [LinkedIn Daily Limit Reached] Modal blocked by daily limit!")
                self.daily_limit_hit = True
                return "DAILY_LIMIT_REACHED"
            logger.warning("⚠️ Easy Apply modal did not appear after clicking Easy Apply button.")
            return "MODAL_FAILED_TO_OPEN"

        logger.info("  📋 Easy Apply modal is open! Processing application form...")

        for step in range(1, 12):
            await asyncio.sleep(2.0)

            # Rule 1: Clean any secondary about or popup tabs while keeping modal open
            search_url = getattr(self, "_current_search_url", "https://www.linkedin.com/jobs/")
            self._page, _ = await clean_and_recover_blank_tabs(
                self._context,
                self._page,
                fallback_url=search_url,
                allowed_domains=["linkedin.com"],
                auto_refresh=False,
            )

            # Check if modal is still open
            modal = await self._page.query_selector("div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal")
            if not modal or not await modal.is_visible():
                logger.info("  ✅ Modal closed — application submitted successfully!")
                return "APPLIED"

            # Check for post-apply popups ("Not now", "Done", "Application sent", etc.)
            post_apply_header = await self._page.query_selector(
                ".artdeco-modal:has-text('Application sent'), .artdeco-modal:has-text('Applied'), .artdeco-modal:has-text('Your application was sent'), button:has-text('Not now'), button:has-text('Done')"
            )
            if post_apply_header and await post_apply_header.is_visible():
                logger.info("  🎉 Post-apply confirmation screen detected!")
                await self._dismiss_post_apply_popup()
                await self._dismiss_modal()
                return "APPLIED"

            logger.info(f"  📝 Processing Easy Apply Step {step}...")

            # 1. Upload tailored resume if file upload input is present
            file_inputs = await self._page.query_selector_all("input[type='file']")
            for f_inp in file_inputs:
                if os.path.exists(resume_pdf_path):
                    try:
                        await f_inp.set_input_files(resume_pdf_path)
                        logger.info(f"  ⬆️ Uploaded tailored resume: {os.path.basename(resume_pdf_path)}")
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning(f"  Resume upload note: {e}")

            # 2. Fill text, number, and tel inputs
            text_inputs = await self._page.query_selector_all(
                ".artdeco-modal input[type='text'], .artdeco-modal input[type='number'], .artdeco-modal input[type='tel'], .artdeco-modal textarea"
            )
            for inp in text_inputs:
                try:
                    val = await inp.input_value()
                    if not val:
                        id_attr = await inp.get_attribute("id")
                        # Read the actual input[type] attribute so number fields are handled correctly
                        inp_type = (await inp.get_attribute("type") or "text").strip().lower()
                        label_text = ""
                        if id_attr:
                            label_elem = await self._page.query_selector(f"label[for='{id_attr}']")
                            if label_elem:
                                label_text = await label_elem.inner_text()
                        if not label_text:
                            label_text = (await inp.get_attribute("aria-label")) or "Experience or detail"

                        answer = await self.answer_form_field(
                            question_text=label_text,
                            field_type=inp_type,  # 'number', 'text', 'tel' — from actual HTML attribute
                            job_title=job_title,
                            company=company,
                            exp_years=exp_years,
                        )
                        await inp.fill(str(answer))
                        await asyncio.sleep(0.5)

                        # ── Post-fill validation error detection ────────────────────
                        # If the browser shows a type-mismatch error (e.g. "Enter a
                        # decimal number larger than 0.0"), detect it and re-fill with
                        # the correct numeric value instead of re-throwing.
                        try:
                            err_el = await self._page.query_selector(
                                ".artdeco-inline-feedback--error, "
                                ".fb-form-element__error-text, "
                                "[data-test-form-element-error], "
                                "span[class*='error'], div[class*='error-message']"
                            )
                            if err_el and await err_el.is_visible():
                                err_msg = (await err_el.inner_text()).strip().lower()
                                logger.info(f"  ⚠️ [Field Error] '{label_text[:50]}' → Error: '{err_msg}'")

                                # Re-fill with appropriate numeric value based on error type
                                if any(kw in err_msg for kw in ["decimal", "number", "numeric", "digit", "integer", "larger than"]):
                                    q_l = label_text.lower()
                                    if any(w in q_l for w in ["score", "gpa", "cgpa", "percentage", "marks", "academic", "degree"]):
                                        corrected = "8.0"
                                    elif any(w in q_l for w in ["salary", "ctc", "package", "compensation"]):
                                        corrected = "500000"
                                    elif any(w in q_l for w in ["experience", "years"]):
                                        corrected = str(int(exp_years)) if exp_years >= 1 else "2"
                                    elif any(w in q_l for w in ["notice", "joining", "start"]):
                                        corrected = "0"
                                    else:
                                        corrected = "2"
                                    logger.info(f"  🔧 [Auto-Correct] '{label_text[:50]}' re-filled with '{corrected}' (was '{answer}')")
                                    await inp.triple_click()
                                    await inp.fill(corrected)
                                    await asyncio.sleep(0.4)
                        except Exception:
                            pass
                except Exception:
                    pass

            # 3. Handle dropdown selections (select elements & custom dropdowns)
            selects = await self._page.query_selector_all(".artdeco-modal select")
            for sel in selects:
                try:
                    options = await sel.query_selector_all("option")
                    opt_texts = [await opt.inner_text() for opt in options]
                    id_attr = await sel.get_attribute("id")
                    label_text = ""
                    if id_attr:
                        lbl = await self._page.query_selector(f"label[for='{id_attr}']")
                        if lbl:
                            label_text = await lbl.inner_text()
                    answer = await self.answer_form_field(
                        question_text=label_text or "Select option",
                        field_type="select",
                        options=opt_texts,
                        job_title=job_title,
                        company=company,
                        exp_years=exp_years,
                    )
                    matched_val = None
                    for opt in options:
                        o_txt = (await opt.inner_text()).strip().lower()
                        o_val = await opt.get_attribute("value")
                        if answer.lower() == o_txt or answer.lower() in o_txt or (o_val and answer.lower() == o_val.lower()):
                            matched_val = o_val
                            break
                    if not matched_val and len(options) > 1:
                        for opt in options:
                            o_txt = (await opt.inner_text()).strip().lower()
                            if "yes" in o_txt or "bachelor" in o_txt or "india" in o_txt or "immediate" in o_txt:
                                matched_val = await opt.get_attribute("value")
                                break
                        if not matched_val:
                            matched_val = await options[1].get_attribute("value")

                    if matched_val:
                        await sel.select_option(value=matched_val)
                        await sel.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", matched_val)
                        logger.info(f"  ✨ [Dropdown Selected] '{label_text}' -> '{matched_val}'")
                except Exception as e:
                    logger.warning(f"Dropdown selection note: {e}")

            # 4. Check for radio buttons (Robust label and input clicking)
            fieldsets = await self._page.query_selector_all(".artdeco-modal fieldset, .artdeco-modal [data-test-form-builder-radio-button-form-component='true']")
            for fs in fieldsets:
                try:
                    legend = await fs.query_selector("legend, label, span.fb-form-element-label")
                    legend_text = (await legend.inner_text()) if legend else ""
                    radios = await fs.query_selector_all("input[type='radio']")
                    labels = await fs.query_selector_all("label")

                    if radios or labels:
                        radio_texts = [(await r.get_attribute("value") or "") for r in radios] + [(await l.inner_text()).strip() for l in labels]
                        answer = await self.answer_form_field(
                            question_text=legend_text,
                            field_type="radio",
                            options=radio_texts,
                            job_title=job_title,
                            company=company,
                            exp_years=exp_years,
                        )

                        clicked = False
                        # Try clicking matching label first (most reliable on LinkedIn)
                        for lbl in labels:
                            l_txt = (await lbl.inner_text()).strip().lower()
                            if (answer.lower() == "yes" and "yes" in l_txt) or (answer.lower() == "no" and "no" in l_txt) or (answer.lower() in l_txt):
                                await lbl.scroll_into_view_if_needed()
                                await lbl.click(force=True)
                                logger.info(f"  ✨ [Radio Clicked] '{legend_text}' -> '{l_txt}'")
                                clicked = True
                                break
                        if not clicked and radios:
                            for r in radios:
                                r_val = (await r.get_attribute("value") or "").lower()
                                if (answer.lower() == "yes" and "yes" in r_val) or (answer.lower() == "no" and "no" in r_val) or (answer.lower() in r_val):
                                    await r.evaluate("(el) => { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('click', { bubbles: true })); }")
                                    logger.info(f"  ✨ [Radio Checked] '{legend_text}' -> '{r_val}'")
                                    clicked = True
                                    break
                        if not clicked and labels:
                            await labels[0].click(force=True)
                except Exception as e:
                    logger.warning(f"Radio selection note: {e}")

            # 5. Check for checkboxes (terms, disclosures)
            checkboxes = await self._page.query_selector_all(".artdeco-modal input[type='checkbox']")
            for cb in checkboxes:
                try:
                    if not await cb.is_checked():
                        await cb.check()
                except Exception:
                    pass

            # 6. Check for Submit button
            submit_btn = await self._page.query_selector(
                "button[aria-label*='Submit application'], button.artdeco-button--primary:has-text('Submit application'), button:has-text('Submit')"
            )
            if submit_btn and await submit_btn.is_visible():
                if self.dry_run:
                    logger.info("  🧪 [DRY RUN] Ready to Submit! (Dry run enabled — skipping final click)")
                    await self._dismiss_modal()
                    return "DRY_RUN_COMPLETED"
                else:
                    logger.info("  🚀 Submitting final application...")
                    await submit_btn.click()
                    await asyncio.sleep(2.5)

                    # 1. First check if submission succeeded or post-apply popup appeared (e.g., 'Not now', 'Done', Cross X icon)
                    post_handled = await self._dismiss_post_apply_popup()
                    modal_check = await self._page.query_selector("div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal")
                    post_apply_txt = await self._page.query_selector(
                        ".artdeco-modal:has-text('Application sent'), .artdeco-modal:has-text('Applied'), .artdeco-modal:has-text('Your application was sent'), div:has-text('Application sent')"
                    )

                    if not modal_check or not await modal_check.is_visible() or post_handled or post_apply_txt:
                        logger.info("  🎉 Application submitted successfully!")
                        await self._dismiss_modal()
                        return "APPLIED"

                    # 2. Only if the modal is still open and inputs have real errors, trigger healer
                    if await FormSelfHealer.has_validation_errors(self._page):
                        await FormSelfHealer.heal_errors(
                            page=self._page,
                            portal_name="linkedin",
                            step_num=step,
                            job_title=job_title,
                            company=company,
                            gemini_client=self.gemini_client,
                        )
                        re_submit = await self._page.query_selector(
                            "button[aria-label*='Submit application'], button.artdeco-button--primary:has-text('Submit application'), button:has-text('Submit')"
                        )
                        if re_submit and await re_submit.is_visible():
                            await re_submit.click()
                            await asyncio.sleep(2.5)
                            await self._dismiss_post_apply_popup()

                    await self._dismiss_modal()
                    return "APPLIED"

            # 7. Check for Review button
            review_btn = await self._page.query_selector(
                "button[aria-label*='Review your application'], button.artdeco-button--primary:has-text('Review')"
            )
            if review_btn and await review_btn.is_visible():
                await review_btn.click()
                await asyncio.sleep(1.5)
                # Check for validation errors on Review click
                if await FormSelfHealer.has_validation_errors(self._page):
                    await FormSelfHealer.heal_errors(
                        page=self._page,
                        portal_name="linkedin",
                        step_num=step,
                        job_title=job_title,
                        company=company,
                        gemini_client=self.gemini_client,
                    )
                    await review_btn.click()
                    await asyncio.sleep(1.5)
                continue

            # 8. Check for Next button
            next_btn = await self._page.query_selector(
                "button[aria-label*='Continue to next step'], button.artdeco-button--primary:has-text('Next')"
            )
            if next_btn and await next_btn.is_visible():
                await next_btn.click()
                await asyncio.sleep(1.5)
                # Check if validation errors blocked moving to next step
                if await FormSelfHealer.has_validation_errors(self._page):
                    await FormSelfHealer.heal_errors(
                        page=self._page,
                        portal_name="linkedin",
                        step_num=step,
                        job_title=job_title,
                        company=company,
                        gemini_client=self.gemini_client,
                    )
                    # Re-click Next
                    re_next = await self._page.query_selector(
                        "button[aria-label*='Continue to next step'], button.artdeco-button--primary:has-text('Next')"
                    )
                    if re_next and await re_next.is_visible():
                        await re_next.click()
                        await asyncio.sleep(1.5)
                continue

        # If stuck after max steps, dismiss modal safely
        await self._dismiss_modal()
        return "INCOMPLETE"

    async def _dismiss_post_apply_popup(self) -> bool:
        """Dismiss post-submission popups like 'Not now', 'Done', 'No thanks', 'Got it', or Cross (X) icon."""
        dismissed = False
        try:
            for selector in [
                "button:has-text('Not now')",
                "button[aria-label*='Not now']",
                "button:has-text('No thanks')",
                "button:has-text('Done')",
                "button[aria-label*='Done']",
                "button:has-text('Got it')",
                "button.artdeco-modal__dismiss",
                "button[aria-label='Dismiss']",
                "button[aria-label='Close']",
                "button.artdeco-toast-item__dismiss",
            ]:
                btns = await self._page.query_selector_all(selector)
                for btn in btns:
                    if await btn.is_visible():
                        txt = ((await btn.inner_text()) or "").strip()
                        aria = (await btn.get_attribute("aria-label")) or ""
                        await btn.click(force=True)
                        logger.info(f"  ✨ Dismissed post-apply popup ({txt or aria or 'Cross icon'})")
                        dismissed = True
                        await asyncio.sleep(0.8)
                        break
        except Exception as e:
            logger.warning(f"Note during post-apply popup dismissal: {e}")
        return dismissed

    async def _dismiss_modal(self):
        """Close Easy Apply modal safely and handle any 'Not now', 'Done', or cross icons."""
        try:
            # 1. Try post-apply dismiss buttons first
            await self._dismiss_post_apply_popup()

            # 2. Try closing modal with close/dismiss cross buttons
            for sel in [
                "button[aria-label='Dismiss']",
                "button.artdeco-modal__dismiss",
                "button[aria-label='Close']",
                "button:has-text('Done')",
                "button:has-text('Not now')",
            ]:
                btn = await self._page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(0.8)

            # 3. If discard confirmation dialog appears, confirm Discard
            discard_btn = await self._page.query_selector(
                "button[data-control-name='discard_application_confirm_btn'], button.artdeco-button--primary:has-text('Discard'), button:has-text('Discard')"
            )
            if discard_btn and await discard_btn.is_visible():
                await discard_btn.click(force=True)
                await asyncio.sleep(0.8)
        except Exception:
            pass

    async def close(self):
        """Safely disconnect or close browser resources without terminating the single Chrome instance."""
        try:
            if self._context:
                for p in list(self._context.pages):
                    if p != self._page:
                        try:
                            await p.close()
                        except Exception:
                            pass
            if hasattr(self, "_is_cdp") and not self._is_cdp:
                if self._context:
                    await self._context.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("🔌 Cleanly disconnected LinkedIn browser session (single Chrome preserved).")
        except Exception:
            pass


RESUME_MATCHING_ROLES = [
    "Java Backend Developer",
    "Java Full Stack Developer",
    "Spring Boot Developer",
    "Java Developer",
    "Junior Software Engineer",
    "Python Backend Developer",
    "AI Agent Developer",
    "Generative AI Engineer",
    "AWS Cloud Engineer",
]


async def run_linkedin_auto_apply(
    keyword: str = None,
    keywords: list[str] = None,
    location: str = "India",
    target_applied: int = 40,
    max_jobs: int = 30,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run LinkedIn Browser Auto-Apply Agent (Agent 3) across multiple matching resume search roles
    until target_applied count (40-50 applications) or daily limit is reached.
    """
    search_roles = []
    if keywords:
        search_roles = list(keywords)
    elif keyword:
        search_roles = [keyword] + [r for r in RESUME_MATCHING_ROLES if r.lower() != keyword.lower()]
    else:
        search_roles = list(RESUME_MATCHING_ROLES)

    agent = LinkedInBrowserAgent(dry_run=dry_run)
    all_results = []
    total_applied = 0

    try:
        await agent.connect()

        for role_idx, current_keyword in enumerate(search_roles, 1):
            if total_applied >= target_applied:
                logger.info(f"🎯 Total portal session target of {target_applied} applications reached on LinkedIn (applied: {total_applied})! Moving to next browser agent...")
                break

            logger.info(f"\n{'#'*65}\n🎯 [ROLE {role_idx}/{len(search_roles)}] Searching LinkedIn for: '{current_keyword}' ({location}) [Target: {target_applied} applied]\n{'#'*65}")

            role_applied = 0
            page_num = 0
            while role_applied < target_applied and total_applied < target_applied and page_num < 5:
                start_offset = page_num * 25
                logger.info(f"\n📄 [LinkedIn: '{current_keyword}'] Page {page_num + 1} (start={start_offset})...")

                url = (
                    f"https://www.linkedin.com/jobs/search/?"
                    f"keywords={quote_plus(current_keyword)}&"
                    f"location={quote_plus(location)}&"
                    f"f_TPR=r86400&"
                    f"f_AL=true&"
                    f"sortBy=DD&"
                    f"start={start_offset}"
                )
                agent._current_search_url = url
                await agent._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(4)
                await agent._check_and_wait_for_signin()

                results, applied_on_page = await agent.extract_and_apply_jobs(
                    target_applied=target_applied - total_applied,
                    max_inspect_per_page=max_jobs,
                )
                all_results.extend(results)
                role_applied += applied_on_page
                total_applied += applied_on_page
                page_num += 1

                if total_applied >= target_applied:
                    logger.info(f"🎯 Target of {target_applied} applications reached on LinkedIn! Advancing to next portal...")
                    break

                if not results:
                    logger.info(f"🛑 No more jobs discovered on page {page_num} for '{current_keyword}'.")
                    break

                if agent.daily_limit_hit:
                    logger.warning(f"⛔ [LinkedIn Daily Limit Active] Halting LinkedIn pagination early after {total_applied} applications.")
                    break

            if agent.daily_limit_hit:
                logger.warning(f"⛔ [LinkedIn Daily Limit Active] Skipping remaining {len(search_roles) - role_idx} LinkedIn roles. Transitioning to next browser agent immediately!")
                break

            logger.info(f"✅ Completed search for role [{role_idx}/{len(search_roles)}] '{current_keyword}'. Applied: {role_applied}. (Total session applied: {total_applied}/{target_applied})")

        logger.info(f"\n🏆 LinkedIn Sweep Complete! Total Applications Submitted: {total_applied}" + (" (Daily limit reached — moving to next agent)" if agent.daily_limit_hit else ""))
        return all_results
    finally:
        await agent.close()
