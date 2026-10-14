"""
Indeed Job Board Auto-Apply Browser Agent.
Automates live searching, 0-2 yrs experience filtering, tailored ATS PDF resume generation (resumes/indeed/),
and auto-submitting on-site applications via 'Apply with Indeed' / 'Easily apply' or emailing external application links.
Features:
  - Real Google Chrome CDP (Remote Debugging Port 9222) connection for true native browser integrity & Cloudflare avoidance.
  - Permanent authenticated session persistence via dedicated AgentProfile user-data-dir.
  - Multi-Role Sequential Sweep across all matching resume roles (Java Backend, Full Stack, Spring Boot, Python, AI Agent, Cloud).
  - Per-Role target application limits without premature browser closing.
  - Upfront Title-First Screening + Multi-Source JD extraction (Hydrated DOM, JSON-LD Schema, Qualifications, Snippets).
  - Direct email notification alerts when CAPTCHA / Human Challenge or Sign-in is required.
  - Automatic sign-in and human verification pause and detection.
  - Human-like interaction emulation (smooth scrolling, cursor movement, natural typing cadence, and realistic pacing).
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

from app.config.settings import JOB_BOARD_EMAIL, JOB_BOARD_PASSWORD
from app.services.browser_tab_guard import (
    attach_context_blank_tab_monitor,
    clean_and_recover_blank_tabs,
    connect_or_launch_single_chrome,
    is_blank_url,
)
from app.services.email_service import EmailService
from app.services.form_self_healer import FormSelfHealer
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

FORM_FILLER_SYSTEM_PROMPT = """You are an autonomous job application form-filler assistant for candidate Doddi Kamal Kumar.
Candidate Details:
- Name: Doddi Kamal Kumar (Kamal Doddi)
- Email: kamalkumar.doddi@gmail.com
- Phone: +91-9398872099 / 9398872099
- Current Location: Hyderabad, India
- Open to Relocation: Yes, immediately open to relocate anywhere (Bengaluru, Bangalore, Pune, Mumbai, Chennai, Gurgaon, Delhi, Noida, etc.)
- Work Mode: Open to Hybrid, Onsite, and Remote work
- Notice Period: Immediate joiner (0 days / 0-15 days)
- Experience: 1.5 - 2+ years of professional backend engineering experience in Java, Spring Boot, Microservices, REST APIs, Python, AI Agents
- Degree: Bachelor of Technology (B.Tech in Computer Science / Engineering), graduated with 8.0 GPA
- Work Authorization: Legally authorized to work in India (Citizen). Does not require visa sponsorship.
- Expected Salary / CTC: 5 LPA (500000 INR)
- Current Salary / CTC: 1.4 LPA (140000 INR)

Instructions:
Reply with ONLY a strict JSON object: {"answer": "<concise answer>"}
"""


def build_form_field_prompt(
    question_text: str,
    field_type: str,
    options: list[str] = None,
    job_title: str = "",
    company: str = "",
) -> str:
    prompt = f"Question: {question_text}\nField Type: {field_type}\nJob Title: {job_title}\nCompany: {company}\n"
    if options:
        prompt += f"Available Options: {options}\nSelect the single best matching option from the list.\n"
    prompt += "Provide the most appropriate answer strictly matching Kamal Kumar's profile in JSON: {\"answer\": \"<value>\"}"
    return prompt


class IndeedExperienceAnalyzer:
    """Strict Experience filter for Indeed job postings (0-2 years target)."""

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
        """Fast 0ms title screening to reject senior/lead roles before right pane loading."""
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

        # 3. Check for Fresher / Early Career Signals
        for pat in cls.FRESHER_PATTERNS:
            m = re.search(pat, desc_lower) or re.search(pat, title_lower)
            if m:
                return {
                    "eligible": True,
                    "reason": f"Matched early-career experience signal: '{m.group(0)}'",
                    "exp_years": 1.5,
                }

        # Default eligible for standard junior/general roles
        return {
            "eligible": True,
            "reason": "Standard experience range (0-2 years eligible)",
            "exp_years": 2.0,
        }


class IndeedBrowserAgent:
    """Automated Browser Agent for Indeed India (in.indeed.com) with Real Chrome CDP Connection & Humanized Behavior."""

    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        chrome_path: Optional[str] = None,
        cdp_port: int = 9222,
        dry_run: bool = False,
    ):
        self.user_data_dir = user_data_dir or os.path.expandvars(
            r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile"
        )
        self.chrome_path = chrome_path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        self.cdp_port = cdp_port
        self.dry_run = dry_run

        self.resume_service = ResumeService()
        self.email_service = EmailService()
        self.gemini_client = get_gemini_client()

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._owns_context = True
        self._is_cdp = False
        self._last_mouse_x = 400.0
        self._last_mouse_y = 400.0

    def is_cdp_port_open(self) -> bool:
        """Check if Chrome debugging port 9222 is already open."""
        try:
            resp = httpx.get(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1.5)
            return resp.status_code == 200
        except Exception:
            return False

    def _launch_native_chrome(self):
        """Launch native Google Chrome process with remote debugging port 9222 and persistent profile."""
        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ]
        logger.info(f"🚀 Spawning real Google Chrome with persistent profile on port {self.cdp_port}...")
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            logger.warning(f"Note when spawning native Chrome: {e}")

    async def connect(self, context=None, page=None):
        """Connect to real Google Chrome via CDP (Port 9222) or persistent browser context."""
        if context and page:
            self._context = context
            self._page = page
            self._owns_context = False
            logger.info("🔄 Using existing Chrome browser context for Indeed...")
            return

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        self._context, self._page, self._is_cdp = await connect_or_launch_single_chrome(
            self._playwright,
            cdp_port=self.cdp_port,
            user_data_dir=self.user_data_dir,
            chrome_path=self.chrome_path,
        )

        # Apply stealth overrides
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'hi'],
            });
        """)

        # Clean any stuck about:blank tabs and attach context monitor
        self._page, _ = await clean_and_recover_blank_tabs(self._context, self._page, fallback_url="https://in.indeed.com/")
        attach_context_blank_tab_monitor(self._context, lambda: self._page, default_portal_url="https://in.indeed.com/")

        # Check Indeed status & verify logged-in account
        logger.info("🔍 Checking Indeed session & account login status...")
        await self._page.goto("https://in.indeed.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._check_and_wait_for_human_challenge()
        await self._check_and_wait_for_signin()

    # -------------------------------------------------------------------------
    # HUMAN-LIKE BEHAVIOR EMULATION HELPERS
    # -------------------------------------------------------------------------
    async def _human_move_to(self, target_x: float, target_y: float, steps: int = 6):
        """Move mouse naturally towards target with intermediate curve steps and micro-jitter."""
        try:
            start_x = self._last_mouse_x or random.randint(300, 700)
            start_y = self._last_mouse_y or random.randint(300, 600)

            for i in range(1, steps + 1):
                t = i / steps
                # Bezier-like curve with slight random deviation
                cur_x = start_x + (target_x - start_x) * t + random.uniform(-4, 4) * (1 - t)
                cur_y = start_y + (target_y - start_y) * t + random.uniform(-4, 4) * (1 - t)
                await self._page.mouse.move(cur_x, cur_y)
                await asyncio.sleep(random.uniform(0.015, 0.04))

            await self._page.mouse.move(target_x, target_y)
            self._last_mouse_x = target_x
            self._last_mouse_y = target_y
        except Exception:
            pass

    async def _human_scroll(self, delta_y: int = 300, steps: int = 5):
        """Smooth human-like scrolling with micro-jitter and natural pacing."""
        try:
            step_size = delta_y / max(steps, 1)
            for _ in range(steps):
                jitter = random.uniform(-15, 15)
                await self._page.mouse.wheel(0, step_size + jitter)
                await asyncio.sleep(random.uniform(0.04, 0.08))
        except Exception:
            pass

    async def _human_click(
        self,
        element,
        hover_pause: tuple[float, float] = (0.2, 0.45),
        click_delay: tuple[int, int] = (65, 125),
        post_pause: tuple[float, float] = (0.4, 0.8),
    ):
        """Move mouse naturally to element, hover briefly, and click with realistic mouse down delay."""
        try:
            if not element:
                return
            await element.scroll_into_view_if_needed()
            box = await element.bounding_box()
            if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
                target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                await self._human_move_to(target_x, target_y)
                await asyncio.sleep(random.uniform(*hover_pause))
                await self._page.mouse.click(target_x, target_y, delay=random.randint(*click_delay))
            else:
                await asyncio.sleep(random.uniform(*hover_pause))
                await element.click(delay=random.randint(*click_delay))
            await asyncio.sleep(random.uniform(*post_pause))
        except Exception:
            try:
                await element.click(force=True)
            except Exception:
                pass

    async def _human_type(self, element, text: str):
        """Naturally focus an input field and type characters with human cadence (35-95ms)."""
        try:
            if not element:
                return
            await self._human_click(element, hover_pause=(0.1, 0.25), post_pause=(0.15, 0.3))
            # Clear existing content if any
            await self._page.keyboard.press("Control+A")
            await asyncio.sleep(random.uniform(0.05, 0.12))
            await self._page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.08, 0.15))

            for ch in str(text):
                await self._page.keyboard.type(ch)
                delay = random.uniform(0.035, 0.095)
                if ch in (" ", ".", "@", "_", "-"):
                    delay += random.uniform(0.04, 0.1)
                await asyncio.sleep(delay)
            await asyncio.sleep(random.uniform(0.2, 0.45))
        except Exception:
            try:
                await element.fill(str(text))
            except Exception:
                pass

    async def _check_and_wait_for_human_challenge(self):
        """
        Check if Indeed has presented a human verification or Cloudflare challenge.
        1. Immediately opens a 2nd tab beside the 1st tab to https://in.indeed.com/.
        2. In that 2nd tab, locates the 'Verify you are human' checkbox and moves the cursor to click it.
        3. Waits until verified, clicks 'Return home' or navigates to Indeed home, and closes the 2nd tab.
        4. Refreshes the 1st tab to continue searching.
        5. If still not cleared, sends an email alert to the user.
        """
        try:
            page_text = (await self._page.inner_text("body") if await self._page.query_selector("body") else "").lower()
            page_title = (await self._page.title()).lower()

            has_challenge = any(phrase in page_text or phrase in page_title for phrase in [
                "verify you are human", "security check", "cloudflare",
                "checking your browser", "challenge-platform", "enable javascript and cookies",
                "press & hold", "press and hold", "just a moment", "additional verification", "additional verification required"
            ]) and not await self._page.query_selector("div.job_seen_beacon, div.cardOutline")

            if not has_challenge:
                return

            logger.info("\n" + "=" * 68)
            logger.info("⚠️  INDEED HUMAN VERIFICATION / CAPTCHA DETECTED!")
            logger.info("🤖  Opening 2nd tab beside 1st tab to solve verification with natural cursor movement...")
            logger.info("=" * 68 + "\n")

            # 1. Open 2nd tab immediately to solve challenge
            for attempt_idx in range(1, 3):
                new_tab = None
                try:
                    if self._context:
                        new_tab = await self._context.new_page()
                    else:
                        new_tab = await self._page.context.new_page()

                    logger.info(f"📑 [Attempt {attempt_idx}/2] Opened 2nd tab beside 1st tab. Navigating to Indeed...")
                    await new_tab.goto("https://in.indeed.com/", wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(3.5)

                    # Search for verification checkbox on 2nd tab across main page and all iframes
                    clicked_box = False
                    active_tab_containers = [new_tab] + new_tab.frames
                    for frame in active_tab_containers:
                        try:
                            cf_box = await frame.query_selector(
                                "input[type='checkbox'], span.mark, .ctp-checkbox-label, div#challenge-stage input, #cf-stage input, button:has-text('Verify'), div.cb-c input, .cf-turnstile-wrapper, div[class*='turnstile']"
                            )
                            if cf_box and await cf_box.is_visible():
                                logger.info("👆 [2nd Tab] Moving physical mouse cursor to click verification checkbox...")
                                await cf_box.scroll_into_view_if_needed()
                                box = await cf_box.bounding_box()
                                if box and box.get("width", 0) > 0:
                                    tx = box["x"] + box["width"] * random.uniform(0.4, 0.6)
                                    ty = box["y"] + box["height"] * random.uniform(0.4, 0.6)
                                    await new_tab.mouse.move(tx, ty, steps=7)
                                    await asyncio.sleep(random.uniform(0.3, 0.6))
                                    await new_tab.mouse.click(tx, ty, delay=random.randint(90, 150))
                                else:
                                    await cf_box.click(delay=random.randint(90, 150))
                                clicked_box = True
                                logger.info("✅ [2nd Tab] Clicked verification checkbox! Waiting for verification to process...")
                                await asyncio.sleep(5.0)
                                break
                        except Exception as click_err:
                            logger.debug(f"2nd tab checkbox click note: {click_err}")

                    if not clicked_box:
                        try:
                            iframe_el = await new_tab.query_selector("iframe[src*='cloudflare'], iframe[src*='challenges']")
                            if iframe_el and await iframe_el.is_visible():
                                logger.info("👆 [2nd Tab] Moving cursor to click inside challenge iframe...")
                                await iframe_el.scroll_into_view_if_needed()
                                ibox = await iframe_el.bounding_box()
                                if ibox:
                                    await new_tab.mouse.click(ibox["x"] + 30, ibox["y"] + 30, delay=120)
                                    await asyncio.sleep(4.5)
                        except Exception:
                            pass

                    # Wait till verified on 2nd tab
                    logger.info("⏳ [2nd Tab] Waiting till verification completes...")
                    await asyncio.sleep(4.0)

                    # Look for and click 'Return home' / 'Back to home' button on 2nd tab
                    home_btn = await new_tab.query_selector(
                        "button:has-text('Return home'), a:has-text('Return home'), button:has-text('Back to home'), a:has-text('Back to home'), button:has-text('Go to homepage'), a:has-text('Go to homepage'), a[data-gnav-element-name='Home'], a.gnav-logo"
                    )
                    if home_btn and await home_btn.is_visible():
                        btn_txt = ((await home_btn.inner_text()) or "Return home").strip()
                        logger.info(f"👆 [2nd Tab] Moving manual cursor to click '{btn_txt}' button...")
                        await home_btn.scroll_into_view_if_needed()
                        await self._human_click(home_btn, hover_pause=(0.2, 0.4), post_pause=(1.5, 2.5))
                    else:
                        logger.info("🌐 [2nd Tab] Navigating to Indeed home page...")
                        await new_tab.goto("https://in.indeed.com/", wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(2.0)

                    logger.info("🚪 [2nd Tab] Verification complete on 2nd tab. Closing 2nd tab...")
                    await new_tab.close()
                    new_tab = None

                    # Switch back to 1st tab and refresh it
                    logger.info("🔄 Bringing 1st tab to front and refreshing page...")
                    await self._page.bring_to_front()
                    await asyncio.sleep(1.0)
                    await self._page.reload(wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(3.5)

                    # Check if challenge has cleared on 1st tab
                    p_text_now = (await self._page.inner_text("body") if await self._page.query_selector("body") else "").lower()
                    p_title_now = (await self._page.title()).lower()
                    is_still_challenge = any(phrase in p_text_now or phrase in p_title_now for phrase in [
                        "verify you are human", "security check", "cloudflare", "checking your browser", "additional verification"
                    ]) and not await self._page.query_selector("div.job_seen_beacon, div.cardOutline, #jobDescriptionText, [data-testid='JobCard']")

                    if not is_still_challenge:
                        logger.info("✅ 1st tab verification cleared! Resuming Indeed search & application sweep...")
                        return

                except Exception as tab_err:
                    logger.warning(f"2nd tab verification attempt note: {tab_err}")
                    if new_tab and not new_tab.is_closed():
                        try:
                            await new_tab.close()
                        except Exception:
                            pass

            # 2. If still not cleared after 2 automatic attempts, send email alert and pause for user
            logger.info("📧 Sending alert email to kamalkumar.doddi@gmail.com and waiting for manual solve...")
            try:
                self.email_service.send_email(
                    to_email="kamalkumar.doddi@gmail.com",
                    subject="🚨 [ACTION REQUIRED] Please Solve CAPTCHA / Human Verification on Indeed",
                    body="Hello Kamal,\n\nThe Indeed Auto-Apply Agent has encountered a Human Verification / Cloudflare CAPTCHA check.\n\n👉 Please switch to the open Google Chrome window on your computer and solve the verification.\n\nBest,\nAI Job Agent"
                )
            except Exception as e:
                logger.warning(f"Could not send CAPTCHA email: {e}")

            for wait_idx in range(60):
                await asyncio.sleep(5.0)
                p_text_now = (await self._page.inner_text("body") if await self._page.query_selector("body") else "").lower()
                p_title_now = (await self._page.title()).lower()
                if not any(phrase in p_text_now or phrase in p_title_now for phrase in ["verify you are human", "security check", "cloudflare", "additional verification"]):
                    logger.info("✅ Human verification solved! Resuming agent...")
                    return

        except Exception as e:
            logger.warning(f"Verification challenge handler note: {e}")

    async def _check_and_wait_for_signin(self):
        """Check if Indeed presents a sign-in wall or if user is logged in, persisting session tokens."""
        for attempt in range(300):
            try:
                current_url = self._page.url.lower()
                # Check if already authenticated via Account Menu or user profile elements
                is_logged_in = await self._page.query_selector(
                    "a[data-gnav-element-name='AccountMenu'], button[id*='AccountMenu'], div[data-testid='AccountMenu'], a[href*='/account'], button[aria-label*='Account'], button[aria-label*='Profile']"
                )
                if is_logged_in:
                    if attempt > 0:
                        logger.info("✅ Indeed sign-in detected! Resuming agent...")
                    else:
                        logger.info("✅ Authenticated Indeed user account session confirmed!")
                    return

                # If not logged in yet
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info("🔐  INDEED SIGN-IN REQUIRED (Saves Session Cookies Permanently)")
                    logger.info("👉  Please log in to your Indeed account in the opened Chrome window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email="kamalkumar.doddi@gmail.com",
                                subject="🔐 [ACTION REQUIRED] Please Sign In to Indeed",
                                body="Hello Kamal,\n\nThe Indeed Auto-Apply Agent requires you to log in.\n\n👉 Please switch to the open Chrome browser window on your computer and sign in.\n\nThe agent will automatically detect that you have signed in, save your session cookies permanently, and start applying immediately.\n\nBest,\nAI Job Agent"
                            )
                            logger.info("📧 Sent sign-in notification email to kamalkumar.doddi@gmail.com")
                        except Exception as e:
                            logger.warning(f"Could not send sign-in email: {e}")

                await asyncio.sleep(3.0)
            except Exception:
                await asyncio.sleep(2.0)

    async def close(self):
        """Disconnect session safely."""
        try:
            if self._context and not self._is_cdp:
                await self._context.close()
            if self._browser and not self._is_cdp:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("🔌 Closed Indeed browser session cleanly.")
        except Exception as e:
            logger.warning(f"Note during browser close: {e}")

    async def _find_indeed_apply_buttons(self, page_or_frame):
        """
        Comprehensive search for Direct Indeed Apply buttons ('Apply now', 'Apply with Indeed', 'Easily apply')
        and External Apply buttons across all HTML tags (button, a, div[role=button], span) and all frames.
        """
        containers = [page_or_frame] + getattr(page_or_frame, "frames", [])
        indeed_apply_btn = None
        external_apply_btn = None

        # 1. Direct Indeed Apply Selectors (matches button, a, div, span)
        direct_selectors = [
            "button#indeedApplyButton",
            "a#indeedApplyButton",
            "div#indeedApplyButton button",
            "div#indeedApplyButton a",
            "div#indeedApplyButton",
            "button[id*='indeedApply']",
            "a[id*='indeedApply']",
            "div[id*='indeedApply']",
            "button:has-text('Apply with Indeed')",
            "a:has-text('Apply with Indeed')",
            "div[role='button']:has-text('Apply with Indeed')",
            "button:has-text('Apply now')",
            "a:has-text('Apply now')",
            "div[role='button']:has-text('Apply now')",
            "span:has-text('Apply now')",
            "button:has-text('Easily apply')",
            "a:has-text('Easily apply')",
            "div[role='button']:has-text('Easily apply')",
            "button:has-text('Apply easily')",
            "a:has-text('Apply easily')",
            "div[data-testid='indeedApply'] button",
            "div[data-testid='indeedApply'] a",
            "div[data-testid='indeedApply']",
            "[data-testid='viewJob-apply-button']",
            "[data-testid='jobsearch-IndeedApplyButton']",
            "button.jobsearch-IndeedApplyButton-button",
            "a.jobsearch-IndeedApplyButton-button",
            "button.css-1oxck4n",
            "a.css-1oxck4n",
            "a[aria-label*='Apply']",
            "button[aria-label*='Apply']",
        ]

        for c in containers:
            if indeed_apply_btn:
                break
            for sel in direct_selectors:
                try:
                    elems = await c.query_selector_all(sel)
                    for el in elems:
                        if el and await el.is_visible():
                            b_txt = ((await el.inner_text()) or "").strip().lower()
                            if not any(w in b_txt for w in ["company site", "employer site", "company website", "employer website"]):
                                indeed_apply_btn = el
                                break
                    if indeed_apply_btn:
                        break
                except Exception:
                    pass

        # 2. JavaScript DOM fallback for Direct Apply
        if not indeed_apply_btn:
            for c in containers:
                try:
                    js_btn = await c.evaluate_handle("""
                        () => {
                            const candidates = Array.from(document.querySelectorAll('button, a, div[role="button"], span[role="button"], a[data-jk]'));
                            for (const el of candidates) {
                                if (!el.offsetParent && el.offsetWidth === 0 && el.offsetHeight === 0) continue;
                                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                                if (txt === 'apply now' || txt === 'apply with indeed' || txt === 'easily apply' || txt === 'apply easily' || txt.startsWith('apply now') || txt.startsWith('apply with indeed')) {
                                    if (!txt.includes('company') && !txt.includes('employer') && !txt.includes('website')) {
                                        return el;
                                    }
                                }
                            }
                            const indeedBtn = document.querySelector('#indeedApplyButton, [data-testid="indeedApply"], .jobsearch-IndeedApplyButton-button');
                            if (indeedBtn) return indeedBtn;
                            return null;
                        }
                    """)
                    if js_btn and js_btn.as_element() and await js_btn.as_element().is_visible():
                        indeed_apply_btn = js_btn.as_element()
                        break
                except Exception:
                    pass

        # 3. External Apply Selectors
        if not indeed_apply_btn:
            external_selectors = [
                "button:has-text('Apply on company site')",
                "a:has-text('Apply on company site')",
                "div[role='button']:has-text('Apply on company site')",
                "button:has-text('Apply on employer site')",
                "a:has-text('Apply on employer site')",
                "button:has-text('Apply on company website')",
                "a:has-text('Apply on company website')",
                "button:has-text('Apply directly')",
                "a:has-text('Apply directly')",
            ]
            for c in containers:
                if external_apply_btn:
                    break
                for sel in external_selectors:
                    try:
                        elems = await c.query_selector_all(sel)
                        for el in elems:
                            if el and await el.is_visible():
                                external_apply_btn = el
                                break
                        if external_apply_btn:
                            break
                    except Exception:
                        pass

        return indeed_apply_btn, external_apply_btn

    def notify_direct_apply_job(
        self,
        job_title: str,
        company: str,
        job_url: str,
        resume_pdf_path: str,
        reason: str = "",
    ):
        """Send email with job link and tailored resume when job requires company site application."""
        to_email = "kamalkumar.doddi@gmail.com"
        subject = f"[Direct Apply - Indeed] {job_title} at {company}"
        body = (
            f"Hello Kamal,\n\n"
            f"The following Indeed job requires applying directly on the company website:\n\n"
            f"• Job Title: {job_title}\n"
            f"• Company: {company}\n"
            f"• Experience Match: {reason}\n"
            f"• Direct Job Link: {job_url}\n\n"
            f"Your ATS-tailored 1-page resume has been generated in 'resumes/indeed/' and attached so you can apply directly.\n\n"
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
        """Use candidate profile and AI to intelligently answer application fields."""
        q_lower = question_text.lower()

        # Candidate Profile Rule-Based Answers (0ms & 0 API quota used)
        if "age" in q_lower or "how old" in q_lower:
            return "23"
        if "dob" in q_lower or "birth" in q_lower:
            return "15/08/2001"
        if "gender" in q_lower:
            return "Male"
        if "marital" in q_lower:
            return "Single"
        if "nationality" in q_lower or "citizenship" in q_lower:
            return "Indian"
        if "graduation year" in q_lower or "passing year" in q_lower or "passout" in q_lower or "year of passing" in q_lower:
            return "2024"
        if "college" in q_lower or "university" in q_lower or "institute" in q_lower:
            return "JNTU Hyderabad"
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

        # Shift and work arrangements
        if any(w in q_lower for w in ["shift", "night", "day shift", "rotational", "weekend", "work from home", "wfh", "office"]):
            return "Yes"

        # Infrastructure / Devices
        if any(w in q_lower for w in ["laptop", "desktop", "computer", "wifi", "wi-fi", "internet", "broadband"]):
            return "Yes"

        # Vehicle / Driving license
        if any(w in q_lower for w in ["vehicle", "two-wheeler", "bike", "driving license", "license"]):
            return "Yes"

        # Technical Skills Experience (Java, Spring Boot, Microservices, Python, SQL, REST APIs, Docker, AWS, Git, React)
        tech_skills = ["java", "spring", "boot", "microservice", "python", "fastapi", "sql", "mysql", "postgres", "rest", "api", "docker", "aws", "git", "hibernate", "react", "backend", "full stack"]
        if any(ts in q_lower for ts in tech_skills):
            if any(w in q_lower for w in ["how many years", "years of experience", "experience in years", "number of years", "how long"]):
                return "2"
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["yes", "2+", "2 years", "2-3", "1-2", "1 to 2", "2 to 3", "intermediate", "expert", "proficient"]):
                        return opt
                return options[0]
            if field_type == "number":
                return "2"
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
            return "0"

        if "sponsorship" in q_lower or "visa" in q_lower:
            if "require" in q_lower or "need" in q_lower:
                return "No"
            return "Yes"
        if "authorized" in q_lower or "legally" in q_lower or "eligible to work" in q_lower:
            return "Yes"
        if "years of experience" in q_lower or "how many years" in q_lower or "experience" in q_lower:
            return str(int(exp_years)) if exp_years >= 2.0 else "2"
        if "degree" in q_lower or "education" in q_lower or "qualification" in q_lower or "bachelor" in q_lower or "graduate" in q_lower or "btech" in q_lower:
            if options:
                for opt in options:
                    if "yes" in opt.lower():
                        return opt
                    if any(deg in opt.lower() for deg in ["bachelor", "b.tech", "btech", "degree", "undergraduate", "graduate", "computer science"]):
                        return opt
                return options[0]
            if field_type == "radio":
                return "Yes"
            return "Bachelor's Degree"
        if "gpa" in q_lower or "percentage" in q_lower or "cgpa" in q_lower:
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

        # Company Employment / Former Employee Checks
        if any(w in q_lower for w in ["currently employed", "employed as", "employed at", "employed with", "worked at", "worked with", "former employee", "previous employee", "ever worked", "previously employed"]):
            return "No"

        # Salary Expectation / CTC rules
        if any(w in q_lower for w in ["salary expectation", "expected salary", "salary expected", "ctc expectation", "expected ctc", "compensation expectation"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs", "lac"]):
                return "5"
            if any(w in q_lower for w in ["monthly", "per month"]):
                return "40000"
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["5", "5.0", "4-6", "4 to 6", "500000", "5 lpa"]):
                        return opt
                return options[0]
            return "500000"

        if "disability" in q_lower:
            return "No"
        if "veteran" in q_lower:
            return "No"
        if "background" in q_lower or "drug" in q_lower:
            return "Yes"
        if "english" in q_lower or "fluent" in q_lower or "proficiency" in q_lower or "language" in q_lower:
            return "Professional" if "professional" in [o.lower() for o in (options or [])] else "Yes"

        # AI Fallback with graceful rate-limit handling
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

        # Final local fallback if AI is rate limited or unavailable (mirrors LinkedIn agent)
        return "Yes" if "yes" in [o.lower() for o in (options or [])] else "2"

    async def extract_and_apply_jobs(
        self,
        target_applied: int = 5,
        max_inspect_per_page: int = 25,
        current_keyword: str = "",
        location: str = "India",
    ) -> tuple[list[dict], int]:
        """Iterate over job cards on current Indeed page with human pacing, upfront title screening, and multi-source JD extraction."""
        results = []
        applied_count = 0

        # Dismiss popup modals gently
        try:
            await self._page.keyboard.press("Escape")
            await self._page.evaluate("""
                document.querySelectorAll('.popover-x, .icl-CloseButton, button[aria-label="close"], button.css-yi9ndv').forEach(el => {
                    try { el.click(); } catch(e) {}
                });
            """)
        except Exception:
            pass

        # Discover Unique Job Cards dynamically from live DOM
        cards_info = await self._page.evaluate("""
            () => {
                const results = [];
                const seenJks = new Set();
                const cardNodes = document.querySelectorAll("div.cardOutline, div.job_seen_beacon, li:has(div.cardOutline), div[data-jk]");
                
                cardNodes.forEach((el) => {
                    const linkEl = el.querySelector("a.jcs-JobTitle, a[data-jk], h2.jobTitle a, a");
                    const titleEl = el.querySelector("a.jcs-JobTitle span, h2.jobTitle span, a.jcs-JobTitle, h2.jobTitle");
                    const compEl = el.querySelector("[data-testid='company-name'], span.companyName, span.css-63koeb, .company");
                    const locEl = el.querySelector("[data-testid='text-location'], div.company_location, .location");
                    const jk = el.getAttribute("data-jk") || (linkEl ? (linkEl.getAttribute("data-jk") || (linkEl.id ? linkEl.id.replace('job_', '') : '')) : '');
                    
                    if (jk && !seenJks.has(jk)) {
                        seenJks.add(jk);
                        const isEasilyApply = (el.innerText || '').includes('Easily apply') || (el.innerText || '').includes('Apply easily') || (el.innerText || '').includes('Apply with Indeed') || !!el.querySelector("[data-testid='indeedApply'], .iaIcon");
                        const snippet = (el.querySelector(".job-snippet, .underShelfFooter, .css-14yo8q")?.innerText || '').trim();
                        results.push({
                            jk: jk,
                            title: (titleEl ? titleEl.innerText : '').trim(),
                            company: (compEl ? compEl.innerText : '').trim(),
                            location: (locEl ? locEl.innerText : '').trim(),
                            isEasilyApply: isEasilyApply,
                            snippet: snippet
                        });
                    }
                });
                return results;
            }
        """)

        card_count = len(cards_info)
        logger.info(f"📋 Discovered {card_count} unique job listings on current Indeed page")

        total_to_inspect = min(card_count if card_count > 0 else max_inspect_per_page, max_inspect_per_page)

        for idx in range(total_to_inspect):
            if applied_count >= target_applied:
                logger.info(f"🎯 Target of {target_applied} applications reached on this search page!")
                break

            card_data = cards_info[idx]
            title = card_data.get("title") or "Unknown Title"
            company = card_data.get("company") or "Unknown Company"
            jk = card_data.get("jk") or ""
            job_url = f"https://in.indeed.com/viewjob?jk={jk}" if jk else self._page.url

            # DEDUPLICATION CHECK 1: Skip if already applied or emailed
            if JobTracker.is_applied_or_emailed("indeed", company, title, jk):
                logger.info(f"⏭️ Skipping already applied/emailed job: '{title}' @ {company}")
                continue

            # FAST TITLE SCREENING (0ms): Skip Senior / Lead / Principal upfront without loading right pane
            title_screening = IndeedExperienceAnalyzer.analyze_title(title)
            if not title_screening["eligible"]:
                logger.info(f"\n[{idx + 1}/{total_to_inspect}] ⏩ Skipping '{title}' @ {company} — {title_screening['reason']}")
                JobTracker.record_job("indeed", company, title, jk, status="SKIPPED_EXP", job_url=job_url)
                results.append({"title": title, "company": company, "reason": title_screening["reason"], "status": "SKIPPED_EXP"})
                continue

            try:
                # 1. Smoothly scroll card into view with natural human wheel motion
                await self._page.evaluate("""
                    (targetJk) => {
                        const el = document.querySelector(`a[data-jk="${targetJk}"], a.jcs-JobTitle[data-jk="${targetJk}"], div[data-jk="${targetJk}"]`);
                        if (el) {
                            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }
                    }
                """, jk)
                await asyncio.sleep(random.uniform(0.4, 0.8))

                # Human-like mouse click on the job card link
                card_link = await self._page.query_selector(f"a[data-jk='{jk}'], a.jcs-JobTitle[data-jk='{jk}'], a#job_{jk}")
                if card_link and await card_link.is_visible():
                    await self._human_click(card_link, hover_pause=(0.2, 0.4), post_pause=(0.8, 1.4))
                else:
                    card_div = await self._page.query_selector(f"div[data-jk='{jk}'], div.cardOutline:has(a[data-jk='{jk}'])")
                    if card_div and await card_div.is_visible():
                        await self._human_click(card_div, hover_pause=(0.2, 0.4), post_pause=(0.8, 1.4))
                    else:
                        await self._page.evaluate("""
                            (targetJk) => {
                                const link = document.querySelector(`a[data-jk="${targetJk}"], a.jcs-JobTitle[data-jk="${targetJk}"], a#job_${targetJk}`);
                                if (link) link.click();
                            }
                        """, jk)
                        await asyncio.sleep(1.0)

                # 2. Wait up to 3.5s for Right-Pane JD to asynchronously hydrate
                try:
                    await self._page.wait_for_selector(
                        "#jobDescriptionText, div.jobsearch-jobDescriptionText, [data-testid='jobsearch-JobDescriptionText'], div.jobsearch-JobComponent-description",
                        timeout=3500,
                    )
                except Exception:
                    pass

                # Check for human challenge on page
                await self._check_and_wait_for_human_challenge()

                # Locate the right-hand details pane container
                pane = None
                for pane_sel in [
                    "div.jobsearch-RightPane", "div.jobsearch-ViewJobPane",
                    "div.jobsearch-JobComponent", "div#vjs-container", "div.fastviewjob",
                    "#jobsearch-ViewjobPaneWrapper"
                ]:
                    p_el = await self._page.query_selector(pane_sel)
                    if p_el and await p_el.is_visible():
                        pane = p_el
                        break

                # Extract refined Title & Company from within the right pane
                if pane:
                    for t_sel in [
                        "h2[data-testid='jobsearch-JobInfoHeader-title'] span",
                        "h1[data-testid='jobsearch-JobInfoHeader-title'] span",
                        "h1.jobsearch-JobInfoHeader-title",
                        "h2.jobsearch-JobInfoHeader-title",
                        "[data-testid='jobsearch-JobInfoHeader-title']",
                        "[data-testid='simpler-jobTitle']"
                    ]:
                        t_elem = await pane.query_selector(t_sel)
                        if t_elem:
                            t_txt = (await t_elem.inner_text()).strip()
                            if t_txt and len(t_txt) > 2 and "jobs in " not in t_txt.lower() and "verification" not in t_txt.lower():
                                title = t_txt
                                break

                    for c_sel in [
                        "div[data-testid='inlineHeader-companyName'] a",
                        "div[data-testid='inlineHeader-companyName']",
                        ".jobsearch-InlineCompanyRating-companyHeader a",
                        "[data-testid='company-name']"
                    ]:
                        c_elem = await pane.query_selector(c_sel)
                        if c_elem:
                            c_txt = (await c_elem.inner_text()).strip()
                            if c_txt and len(c_txt) > 1 and "jobs in " not in c_txt.lower():
                                company = c_txt
                                break

                logger.info(f"\n[{idx + 1}/{total_to_inspect}] 🔎 [Indeed] Inspecting: '{title}' @ {company}")

                # Human reading pause: reading title and inspecting the job
                await asyncio.sleep(random.uniform(1.5, 2.5))

                # Re-verify refined title if it was updated from right pane
                refined_title_screening = IndeedExperienceAnalyzer.analyze_title(title)
                if not refined_title_screening["eligible"]:
                    logger.info(f"⏩ Skipping '{title}' — {refined_title_screening['reason']}")
                    JobTracker.record_job("indeed", company, title, jk, status="SKIPPED_EXP", job_url=job_url)
                    results.append({"title": title, "company": company, "reason": refined_title_screening["reason"], "status": "SKIPPED_EXP"})
                    continue

                # DEDUPLICATION CHECK 2 (with refined title/company)
                if JobTracker.is_applied_or_emailed("indeed", company, title, jk):
                    logger.info(f"⏭️ Skipping already applied/emailed job: '{title}' @ {company}")
                    continue

                # Multi-Source Comprehensive JD Extraction:
                # Scroll right pane to ensure lazy-loaded sections (What You'll Bring, Qualifications, Responsibilities) are hydrated
                try:
                    await self._page.evaluate("""
                        () => {
                            const pane = document.querySelector("div.jobsearch-RightPane, div.jobsearch-ViewJobPane, div.jobsearch-JobComponent, div#vjs-container, #jobsearch-ViewjobPaneWrapper, div.fastviewjob");
                            if (pane) {
                                pane.scrollTop = pane.scrollHeight;
                            }
                        }
                    """)
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

                # 1. Extract from Right Pane & Sub-sections
                jd_parts = []
                target_container = pane or self._page
                try:
                    for qual_sel in ["#qualificationsSection", "#jobDetailsSection", "div[data-testid='jobsearch-JobDescriptionSection']", "#profileInsights"]:
                        q_elem = await target_container.query_selector(qual_sel)
                        if q_elem:
                            txt = (await q_elem.inner_text()).strip()
                            if len(txt) > 10 and txt not in jd_parts:
                                jd_parts.append(txt)

                    for desc_sel in [
                        "#jobDescriptionText", "div[data-testid='jobDescriptionText']", "div.jobsearch-jobDescriptionText",
                        "div.jobsearch-JobComponent-description", "div[data-testid='jobsearch-JobDescription']",
                        "[data-testid='jobsearch-JobDescriptionText']"
                    ]:
                        d_elem = await target_container.query_selector(desc_sel)
                        if d_elem:
                            txt = (await d_elem.inner_text()).strip()
                            if len(txt) > 30 and txt not in jd_parts:
                                jd_parts.append(txt)
                                break

                    # If pane exists, also check if pane has full text that contains more details
                    if pane:
                        pane_full_txt = (await pane.inner_text()).strip()
                        if len(pane_full_txt) > len(" ".join(jd_parts)):
                            jd_parts.append(pane_full_txt)
                except Exception:
                    pass

                # 2. Extract from JSON-LD Schema on the page if DOM text is still short
                job_desc = "\n\n".join(jd_parts).strip()
                if not job_desc or len(job_desc) < 30:
                    try:
                        json_ld_desc = await self._page.evaluate("""
                            () => {
                                const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
                                for (const s of scripts) {
                                    try {
                                        const data = JSON.parse(s.innerText || s.textContent || '{}');
                                        if (data['@type'] === 'JobPosting' && data.description) {
                                            const tmp = document.createElement('div');
                                            tmp.innerHTML = data.description;
                                            return tmp.innerText || tmp.textContent || '';
                                        }
                                    } catch(e) {}
                                }
                                return '';
                            }
                        """)
                        if json_ld_desc and len(json_ld_desc.strip()) > 30:
                            job_desc = json_ld_desc.strip()
                            logger.info(f"ℹ️ Extracted JD via page JSON-LD schema ({len(job_desc)} chars)")
                    except Exception:
                        pass

                # 3. Fallback to Job Snippet
                if not job_desc or len(job_desc) < 30:
                    if card_data.get("snippet") and len(card_data["snippet"]) > 20:
                        job_desc = card_data["snippet"]
                        logger.info(f"ℹ️ Used job snippet for JD analysis: '{job_desc[:80]}...'")
                    else:
                        logger.warning(f"Could not extract Indeed job description for '{title}' @ {company} — skipping")
                        continue

                # Experience Eligibility Analysis
                analysis = IndeedExperienceAnalyzer.analyze(job_title=title, job_description=job_desc)
                if not analysis["eligible"]:
                    logger.info(f"⏩ Skipping '{title}' — {analysis['reason']}")
                    JobTracker.record_job("indeed", company, title, jk, status="SKIPPED_EXP", job_url=job_url)
                    results.append({"title": title, "company": company, "reason": analysis["reason"], "status": "SKIPPED_EXP"})
                    continue

                exp_years = analysis["exp_years"]
                template_name = "2+ Years Software Engineer" if exp_years >= 2.0 else "1.5 Years Full Stack Developer"
                logger.info(f"✅ Experience Matched: {analysis['reason']}")
                logger.info(f"📑 Eligible for: {template_name} (exp_years={exp_years})")

                # Check if already applied
                is_already_applied = False
                for c in [target_container] + getattr(target_container, "frames", []):
                    alr = await c.query_selector(
                        "button:has-text('Applied'), div:has-text('You applied on Indeed'), span:has-text('Applied'), button[disabled]:has-text('Applied'), [data-testid='applied-badge']"
                    )
                    if alr and await alr.is_visible():
                        is_already_applied = True
                        break

                if is_already_applied:
                    logger.info(f"ℹ️ Already applied to '{title}' @ {company} — skipping")
                    JobTracker.record_job("indeed", company, title, jk, status="ALREADY_APPLIED", job_url=job_url)
                    continue

                # Check Apply Buttons across right pane containers & tags
                indeed_apply_btn, external_apply_btn = await self._find_indeed_apply_buttons(target_container)

                # Handle Direct Application or External Email
                if indeed_apply_btn and await indeed_apply_btn.is_visible():
                    job_dict = {
                        "id": f"indeed_{idx + 1}_{int(time.time())}",
                        "title": title,
                        "company": company,
                        "description": job_desc,
                    }
                    tailored_pdf_path = self.resume_service.generate_tailored_resume(
                        job=job_dict,
                        candidate_profile={},
                        exp_years=exp_years,
                        portal="indeed",
                    )
                    logger.info(f"📄 Tailored ATS PDF Ready (resumes/indeed/): {tailored_pdf_path}")

                    btn_label = ((await indeed_apply_btn.inner_text()) or "Apply now").strip()
                    logger.info(f"🎯 Clicking Indeed '{btn_label}' with human movement...")
                    
                    # Human hover and click on the Apply button
                    await self._human_click(
                        indeed_apply_btn,
                        hover_pause=(0.35, 0.75),
                        click_delay=(75, 130),
                        post_pause=(2.0, 3.2),
                    )

                    apply_status = await self._handle_indeed_apply_flow(
                        job_title=title,
                        company=company,
                        resume_pdf_path=tailored_pdf_path,
                        exp_years=exp_years,
                        root_page=self._page,
                    )

                    if apply_status in ("APPLIED", "DRY_RUN_COMPLETED"):
                        applied_count += 1
                        logger.info(f"🎉 Indeed Application Recorded! (Role applied: {applied_count}/{target_applied})")

                    JobTracker.record_job("indeed", company, title, jk, status=apply_status, job_url=job_url)
                    results.append({
                        "title": title,
                        "company": company,
                        "job_url": job_url,
                        "resume": tailored_pdf_path,
                        "template": template_name,
                        "status": apply_status,
                    })

                elif external_apply_btn and await external_apply_btn.is_visible():
                    job_dict = {
                        "id": f"indeed_{idx + 1}_{int(time.time())}",
                        "title": title,
                        "company": company,
                        "description": job_desc,
                    }
                    tailored_pdf_path = self.resume_service.generate_tailored_resume(
                        job=job_dict,
                        candidate_profile={},
                        exp_years=exp_years,
                        portal="indeed",
                    )
                    logger.info(f"📄 Tailored ATS PDF Ready (resumes/indeed/): {tailored_pdf_path}")

                    logger.info(f"🌐 Indeed Job has 'Apply on company site' (External Apply). Sending direct apply email ONCE...")
                    self.notify_direct_apply_job(
                        job_title=title,
                        company=company,
                        job_url=job_url,
                        resume_pdf_path=tailored_pdf_path,
                        reason=analysis["reason"],
                    )
                    JobTracker.record_job("indeed", company, title, jk, status="EXTERNAL_LINK_EMAILED", job_url=job_url)
                    results.append({
                        "title": title,
                        "company": company,
                        "job_url": job_url,
                        "resume": tailored_pdf_path,
                        "template": template_name,
                        "status": "EXTERNAL_LINK_EMAILED",
                    })

                else:
                    logger.info("ℹ️ No active Apply button found on this Indeed post — skipping")
                    JobTracker.record_job("indeed", company, title, jk, status="NO_APPLY_BUTTON", job_url=job_url)
                    results.append({"title": title, "company": company, "status": "NO_APPLY_BUTTON"})

                # Natural human breathing delay between jobs
                delay = random.uniform(4.5, 7.5)
                logger.info(f"⏳ Pacing next inspection in {delay:.1f}s...")
                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing Indeed job card {idx + 1}: {e}")

        return results, applied_count

    async def _find_submit_button(self, containers):
        """Find the final application submit button on Indeed across all containers and frames."""
        submit_selectors = [
            "button[data-testid='submit-button']",
            "button[data-testid='submit-application-button']",
            "button[data-testid='review-page-submit-button']",
            "button[data-testid='ia-submit-button']",
            "button.ia-submitButton",
            "button:has-text('Submit your application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit Application')",
            "button:has-text('Submit your Application')",
            "button:has-text('Submit')",
            "button:has-text('Send application')",
            "button:has-text('Send your application')",
            "button:has-text('Apply')",
            "button[type='submit']:has-text('Submit')",
            "button[type='submit']:has-text('Apply')",
            "button[type='submit']:has-text('Send')",
            "button.ia-continueButton:has-text('Submit')",
            "button.ia-continueButton:has-text('Apply')",
            "button[aria-label*='Submit' i]",
            "button[aria-label*='submit' i]",
        ]
        for container in containers:
            for sel in submit_selectors:
                try:
                    btns = await container.query_selector_all(sel)
                    for btn in btns:
                        if await btn.is_visible():
                            txt = ((await btn.inner_text()) or "").strip().lower()
                            if any(w in txt for w in ["back", "cancel", "edit", "previous", "continue", "next", "review your application", "review application"]):
                                continue
                            return btn
                except Exception:
                    pass
        return None

    async def _handle_indeed_apply_flow(
        self,
        job_title: str,
        company: str,
        resume_pdf_path: str,
        exp_years: float = 2.0,
        root_page=None,
    ) -> str:
        """Handle multi-step Indeed Apply modal/page/iframe flow with realistic human interactions."""
        target_page = root_page or self._page
        resume_edited = False
        pages = self._context.pages
        if len(pages) > 1 and pages[-1] != self._page and pages[-1] != root_page:
            target_page = pages[-1]
            logger.info("  📄 Detected application flow in popup tab...")

        for step in range(1, 16):
            await asyncio.sleep(random.uniform(2.0, 3.2))

            # Check if popup tab opened dynamically on this step
            current_pages = self._context.pages
            if len(current_pages) > 1 and current_pages[-1] != self._page and current_pages[-1] != root_page:
                target_page = current_pages[-1]

            # Check if the opened tab navigated to an external application portal or stuck on about:blank
            if target_page != self._page and target_page != root_page:
                try:
                    curr_url = target_page.url.lower()
                    if is_blank_url(curr_url) and step >= 2:
                        logger.warning("⚠️ [Indeed Tab Guard] Application popup tab is stuck on 'about:blank'. Closing popup and refreshing previous page...")
                        if not target_page.is_closed():
                            await target_page.close()
                        await self._page.bring_to_front()
                        await self._page.reload(wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(2.0)
                        return "BLANK_TAB_CLOSED"
                    elif curr_url and not any(k in curr_url for k in ["indeed.com", "smartapply", "about:blank"]):
                        logger.info(f"🌐 'Apply now' opened external career portal: {target_page.url}")
                        self.notify_direct_apply_job(
                            job_title=job_title,
                            company=company,
                            job_url=target_page.url,
                            resume_pdf_path=resume_pdf_path,
                            reason="External career portal opened via Apply now",
                        )
                        if not target_page.is_closed():
                            await target_page.close()
                        return "EXTERNAL_LINK_EMAILED"
                except Exception:
                    pass

            # Check if submission is already complete (Success Screen Confirmation)
            page_text = (await target_page.inner_text("body") if (not target_page.is_closed() and await target_page.query_selector("body")) else "").lower()
            if any(phrase in page_text for phrase in [
                "your application was submitted",
                "your application was submitted to",
                "your application has been submitted",
                "application was submitted",
                "application was sent",
                "application submitted",
                "application has been sent",
                "you will get an email confirmation",
                "email confirmation at",
                "return to job search",
                "you've applied",
                "applied to",
            ]) or (not target_page.is_closed() and await target_page.query_selector("div[data-testid='application-confirmation'], div.ia-PostApply, .ia-ApplicationConfirmation, h1:has-text('submitted'), button:has-text('Return to job search'), a:has-text('Return to job search')")):
                logger.info("  🎉 Indeed application submission confirmed on-screen! ('Your application was submitted')")
                if target_page != self._page and target_page != root_page and not target_page.is_closed():
                    try:
                        await asyncio.sleep(2.5)
                        await target_page.close()
                        logger.info("  🚪 Closed application tab. Ready for next role.")
                    except Exception:
                        pass
                return "APPLIED"

            logger.info(f"  📝 Processing Indeed Apply Step {step}...")

            active_containers = [target_page] + getattr(target_page, "frames", [])

            # -----------------------------------------------------------------------
            # Fast-path: Indeed Screener Questionnaire page (questions-module URL)
            # Answer all visible questions using ONLY rule-based logic (no AI calls)
            # then click Continue to advance.
            # -----------------------------------------------------------------------
            curr_url_now = (target_page.url if not target_page.is_closed() else "").lower()
            if "questions-module" in curr_url_now or "questions_module" in curr_url_now:
                logger.info("  📋 Detected Indeed Screener Questions page — answering questions...")
                for container in active_containers:
                    try:
                        # --- Radio buttons / Yes-No questions ---
                        # Indeed questions-module structure: a heading (label/h2/p) + list of radio inputs
                        radio_inputs = await container.query_selector_all("input[type='radio']")
                        if radio_inputs:
                            # Group by name attribute
                            name_groups: dict[str, list] = {}
                            for r in radio_inputs:
                                rname = (await r.get_attribute("name") or "")
                                if rname not in name_groups:
                                    name_groups[rname] = []
                                name_groups[rname].append(r)

                            for rname, group_radios in name_groups.items():
                                # Find label text for this question group
                                q_text = ""
                                try:
                                    # Try aria-labelledby on the fieldset or wrapping div
                                    first_r = group_radios[0]
                                    lbl_id = await first_r.get_attribute("aria-labelledby")
                                    if lbl_id:
                                        lbl_el = await container.query_selector(f"#{lbl_id}")
                                        if lbl_el:
                                            q_text = (await lbl_el.inner_text()).strip()
                                    if not q_text:
                                        # Walk up to fieldset and find legend or label
                                        q_text = await container.evaluate("""
                                            (radio) => {
                                                let el = radio.closest('fieldset, [role="group"], div');
                                                for (let i = 0; i < 5 && el; i++) {
                                                    const leg = el.querySelector('legend, label, [data-testid*="label"], h1, h2, h3, p');
                                                    if (leg && leg.innerText.trim().length > 3) return leg.innerText.trim();
                                                    el = el.parentElement;
                                                }
                                                return '';
                                            }
                                        """, first_r)
                                except Exception:
                                    pass

                                # Collect option texts (from labels)
                                option_texts = []
                                for r in group_radios:
                                    rid = await r.get_attribute("id") or ""
                                    r_lbl = await container.query_selector(f"label[for='{rid}']")
                                    r_val = (await r.get_attribute("value") or "").strip()
                                    r_txt = (await r_lbl.inner_text()).strip() if r_lbl else r_val
                                    option_texts.append(r_txt or r_val)

                                # Get rule-based answer (will NOT call AI — falls through to heuristic)
                                answer = await self.answer_form_field(
                                    question_text=q_text or "Selection",
                                    field_type="radio",
                                    options=option_texts,
                                    job_title=job_title,
                                    company=company,
                                    exp_years=exp_years,
                                )

                                # Click matching radio label
                                clicked = False
                                for r in group_radios:
                                    rid = await r.get_attribute("id") or ""
                                    r_lbl = await container.query_selector(f"label[for='{rid}']")
                                    r_val = (await r.get_attribute("value") or "").lower()
                                    r_txt = (await r_lbl.inner_text()).strip().lower() if r_lbl else r_val
                                    if answer.lower() in r_txt or r_txt in answer.lower() or answer.lower() == r_val:
                                        target_el = r_lbl if r_lbl else r
                                        await self._human_click(target_el, hover_pause=(0.15, 0.3), post_pause=(0.3, 0.5))
                                        logger.info(f"  ✨ [Questionnaire Radio] '{q_text[:50]}' -> '{r_txt}'")
                                        clicked = True
                                        break
                                if not clicked and group_radios:
                                    # Default: click first label (usually "Yes")
                                    rid0 = await group_radios[0].get_attribute("id") or ""
                                    lbl0 = await container.query_selector(f"label[for='{rid0}']")
                                    target_el0 = lbl0 if lbl0 else group_radios[0]
                                    await self._human_click(target_el0, hover_pause=(0.15, 0.3), post_pause=(0.3, 0.5))
                                    logger.info(f"  ✨ [Questionnaire Radio] '{q_text[:50]}' -> first option (fallback)")

                        # --- Text / Number inputs ---
                        text_inputs = await container.query_selector_all(
                            "input[type='text'], input[type='number'], input[type='tel'], textarea"
                        )
                        for inp in text_inputs:
                            val = await inp.input_value()
                            if not val:
                                inp_id = await inp.get_attribute("id") or ""
                                lbl_el = await container.query_selector(f"label[for='{inp_id}']")
                                lbl_txt = (await lbl_el.inner_text()).strip() if lbl_el else ""
                                if not lbl_txt:
                                    lbl_txt = (await inp.get_attribute("aria-label")) or (await inp.get_attribute("placeholder")) or "Detail"
                                answer = await self.answer_form_field(
                                    question_text=lbl_txt,
                                    field_type="text",
                                    job_title=job_title,
                                    company=company,
                                    exp_years=exp_years,
                                )
                                await self._human_type(inp, str(answer))

                        # --- Select dropdowns ---
                        selects = await container.query_selector_all("select")
                        for s in selects:
                            sel_id = await s.get_attribute("id") or ""
                            lbl_el = await container.query_selector(f"label[for='{sel_id}']")
                            lbl_txt = (await lbl_el.inner_text()).strip() if lbl_el else (await s.get_attribute("aria-label") or "Option")
                            opts = await s.query_selector_all("option")
                            opt_texts = [(await o.inner_text()).strip() for o in opts]
                            answer = await self.answer_form_field(
                                question_text=lbl_txt,
                                field_type="select",
                                options=opt_texts,
                                job_title=job_title,
                                company=company,
                                exp_years=exp_years,
                            )
                            for o in opts:
                                o_txt = (await o.inner_text()).strip().lower()
                                o_val = await o.get_attribute("value")
                                if answer.lower() in o_txt:
                                    await s.select_option(value=o_val)
                                    logger.info(f"  ✨ [Questionnaire Select] '{lbl_txt}' -> '{o_txt}'")
                                    break

                    except Exception as qe:
                        logger.warning(f"  Questionnaire answering note: {qe}")

                # Click Continue after answering all questions
                await asyncio.sleep(random.uniform(0.5, 1.0))
                q_continue_clicked = False
                for container in active_containers:
                    try:
                        q_btn = await container.query_selector(
                            "button:has-text('Continue'), button[data-testid='continue-button'], "
                            "button.ia-continueButton, button[type='submit']:has-text('Continue'), "
                            "button[type='submit']"
                        )
                        if q_btn and await q_btn.is_visible():
                            logger.info("  ➡️ Clicking 'Continue' on questionnaire page...")
                            await q_btn.scroll_into_view_if_needed()
                            await self._human_click(q_btn, hover_pause=(0.25, 0.45), post_pause=(2.0, 3.0))
                            q_continue_clicked = True
                            break
                    except Exception:
                        pass
                if not q_continue_clicked:
                    try:
                        await target_page.evaluate("""
                            () => {
                                const btns = Array.from(document.querySelectorAll('button, input[type=\'submit\']'));
                                for (const b of btns) {
                                    const t = (b.innerText || b.value || '').trim().toLowerCase();
                                    if (t.includes('continue') || t.includes('next') || t === 'submit') {
                                        b.scrollIntoView(); b.click(); return;
                                    }
                                }
                            }
                        """)
                        logger.info("  ➡️ Clicked Continue via JS fallback on questionnaire page.")
                        await asyncio.sleep(2.5)
                    except Exception:
                        pass
                continue  # Go to next step loop iteration to detect confirmation or next question page


            # Element-based detection: look for the actual "CV options" button or resume-selection indicators
            _cv_options_elem = None
            _upload_different_elem = None
            _resume_file_input = None
            for _c in active_containers:
                try:
                    _cv_options_elem = await _c.query_selector(
                        "button:has-text('CV options'), button:has-text('Resume options'), "
                        "[data-testid='cv-options-button'], button[aria-label*='CV options' i], "
                        "button[aria-label*='resume options' i]"
                    )
                    if _cv_options_elem and await _cv_options_elem.is_visible():
                        break
                    _cv_options_elem = None
                except Exception:
                    pass

            # Also check for visible file input (direct upload screen) or "add a resume" text
            for _c in active_containers:
                try:
                    _resume_file_input = await _c.query_selector("input[type='file']")
                    if _resume_file_input:
                        break
                except Exception:
                    pass

            is_resume_selection_screen = (
                "resume-selection" in curr_url_now
                or "resume_selection" in curr_url_now
                or _cv_options_elem is not None
                or (
                    # File input is only a resume-screen signal when paired with resume-related context
                    _resume_file_input is not None
                    and any(phrase in page_text for phrase in [
                        "add a resume", "add resume", "select a resume", "choose a resume",
                        "upload a resume", "upload your resume", "uploaded today",
                        "resume_kamal_kumar",
                    ])
                )
                or any(phrase in page_text for phrase in [
                    "add a resume", "add resume", "resume_kamal_kumar",
                    "uploaded today", "upload a resume", "upload your resume",
                    "select a resume", "choose a resume",
                ])
            )

            if is_resume_selection_screen:
                logger.info("  📄 Detected Indeed 'Add a resume' / Resume Selection screen.")

                # STEP A: Use 'CV options' -> 'Upload a different file' FIRST if button is visible
                if not resume_edited and os.path.exists(resume_pdf_path):
                    cv_opts_btn = _cv_options_elem  # already found above

                    # If not already found, search again (page may have re-rendered)
                    if not cv_opts_btn:
                        for container in active_containers:
                            try:
                                cv_opts_btn = await container.query_selector(
                                    "button:has-text('CV options'), button:has-text('Resume options'), "
                                    "[data-testid='cv-options-button'], button[aria-label*='CV options' i], "
                                    "button[aria-label*='resume options' i]"
                                )
                                if cv_opts_btn and await cv_opts_btn.is_visible():
                                    break
                                cv_opts_btn = None
                            except Exception:
                                cv_opts_btn = None

                    if cv_opts_btn and await cv_opts_btn.is_visible():
                        logger.info("  ⚙️ Found 'CV options' button. Clicking to open dropdown menu...")
                        await cv_opts_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.4, 0.8))
                        await self._human_click(cv_opts_btn, hover_pause=(0.2, 0.5), post_pause=(1.2, 2.0))

                        # Wait for menu to appear and find 'Upload a different file'
                        await asyncio.sleep(1.0)
                        upload_opt = None
                        for _try in range(3):
                            for container in active_containers:
                                try:
                                    upload_opt = await container.query_selector(
                                        "button:has-text('Upload a different file'), "
                                        "button:has-text('Upload a different resume'), "
                                        "button:has-text('Upload resume'), "
                                        "button:has-text('Upload a resume'), "
                                        "[role='menuitem']:has-text('Upload'), "
                                        "li:has-text('Upload a different file'), "
                                        "li:has-text('Upload'), "
                                        "span:has-text('Upload a different file'), "
                                        "div[role='menuitem']:has-text('Upload')"
                                    )
                                    if upload_opt and await upload_opt.is_visible():
                                        break
                                    upload_opt = None
                                except Exception:
                                    upload_opt = None
                            if upload_opt:
                                break
                            await asyncio.sleep(0.6)

                        if upload_opt:
                            logger.info("  ⬆️ Clicking 'Upload a different file' from CV options menu...")
                            # Expect file chooser from clicking this menu item
                            try:
                                async with target_page.expect_file_chooser(timeout=5000) as fc_info:
                                    await upload_opt.click()
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(resume_pdf_path)
                                logger.info(f"  ✅ Resume uploaded via file chooser: {os.path.basename(resume_pdf_path)}")
                                resume_edited = True
                                # Wait for upload progress (up to 8s) — wait for filename to appear
                                pdf_name_stem = os.path.splitext(os.path.basename(resume_pdf_path))[0].lower()
                                for _w in range(16):
                                    await asyncio.sleep(0.5)
                                    try:
                                        _pg_txt = (await target_page.inner_text("body") if await target_page.query_selector("body") else "").lower()
                                        if pdf_name_stem[:12] in _pg_txt or "uploaded" in _pg_txt:
                                            logger.info("  ✅ Upload confirmed in DOM.")
                                            break
                                    except Exception:
                                        pass
                                await asyncio.sleep(1.5)
                            except Exception as fc_err:
                                logger.warning(f"  ⚠️ File chooser not triggered by menu click ({fc_err}). Trying fallback...")
                                # Fallback: click menu item, then find file input
                                try:
                                    await upload_opt.click()
                                    await asyncio.sleep(1.5)
                                    for container in active_containers:
                                        f_inp = await container.query_selector("input[type='file']")
                                        if f_inp:
                                            await f_inp.set_input_files(resume_pdf_path)
                                            logger.info(f"  ✅ Uploaded via file input fallback: {os.path.basename(resume_pdf_path)}")
                                            resume_edited = True
                                            await asyncio.sleep(3.0)
                                            break
                                except Exception:
                                    pass
                        else:
                            logger.warning("  ⚠️ 'Upload a different file' option not found in CV options menu. Trying direct file input...")
                    else:
                        logger.info("  ℹ️ 'CV options' button not visible on screen. Trying direct file input upload...")

                    # STEP B: Fallback — direct file input upload if CV options flow didn't work
                    if not resume_edited:
                        for container in active_containers:
                            try:
                                file_input = await container.query_selector("input[type='file']")
                                if file_input and os.path.exists(resume_pdf_path):
                                    await file_input.set_input_files(resume_pdf_path)
                                    logger.info(f"  ⬆️ Uploaded resume via direct file input: {os.path.basename(resume_pdf_path)}")
                                    resume_edited = True
                                    # Wait for upload to complete
                                    pdf_name_stem = os.path.splitext(os.path.basename(resume_pdf_path))[0].lower()
                                    for _w in range(16):
                                        await asyncio.sleep(0.5)
                                        try:
                                            _pg_txt = (await target_page.inner_text("body") if await target_page.query_selector("body") else "").lower()
                                            if pdf_name_stem[:12] in _pg_txt or "uploaded" in _pg_txt:
                                                logger.info("  ✅ Upload confirmed in DOM.")
                                                break
                                        except Exception:
                                            pass
                                    await asyncio.sleep(1.5)
                                    break
                            except Exception:
                                pass

                # STEP C: Scroll down to reveal the Continue button
                try:
                    await target_page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(0.8)
                except Exception:
                    pass

                # STEP D: Only click Continue AFTER upload is done (or if already edited)
                if resume_edited or not os.path.exists(resume_pdf_path):
                    resume_continue_clicked = False
                    for container in active_containers:
                        try:
                            continue_btn = await container.query_selector(
                                "button:has-text('Continue'), button[data-testid='continue-button'], "
                                "button.ia-continueButton, button[type='submit']:has-text('Continue'), "
                                "button[type='submit']"
                            )
                            if continue_btn and await continue_btn.is_visible():
                                logger.info("  ➡️ Found 'Continue' button on resume screen! Scrolling and clicking...")
                                await continue_btn.scroll_into_view_if_needed()
                                await asyncio.sleep(random.uniform(0.5, 1.0))
                                await self._human_click(
                                    continue_btn,
                                    hover_pause=(0.25, 0.45),
                                    click_delay=(70, 120),
                                    post_pause=(2.0, 3.0),
                                )
                                resume_continue_clicked = True
                                break
                        except Exception as e:
                            logger.debug(f"Resume continue search note: {e}")

                    if not resume_continue_clicked:
                        # JavaScript evaluate fallback click
                        try:
                            js_clicked = await target_page.evaluate("""
                                () => {
                                    const btns = Array.from(document.querySelectorAll('button, a[role="button"], input[type="submit"]'));
                                    for (const b of btns) {
                                        const txt = (b.innerText || b.textContent || b.value || '').trim().toLowerCase();
                                        if (txt === 'continue' || txt.includes('continue')) {
                                            b.scrollIntoView();
                                            b.click();
                                            return true;
                                        }
                                    }
                                    return false;
                                }
                            """)
                            if js_clicked:
                                logger.info("  ➡️ Clicked 'Continue' via JS evaluate fallback on resume screen.")
                                await asyncio.sleep(2.5)
                        except Exception:
                            pass
                else:
                    logger.warning("  ⚠️ Resume upload was not confirmed — NOT clicking Continue yet. Will retry next step.")

                # CRITICAL: Skip questionnaire answering on the resume screen and advance to next step
                continue

            # 1. Resume selection & upload (skipped if already handled in resume-selection screen above)
            if not resume_edited:
                for container in active_containers:
                    try:
                        # A. Upload tailored resume if file input is present on non-resume-selection steps
                        file_inputs = await container.query_selector_all("input[type='file']")
                        for f_inp in file_inputs:
                            if os.path.exists(resume_pdf_path):
                                await asyncio.sleep(random.uniform(0.8, 1.5))
                                await f_inp.set_input_files(resume_pdf_path)
                                logger.info(f"  ⬆️ Uploaded tailored resume: {os.path.basename(resume_pdf_path)}")
                                resume_edited = True
                                await asyncio.sleep(1.2)

                        # B. If Indeed shows a list of resumes (radio options/tiles), ensure one is selected
                        resume_radios = await container.query_selector_all(
                            "input[type='radio'][name*='resume'], input[type='radio'][id*='resume'], div[data-testid='FileRow'] input[type='radio'], .ia-Resume-item input[type='radio']"
                        )
                        if resume_radios:
                            is_any_checked = False
                            for r in resume_radios:
                                if await r.is_checked():
                                    is_any_checked = True
                                    break
                            if not is_any_checked:
                                await self._human_click(resume_radios[0], hover_pause=(0.2, 0.4), post_pause=(0.3, 0.6))
                                logger.info("  📄 Selected active resume option")
                    except Exception as e:
                        logger.debug(f"Resume step note: {e}")

            # 2. Select Dropdowns (native <select> & custom dropdowns)
            for container in active_containers:
                try:
                    selects = await container.query_selector_all("select")
                    for s in selects:
                        id_attr = await s.get_attribute("id") or ""
                        name_attr = await s.get_attribute("name") or ""
                        lbl = await container.query_selector(f"label[for='{id_attr}']") if id_attr else None
                        lbl_txt = (await lbl.inner_text()) if lbl else (name_attr or "Option")
                        if not lbl_txt:
                            lbl_txt = (await s.get_attribute("aria-label")) or "Option"

                        options_elems = await s.query_selector_all("option")
                        opt_texts = [(await o.inner_text()).strip() for o in options_elems]
                        
                        answer = await self.answer_form_field(
                            question_text=lbl_txt,
                            field_type="select",
                            options=opt_texts,
                            job_title=job_title,
                            company=company,
                            exp_years=exp_years,
                        )

                        val_to_select = None
                        for o in options_elems:
                            o_txt = (await o.inner_text()).strip().lower()
                            o_val = await o.get_attribute("value")
                            if answer.lower() == o_txt or answer.lower() in o_txt or (o_val and answer.lower() == o_val.lower()):
                                val_to_select = o_val
                                break
                        
                        if not val_to_select and len(options_elems) > 1:
                            for o in options_elems:
                                o_txt = (await o.inner_text()).strip().lower()
                                o_val = await o.get_attribute("value")
                                if any(kw in o_txt for kw in ["yes", "bachelor", "india", "immediate", "0-15", "0 days", "1.4", "5"]):
                                    val_to_select = o_val
                                    break
                            if not val_to_select:
                                val_to_select = await options_elems[1].get_attribute("value")

                        if val_to_select:
                            await self._human_click(s, hover_pause=(0.2, 0.4), post_pause=(0.2, 0.4))
                            await s.select_option(value=val_to_select)
                            await s.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", val_to_select)
                            logger.info(f"  ✨ [Indeed Dropdown] '{lbl_txt}' -> '{val_to_select}'")
                            await asyncio.sleep(random.uniform(0.3, 0.6))
                except Exception as e:
                    logger.warning(f"Indeed dropdown note: {e}")

            # 3. Fill text & number inputs with human keystroke cadence
            for container in active_containers:
                try:
                    text_inputs = await container.query_selector_all("input[type='text'], input[type='number'], input[type='tel'], textarea")
                    for inp in text_inputs:
                        val = await inp.input_value()
                        if not val:
                            id_attr = await inp.get_attribute("id")
                            label_text = ""
                            if id_attr:
                                lbl = await container.query_selector(f"label[for='{id_attr}']")
                                if lbl:
                                    label_text = await lbl.inner_text()
                            if not label_text:
                                label_text = (await inp.get_attribute("aria-label")) or (await inp.get_attribute("placeholder")) or "Detail"

                            answer = await self.answer_form_field(
                                question_text=label_text,
                                field_type="text",
                                job_title=job_title,
                                company=company,
                                exp_years=exp_years,
                            )
                            await self._human_type(inp, str(answer))
                except Exception:
                    pass

            # 4. Radio buttons (Label and input clicking with human motion)
            for container in active_containers:
                try:
                    fieldsets = await container.query_selector_all("fieldset, div.ia-Questions-item, div[data-testid='Questions-item'], div[class*='Questions-item']")
                    for fs in fieldsets:
                        legend = await fs.query_selector("legend, label, div.ia-Questions-itemLabel, span.css-1y5v1a1, h2, h3, p")
                        legend_text = (await legend.inner_text()) if legend else ""
                        radios = await fs.query_selector_all("input[type='radio']")
                        labels = await fs.query_selector_all("label")

                        if radios or labels:
                            radio_texts = [(await r.get_attribute("value") or "") for r in radios] + [(await l.inner_text()).strip() for l in labels]
                            answer = await self.answer_form_field(
                                question_text=legend_text or "Selection",
                                field_type="radio",
                                options=radio_texts,
                                job_title=job_title,
                                company=company,
                                exp_years=exp_years,
                            )

                            clicked = False
                            # 1. Try clicking matching label with human cursor movement
                            for lbl in labels:
                                l_txt = (await lbl.inner_text()).strip().lower()
                                if (answer.lower() == "yes" and "yes" in l_txt) or (answer.lower() == "no" and "no" in l_txt) or (answer.lower() in l_txt):
                                    await self._human_click(lbl, hover_pause=(0.2, 0.4), post_pause=(0.3, 0.6))
                                    logger.info(f"  ✨ [Indeed Radio Label] '{legend_text}' -> '{l_txt}'")
                                    clicked = True
                                    break
                            
                            # 2. If label didn't match, check matching radio input directly
                            if not clicked and radios:
                                for r in radios:
                                    r_val = (await r.get_attribute("value") or "").lower()
                                    if (answer.lower() == "yes" and "yes" in r_val) or (answer.lower() == "no" and "no" in r_val) or (answer.lower() in r_val):
                                        await r.evaluate("(el) => { el.checked = true; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
                                        logger.info(f"  ✨ [Indeed Radio Checked] '{legend_text}' -> '{r_val}'")
                                        clicked = True
                                        break

                            # 3. Default fallback to first label
                            if not clicked and labels:
                                await self._human_click(labels[0], hover_pause=(0.2, 0.35))
                except Exception as e:
                    logger.warning(f"Indeed radio selection note: {e}")

            # 5. Checkboxes (terms / agreements)
            for container in active_containers:
                try:
                    checkboxes = await container.query_selector_all("input[type='checkbox']")
                    for cb in checkboxes:
                        if not await cb.is_checked():
                            await self._human_click(cb, hover_pause=(0.15, 0.3))
                except Exception:
                    pass

            # 6. Check for Review Page with 'Edit' button for Resume
            if not resume_edited and os.path.exists(resume_pdf_path):
                edit_resume_btn = None
                for container in active_containers:
                    edit_resume_btn = await container.query_selector(
                        "button[aria-label*='Edit resume' i], a[aria-label*='Edit resume' i], button[aria-label*='Edit CV' i], a[aria-label*='Edit CV' i], div:has(span:has-text('Resume')) button:has-text('Edit'), div:has(h2:has-text('Resume')) button:has-text('Edit'), button[data-testid='edit-resume-button']"
                    )
                    if edit_resume_btn and await edit_resume_btn.is_visible():
                        break

                if edit_resume_btn and await edit_resume_btn.is_visible():
                    logger.info("  ✏️ Found 'Edit' button for Resume on Review screen! Clicking to attach tailored ATS resume...")
                    await edit_resume_btn.scroll_into_view_if_needed()
                    await self._human_click(edit_resume_btn, hover_pause=(0.2, 0.4), post_pause=(2.0, 3.0))
                    resume_edited = True
                    continue

            # 7. Check for Google reCAPTCHA 'I'm not a robot' checkbox on Review / Submit screen
            for frame in [target_page] + getattr(target_page, "frames", []):
                try:
                    rc_anchor = await frame.query_selector(
                        "#recaptcha-anchor, .recaptcha-checkbox, div.rc-anchor-checkbox, [aria-checked='false']"
                    )
                    if rc_anchor and await rc_anchor.is_visible():
                        is_checked = await rc_anchor.get_attribute("aria-checked")
                        if is_checked != "true":
                            logger.info("🤖 [reCAPTCHA] Detected 'I'm not a robot' checkbox on submit page. Moving physical cursor to click...")
                            await rc_anchor.scroll_into_view_if_needed()
                            box = await rc_anchor.bounding_box()
                            if box and box.get("width", 0) > 0:
                                tx = box["x"] + box["width"] * random.uniform(0.4, 0.6)
                                ty = box["y"] + box["height"] * random.uniform(0.4, 0.6)
                                await target_page.mouse.move(tx, ty, steps=6)
                                await asyncio.sleep(0.3)
                                await target_page.mouse.click(tx, ty, delay=100)
                            else:
                                await rc_anchor.click()
                            logger.info("✅ [reCAPTCHA] Clicked 'I'm not a robot' checkbox! Waiting 3.5s for verification...")
                            await asyncio.sleep(3.5)
                            break
                except Exception as rc_err:
                    logger.debug(f"reCAPTCHA submit check note: {rc_err}")

            # 8. Check for Submit button
            submit_btn = await self._find_submit_button(active_containers)

            if submit_btn and await submit_btn.is_visible():
                if self.dry_run:
                    logger.info("  🧪 [DRY RUN] Ready to Submit! (Dry run enabled — skipping final click)")
                    if target_page != self._page and target_page != root_page and not target_page.is_closed():
                        try:
                            await target_page.close()
                        except Exception:
                            pass
                    return "DRY_RUN_COMPLETED"

                btn_txt = ((await submit_btn.inner_text()) or "Submit").strip()
                logger.info(f"  🚀 Final Stage Reached! Clicking '{btn_txt}' on Indeed with human cursor...")
                await submit_btn.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(1.0, 1.8))
                await self._human_click(
                    submit_btn,
                    hover_pause=(0.4, 0.8),
                    click_delay=(70, 130),
                    post_pause=(2.0, 3.5),
                )

                # Wait up to 40 seconds strictly for on-screen submission confirmation before closing
                logger.info("  ⏳ Waiting for on-screen confirmation message ('Your application was submitted to...')...")
                verified = False
                for wait_sec in range(1, 41):
                    await asyncio.sleep(1.0)
                    if target_page.is_closed():
                        logger.info("  🎉 Application tab closed after submission — submission verified!")
                        verified = True
                        break

                    try:
                        p_txt = (await target_page.inner_text("body") if await target_page.query_selector("body") else "").lower()
                        has_success_text = any(phrase in p_txt for phrase in [
                            "your application was submitted",
                            "your application was submitted to",
                            "your application has been submitted",
                            "application was submitted",
                            "application was sent",
                            "application submitted",
                            "application has been sent",
                            "you will get an email confirmation",
                            "email confirmation at",
                            "return to job search",
                            "explore more jobs",
                            "back to search",
                            "you've applied",
                            "applied to",
                            "application status",
                        ])
                        has_success_element = await target_page.query_selector(
                            "div[data-testid='application-confirmation'], div.ia-PostApply, .ia-ApplicationConfirmation, h1:has-text('submitted'), h1:has-text('Application'), button:has-text('Return to job search'), a:has-text('Return to job search'), svg[aria-label*='check' i], div:has-text('email confirmation')"
                        )

                        if has_success_text or has_success_element:
                            logger.info(f"  🎉 SUCCESS CONFIRMED ON SCREEN: 'Your application was submitted to {company}'! ({wait_sec}s)")
                            verified = True
                            break
                    except Exception:
                        pass

                    # Re-attempt submit click if still on submit button after 6s or 14s
                    if wait_sec in (6, 14):
                        re_submit = await self._find_submit_button(active_containers)
                        if re_submit and await re_submit.is_visible():
                            logger.info("  🔄 Re-clicking submit button to ensure registration...")
                            await self._human_click(re_submit, hover_pause=(0.2, 0.4), post_pause=(1.5, 2.5))

                    # Check if validation error blocked submission
                    if await FormSelfHealer.has_validation_errors(target_page):
                        logger.info("  ⚠️ Validation error detected on submit — triggering self-healer...")
                        await FormSelfHealer.heal_errors(
                            page=target_page,
                            portal_name="indeed",
                            step_num=step,
                            job_title=job_title,
                            company=company,
                            gemini_client=self.gemini_client,
                        )
                        re_submit = await self._find_submit_button(active_containers)
                        if re_submit and await re_submit.is_visible():
                            await self._human_click(re_submit, hover_pause=(0.3, 0.6), post_pause=(2.0, 3.0))

                # ONLY close application tab after receiving the successfully applied message on the screen!
                if verified:
                    if target_page != self._page and target_page != root_page and not target_page.is_closed():
                        try:
                            logger.info("  ⏳ Pausing 2.5s on success confirmation screen before closing tab...")
                            await asyncio.sleep(2.5)
                            await target_page.close()
                            logger.info("  🚪 Successfully closed application tab after on-screen confirmation!")
                        except Exception:
                            pass
                    return "APPLIED"
                else:
                    logger.warning("  ⚠️ Submission confirmation timeout reached (tab remains open for user review).")
                    return "SUBMITTED_AWAITING_CONFIRMATION"

            # 7. Check for Continue / Next / Review button
            continue_btn = None
            for container in active_containers:
                continue_btn = await container.query_selector(
                    "button:has-text('Review your application'), button:has-text('Review Application'), button:has-text('Review'), button:has-text('Continue'), button:has-text('Next'), button[data-testid='review-button'], button[data-testid='continue-button'], button.ia-continueButton, button[type='submit']:has-text('Continue')"
                )
                if continue_btn and await continue_btn.is_visible():
                    break

            if continue_btn and await continue_btn.is_visible():
                c_lbl = ((await continue_btn.inner_text()) or "Continue").strip()
                logger.info(f"  ➡️ Clicking '{c_lbl}' to advance application...")
                await asyncio.sleep(random.uniform(1.0, 1.8))
                await self._human_click(
                    continue_btn,
                    hover_pause=(0.25, 0.5),
                    click_delay=(70, 120),
                    post_pause=(2.0, 3.0),
                )
                # Check if validation errors blocked moving to next step
                if await FormSelfHealer.has_validation_errors(target_page):
                    await FormSelfHealer.heal_errors(
                        page=target_page,
                        portal_name="indeed",
                        step_num=step,
                        job_title=job_title,
                        company=company,
                        gemini_client=self.gemini_client,
                    )
                    # Re-click Continue
                    re_continue = None
                    for container in active_containers:
                        re_continue = await container.query_selector(
                            "button:has-text('Review your application'), button:has-text('Review'), button:has-text('Continue'), button:has-text('Next'), button[data-testid='continue-button'], button.ia-continueButton"
                        )
                        if re_continue and await re_continue.is_visible():
                            break
                    if re_continue and await re_continue.is_visible():
                        await self._human_click(re_continue, hover_pause=(0.25, 0.5), post_pause=(2.0, 3.0))
                continue

        # Final check if on confirmation screen before exit
        if not target_page.is_closed():
            p_final = (await target_page.inner_text("body") if await target_page.query_selector("body") else "").lower()
            if any(phrase in p_final for phrase in ["your application was submitted", "application was submitted", "return to job search", "email confirmation"]):
                logger.info("  🎉 Indeed application submission confirmed on-screen at end of steps!")
                if target_page != self._page and target_page != root_page and not target_page.is_closed():
                    try:
                        await asyncio.sleep(2.5)
                        await target_page.close()
                    except Exception:
                        pass
                return "APPLIED"

        if target_page != self._page and target_page != root_page and not target_page.is_closed():
            try:
                await target_page.close()
            except Exception:
                pass
        return "INCOMPLETE"


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


async def run_indeed_auto_apply(
    keyword: str = None,
    keywords: list[str] = None,
    location: str = "India",
    target_applied: int = 40,
    max_jobs: int = 30,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run Indeed Browser Auto-Apply Agent across ALL matching resume roles.
    Applies target_applied count per portal (e.g. 40-50 apps) and advances to the next browser agent.
    """
    search_roles = []
    if keywords:
        search_roles = list(keywords)
    elif keyword:
        search_roles = [keyword] + [r for r in RESUME_MATCHING_ROLES if r.lower() != keyword.lower()]
    else:
        search_roles = list(RESUME_MATCHING_ROLES)

    agent = IndeedBrowserAgent(dry_run=dry_run)
    all_results = []
    total_applied = 0

    try:
        await agent.connect()

        for role_idx, current_keyword in enumerate(search_roles, 1):
            if total_applied >= target_applied:
                logger.info(f"🎯 Total portal target of {target_applied} applications reached on Indeed (applied: {total_applied})! Moving to next browser agent...")
                break

            logger.info(f"\n{'#'*65}\n🎯 [ROLE {role_idx}/{len(search_roles)}] Searching Indeed for: '{current_keyword}' ({location}) [Target: {target_applied} applied]\n{'#'*65}")

            role_applied = 0
            page_num = 0
            while role_applied < target_applied and total_applied < target_applied and page_num < 5:
                start_offset = page_num * 10
                logger.info(f"\n📄 [Indeed: '{current_keyword}'] Search Page {page_num + 1} (start={start_offset})...")
                
                url = (
                    f"https://in.indeed.com/jobs?"
                    f"q={quote_plus(current_keyword)}&"
                    f"l={quote_plus(location)}&"
                    f"fromage=1&"
                    f"start={start_offset}&"
                    f"sort=date"
                )
                await agent._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(4)
                await agent._check_and_wait_for_human_challenge()
                await agent._check_and_wait_for_signin()

                results, applied_on_page = await agent.extract_and_apply_jobs(
                    target_applied=target_applied - total_applied,
                    max_inspect_per_page=max_jobs,
                    current_keyword=current_keyword,
                    location=location,
                )
                all_results.extend(results)
                role_applied += applied_on_page
                total_applied += applied_on_page
                page_num += 1

                if total_applied >= target_applied:
                    logger.info(f"🎯 Target of {target_applied} applications reached on Indeed! Advancing to next portal...")
                    break

                if not results:
                    logger.info(f"🛑 No new jobs on page {page_num} for '{current_keyword}'.")
                    break

                # Check if Next Page exists on Indeed
                next_btn = await agent._page.query_selector(
                    "a[data-testid='pagination-page-next'], a[aria-label='Next Page'], a[aria-label='Next'], nav[aria-label='pagination'] a:has-text('Next')"
                )
                if not next_btn or not await next_btn.is_visible():
                    logger.info(f"🛑 No more pages for '{current_keyword}'.")
                    break

            logger.info(f"✅ Completed search for role [{role_idx}/{len(search_roles)}] '{current_keyword}'. Applied: {role_applied}. (Total session applied: {total_applied}/{target_applied})")

        logger.info(f"\n🏆 Indeed Full Multi-Role Sweep Complete! Total Applications Submitted: {total_applied}")
        return all_results
    finally:
        await agent.close()
