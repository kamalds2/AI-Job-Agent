"""
Wellfound (AngelList Talent) Auto-Apply Browser Agent.

Automates live searching on Wellfound (wellfound.com/jobs),
0-2 yrs experience filtering, tailored ATS PDF resume generation (resumes/wellfound/),
and auto-submitting applications via the 'Send application' modal with tailored responses to
'What interests you about working for this company?' and employer questions.

Features:
  - Real Google Chrome CDP (Remote Debugging Port 9222) connection & persistent profile (AgentProfile).
  - Multi-Role Sequential Sweep across target roles (Java Backend, Full Stack, Spring Boot, Python, AI Agent, Cloud).
  - Sort by Most Recent / Newest filter.
  - Strict 0-2 years experience filtering (skips 3+ yrs, 5+ yrs, Senior/Lead roles and high-exp modal warnings).
  - Deeply tailored 1-page ATS PDF resume generation in resumes/wellfound/.
  - AI-driven personalized message crafting answering 'What interests you about working for this company?'.
  - Human-like typing cadence and natural interaction emulation.
  - Live modal submission ('Send application') with full JobTracker recording.
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

from app.services.browser_tab_guard import (
    attach_context_blank_tab_monitor,
    clean_and_recover_blank_tabs,
    connect_or_launch_single_chrome,
)
from app.services.email_service import EmailService
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

WELLFOUND_PITCH_SYSTEM_PROMPT = """Act as an expert technical recruiter and career strategist. I am applying for a software engineering role and I need you to write a highly targeted, punchy, and confident application message.

Here is the situation:
- I am applying on a platform that asks a specific question (e.g., "What interests you about working for this company?" or "Note to recruiter").
- I have 2 years of highly impactful, fast-paced experience, but the job description might ask for more. You need to frame my 2 years of intense, high-ownership experience as equivalent to a mid-level engineer by highlighting my modern tech stack, AI-assisted execution speed, and ability to own features end-to-end.

RULES FOR THE MESSAGE:
1. Keep it short and punchy (under 130 words). Recruiters skim.
2. NO robotic, fluffy openings like "I am writing to express my interest in..." or "Hope this finds you well." Start directly with a strong hook about their company or product.
3. Map 2 specific requirements from their Job Description to exact technical achievements from my Resume.
4. Sound confident, hungry, and ready to execute. Do not apologize for years of experience; instead, highlight my velocity, ownership, and modern engineering practices.
5. End with a simple, confident call to action to discuss further.
6. Write strictly in first-person ("I", "my"). NEVER use third-person words ("he", "she", "Kamal", "the candidate").
7. Use the EXACT Company Name provided. NEVER write "X company", "x company", "[Company Name]", "[Insert Company Name]", or any bracketed placeholder.
8. Output ONLY the raw message text without quotes or markdown fences.
"""


class WellfoundExperienceAnalyzer:
    """Strict Experience filter for Wellfound job postings (0-2 years target)."""

    SENIOR_TITLE_PATTERNS = [
        r"\b(?:senior|sr\.?|lead|principal|staff|architect|manager|director|vp|vice\s+president|head\s+of|avp|svp|evp)\b",
        r"\b(?:tech\s*lead|team\s*lead|pod\s*lead|delivery\s*lead|module\s*lead)\b",
        r"\b(?:specialist|engineer|developer|consultant)\s+(?:iii|iv|v|vi|3|4|5|6)\b",
        r"\b(?:level\s*[3-9]|level\s*v|level\s*iv|l[3-9]|band\s*[3-9]|e[3-9])\b",
        r"\b(?:lead\s*(?:i{1,3}|iv|v))\b",
        r"\b(?:[3-9]|\d{2})\s*\+\s*(?:years?|yrs?)\b",
    ]

    MID_EXPERIENCE_PATTERNS = [
        r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?|yr)\b",
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:to|-|–|—)\s*\d+\s*(?:years?|yrs?|yr)\b",
        r"\b2\s*(?:to|-|–|—)\s*([4-9]|\d{2,})\s*(?:years?|yrs?|yr)\b",
        r"\b(?:minimum|min|at\s+least|overall|total|around|above|exceeding|more\s+than|requires?|requiring)\s+(?:of\s+)?([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\b",
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)(?:\s+of)?(?:\s+[\w\s]{1,35})?\s+(?:experience|exp|hands-on|industry|relevant)\b",
        r"\b([3-9]|\d{2,})\s*(?:years?|yrs?|yr)\s+(?:experience|exp)\s+(?:required|needed|mandatory|must\s+have)\b",
        r"\b(?:experience|exp)[\s:]*([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\b",
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

        # 4. Check for Early Career Signals
        for pat in cls.FRESHER_PATTERNS:
            m = re.search(pat, desc_lower) or re.search(pat, title_lower)
            if m:
                return {
                    "eligible": True,
                    "reason": f"Matched early-career experience signal: '{m.group(0)}'",
                    "exp_years": 1.5,
                }

        # Default eligible for standard roles
        return {
            "eligible": True,
            "reason": "Standard developer role (0-2 years eligible) -> Using 1.5 Years Resume Template.",
            "exp_years": 2.0,
        }


class WellfoundBrowserAgent:
    """Automated Browser Agent for Wellfound (wellfound.com/jobs)."""

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
        """Check if Chrome debugging port 9222 is open."""
        try:
            resp = httpx.get(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1.5)
            return resp.status_code == 200
        except Exception:
            return False

    def _launch_native_chrome(self):
        """Launch native Chrome process with port 9222."""
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
            fallback_url="https://wellfound.com/jobs",
            allowed_domains=["wellfound.com", "angel.co"],
            auto_refresh=False,
        )
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url="https://wellfound.com/jobs",
            allowed_domains=["wellfound.com", "angel.co"],
        )

        # Stealth overrides
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        logger.info("🔍 Checking Wellfound session status...")
        await self._page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._check_and_wait_for_signin()

    async def _check_and_wait_for_signin(self):
        """Check if Wellfound requires login and pause until the user signs in."""
        for attempt in range(300):
            try:
                current_url = self._page.url.lower()

                # Check for active logged-in indicators on Wellfound
                is_logged_in = await self._page.query_selector(
                    "a[href*='/jobs/applications'], a:has-text('Applications'), a:has-text('Messages'), a:has-text('Overview'), button[data-test='UserMenu'], button[aria-label*='User menu'], button[id*='user-menu'], a[href*='/profile'], a[href*='/settings'], img[alt*='Kamal'], img[alt*='profile'], img[alt*='avatar']"
                )
                if is_logged_in:
                    if attempt > 0:
                        logger.info("✅ Wellfound sign-in detected! Resuming agent...")
                    else:
                        logger.info("✅ Logged in to Wellfound successfully!")
                    return

                # If not logged in yet
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info("🔐  WELLFOUND (ANGELLIST) SIGN-IN REQUIRED!")
                    logger.info("👉  Please log in to your Wellfound account in the opened Chrome window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email="kamalkumar.doddi@gmail.com",
                                subject="🔐 [ACTION REQUIRED] Please Sign In to Wellfound",
                                body="Hello Kamal,\n\nThe Wellfound Auto-Apply Agent requires you to log in.\n\n👉 Please switch to the open Chrome browser window on your computer and sign in.\n\nThe agent will automatically detect that you have signed in and start applying immediately.\n\nBest,\nAI Job Agent"
                            )
                            logger.info("📧 Sent sign-in notification email to kamalkumar.doddi@gmail.com")
                        except Exception as e:
                            logger.warning(f"Could not send sign-in email: {e}")

                await asyncio.sleep(3.0)
            except Exception:
                await asyncio.sleep(2.0)

    # -------------------------------------------------------------------------
    # HUMAN-LIKE BEHAVIOR HELPERS
    # -------------------------------------------------------------------------
    async def _human_move_to(self, target_x: float, target_y: float, steps: int = 6):
        try:
            start_x = self._last_mouse_x or random.randint(300, 700)
            start_y = self._last_mouse_y or random.randint(300, 600)
            for i in range(1, steps + 1):
                t = i / steps
                cur_x = start_x + (target_x - start_x) * t + random.uniform(-4, 4) * (1 - t)
                cur_y = start_y + (target_y - start_y) * t + random.uniform(-4, 4) * (1 - t)
                await self._page.mouse.move(cur_x, cur_y)
                await asyncio.sleep(random.uniform(0.015, 0.04))
            await self._page.mouse.move(target_x, target_y)
            self._last_mouse_x = target_x
            self._last_mouse_y = target_y
        except Exception:
            pass

    async def _human_click(self, element, hover_pause: tuple[float, float] = (0.2, 0.45), click_delay: tuple[int, int] = (65, 125), post_pause: tuple[float, float] = (0.4, 0.8)):
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
        try:
            if not element:
                return
            await self._human_click(element, hover_pause=(0.1, 0.25), post_pause=(0.15, 0.3))
            await self._page.keyboard.press("Control+A")
            await asyncio.sleep(random.uniform(0.05, 0.12))
            await self._page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.08, 0.15))

            for ch in str(text):
                await self._page.keyboard.type(ch)
                delay = random.uniform(0.025, 0.075)
                if ch in (" ", ".", "\n", ",", "!", "?"):
                    delay += random.uniform(0.04, 0.09)
                await asyncio.sleep(delay)
            await asyncio.sleep(random.uniform(0.2, 0.45))
        except Exception:
            try:
                await element.fill(str(text))
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # AI CONTENT GENERATOR FOR WELLFOUND QUESTIONS
    # -------------------------------------------------------------------------
    def generate_wellfound_interest_answer(
        self,
        company: str,
        job_title: str,
        job_description: str,
        question_text: str = "What interests you about working for this company?",
    ) -> str:
        """Generate a tailored, high-converting answer in strictly first-person perspective ('I', 'my') using the career strategist prompt."""
        clean_company = company.replace("•", "").replace("Actively Hiring", "").strip() if company else "your team"
        if clean_company.lower() in ("startup", "company", "x company"):
            clean_company = "your engineering team"

        user_prompt = f"""Platform Question to Answer: {question_text}
Company Name: {clean_company}
Target Role: {job_title}

MY RESUME & TECHNICAL ACHIEVEMENTS:
- Core Stack: Java (17/21), Spring Boot microservices, Spring Cloud, Hibernate/JPA, RESTful APIs, Python (FastAPI/Django), React.js, Next.js, PostgreSQL, MySQL, Redis caching, Kafka message brokers, Docker, AWS (EC2, S3), CI/CD, Autonomous AI Agents (LangChain/LangGraph).
- Key Engineering Metrics: Engineered high-throughput Spring Boot microservices handling 10k+ req/sec, optimized database queries and caching reducing p99 latency by 35%, built autonomous AI automation pipelines and full-stack features end-to-end with high execution velocity. Immediate joiner (0 days notice).

JOB DESCRIPTION:
{job_description[:3000]}

Generate the targeted application message for {clean_company} addressing the question '{question_text}' now:"""

        if self.gemini_client:
            try:
                resp = self.gemini_client.generate_content(
                    prompt=user_prompt,
                    system_instruction=WELLFOUND_PITCH_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=2048,
                )
                if resp and len(resp.strip()) >= 50:
                    clean = resp.strip().replace("```", "").strip()
                    # Sanitize any accidental placeholders
                    clean = re.sub(r"\[(?:Insert\s+)?Company(?:\s+Name)?\]", clean_company, clean, flags=re.IGNORECASE)
                    clean = re.sub(r"\b[Xx]\s+company\b", clean_company, clean, flags=re.IGNORECASE)
                    clean = re.sub(r"\bcompany\s+x\b", clean_company, clean, flags=re.IGNORECASE)
                    logger.info(f"🤖 [AI Wellfound Pitch] Generated message for {clean_company} ({len(clean)} chars)")
                    return clean
            except Exception as e:
                logger.warning(f"AI message generation note: {e}")

        # High quality first-person fallback
        return (
            f"I am genuinely excited about {clean_company}'s product and engineering direction. "
            f"With 2 years of intense, high-ownership software engineering experience in Java, Spring Boot microservices, "
            f"REST APIs, Python, and AI agents, I have built and scaled high-uptime distributed systems and modern web applications. "
            f"I take full end-to-end ownership of features with rapid execution velocity. As an immediate joiner (0 days notice), "
            f"I would love to discuss how I can contribute to {clean_company}'s technical roadmap."
        )

    # -------------------------------------------------------------------------
    # SEARCH & APPLICATION FLOW
    # -------------------------------------------------------------------------
    async def search_and_filter_jobs(
        self,
        keywords: list[str] | str = None,
        location: str = "India",
    ):
        """Navigate to https://wellfound.com/jobs, enter all target roles into the search bar with Enter to accumulate search chips, set location, apply 0-2 yrs filter, and sort by most recent."""
        # Ensure we are always on https://wellfound.com/jobs (never wellfound.com/search)
        current_url = self._page.url.lower()
        if "wellfound.com/jobs" not in current_url or "wellfound.com/search" in current_url:
            logger.info("🌐 Navigating to Wellfound jobs base page: https://wellfound.com/jobs ...")
            await self._page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3.5)
        else:
            logger.info("🌐 Already on Wellfound jobs base page (https://wellfound.com/jobs)")

        # Determine roles list
        if isinstance(keywords, str):
            roles_list = [keywords] if keywords else RESUME_MATCHING_ROLES
        elif isinstance(keywords, list) and len(keywords) > 0:
            roles_list = keywords
        else:
            roles_list = [
                "Backend Engineer",
                "Java Backend Developer",
                "Java Full Stack Developer",
                "Spring Boot Developer",
                "Python Backend Developer",
            ]

        # 1. Type each role in 'Add a job title' dropdown / search bar and press Enter to accumulate search chips
        logger.info(f"🔍 [Multi-Role Search] Adding {len(roles_list)} target roles to search bar: {roles_list}")
        for r_idx, role_name in enumerate(roles_list, start=1):
            try:
                # Step A: Find and click the 'Add a job title' box strictly inside the 'Search for jobs' main content
                clicked_title_box = await self._page.evaluate("""
                    () => {
                        // Locate the main jobs search area (under 'Search for jobs')
                        const headers = Array.from(document.querySelectorAll("h1, h2, div")).filter(el => {
                            const t = (el.innerText || '').trim().toLowerCase();
                            return t === 'search for jobs';
                        });
                        const searchSection = headers.length > 0 ? (headers[0].closest("main") || headers[0].parentElement?.parentElement || document.body) : document.body;

                        // Find the job title container/input inside the searchSection (NOT in header or nav)
                        const candidates = Array.from(searchSection.querySelectorAll("div, button, input")).filter(el => {
                            if (el.closest("header") || el.closest("nav") || el.closest("[data-test='TopNav']")) return false;
                            const t = (el.innerText || el.placeholder || el.getAttribute('aria-label') || '').toLowerCase().trim();
                            return t.includes('add a job title') || t.includes('backend engineer') || (t.includes('job title') && !t.includes('search for jobs'));
                        });

                        if (candidates.length > 0) {
                            const target = candidates[0].querySelector("input") || candidates[0];
                            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            target.focus();
                            target.click();
                            return true;
                        }

                        return false;
                    }
                """)

                await asyncio.sleep(0.4)

                # Step B: Type the role directly via page keyboard or active element
                await self._page.keyboard.type(role_name, delay=40)
                await asyncio.sleep(0.5)

                # Step C: Check if a dropdown option appeared and click it, else press Enter
                selected_opt = await self._page.evaluate("""
                    (role) => {
                        const options = Array.from(document.querySelectorAll("li, div[role='option'], div[class*='menu'] div, div[class*='option'], div[class*='item']")).filter(el => {
                            if (el.closest("header") || el.closest("nav")) return false;
                            return (el.offsetParent !== null || el.getBoundingClientRect().height > 0);
                        });
                        const match = options.find(o => {
                            const t = (o.innerText || o.textContent || '').trim().toLowerCase();
                            return t === role.toLowerCase() || t.includes(role.toLowerCase());
                        });
                        if (match) {
                            match.click();
                            return true;
                        }
                        return false;
                    }
                """, role_name)

                if not selected_opt:
                    await self._page.keyboard.press("Enter")

                await asyncio.sleep(0.8)
                logger.info(f"  [{r_idx}/{len(roles_list)}] 🏷️ Added search chip: '{role_name}'")
            except Exception as r_err:
                logger.warning(f"Note adding role chip '{role_name}': {r_err}")

        await asyncio.sleep(1.0)

        # 2. Type Location in 'Add a location' dropdown / search bar strictly within 'Search for jobs' section
        try:
            if location:
                logger.info(f"📍 [Search Bar] Typing location: '{location}'...")
                # Step A: Find and click 'Add a location' container/input
                clicked_loc_box = await self._page.evaluate("""
                    () => {
                        const headers = Array.from(document.querySelectorAll("h1, h2, div")).filter(el => {
                            const t = (el.innerText || '').trim().toLowerCase();
                            return t === 'search for jobs';
                        });
                        const searchSection = headers.length > 0 ? (headers[0].closest("main") || headers[0].parentElement?.parentElement || document.body) : document.body;

                        const candidates = Array.from(searchSection.querySelectorAll("div, button, input")).filter(el => {
                            if (el.closest("header") || el.closest("nav") || el.closest("[data-test='TopNav']")) return false;
                            const t = (el.innerText || el.placeholder || el.getAttribute('aria-label') || '').toLowerCase().trim();
                            return t.includes('add a location') || t === 'location';
                        });

                        if (candidates.length > 0) {
                            const target = candidates[0].querySelector("input") || candidates[0];
                            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            target.focus();
                            target.click();
                            return true;
                        }
                        return false;
                    }
                """)

                await asyncio.sleep(0.4)
                await self._page.keyboard.type(location, delay=40)
                await asyncio.sleep(0.5)

                selected_loc = await self._page.evaluate("""
                    (loc) => {
                        const options = Array.from(document.querySelectorAll("li, div[role='option'], div[class*='menu'] div, div[class*='option']")).filter(el => {
                            if (el.closest("header") || el.closest("nav")) return false;
                            return (el.offsetParent !== null || el.getBoundingClientRect().height > 0);
                        });
                        const match = options.find(o => {
                            const t = (o.innerText || o.textContent || '').trim().toLowerCase();
                            return t === loc.toLowerCase() || t.startsWith(loc.toLowerCase());
                        });
                        if (match) {
                            match.click();
                            return true;
                        }
                        return false;
                    }
                """, location)

                if not selected_loc:
                    await self._page.keyboard.press("Enter")

                await asyncio.sleep(1.0)
                logger.info(f"✅ Location '{location}' entered in search bar!")
        except Exception as loc_err:
            logger.warning(f"Location input note: {loc_err}")

        # Ensure page stayed on https://wellfound.com/jobs and didn't redirect to /search
        if "wellfound.com/search" in self._page.url.lower():
            logger.warning("Detected accidental redirect to /search. Navigating back to https://wellfound.com/jobs...")
            await self._page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3.0)

        # 3. Open Filters Modal & Set 0-2 Years Experience Range
        try:
            exp_badge = await self._page.query_selector("div:has-text('0-2 years'), span:has-text('0-2 years'), button:has-text('0-2 years')")
            if not exp_badge or not await exp_badge.is_visible():
                logger.info("⚙️ Opening Wellfound Filters modal to set '0-2 years' experience...")
                filters_btn = await self._page.query_selector("button:has-text('Filters'), div:has-text('Filters')")
                if filters_btn and await filters_btn.is_visible():
                    await self._human_click(filters_btn, hover_pause=(0.2, 0.4), post_pause=(1.0, 1.5))
                    await asyncio.sleep(1.5)

                    # Inside Filter Modal: ensure 0-2 years experience is selected
                    try:
                        exp_opt = await self._page.query_selector("button:has-text('0-2 years'), div:has-text('0-2 years'), label:has-text('0-2')")
                        if exp_opt and await exp_opt.is_visible():
                            await self._human_click(exp_opt)
                        
                        no_exp_chk = await self._page.query_selector("label:has-text('Include jobs with no experience listed') input, input[type='checkbox']")
                        if no_exp_chk and not await no_exp_chk.is_checked():
                            await self._human_click(no_exp_chk)
                    except Exception as modal_f_err:
                        logger.debug(f"Filter option adjustment note: {modal_f_err}")

                    # Click 'View results' button
                    view_btn = await self._page.query_selector("button:has-text('View results'), button:has-text('View')")
                    if view_btn and await view_btn.is_visible():
                        await self._human_click(view_btn, hover_pause=(0.2, 0.4), post_pause=(1.5, 2.0))
                    else:
                        await self._page.keyboard.press("Escape")
                    await asyncio.sleep(2.0)
        except Exception as filter_err:
            logger.debug(f"Filter modal error: {filter_err}")

        # 4. Click 'Sort by' dropdown and select 'Most recent'
        try:
            logger.info("⚡ Checking Sort dropdown for 'Most recent'...")
            sort_btn = await self._page.query_selector(
                "button:has-text('Recommended'), div:has-text('Sort by:'), button:has-text('Sort'), div[class*='sort']"
            )
            if sort_btn and await sort_btn.is_visible():
                await self._human_click(sort_btn, hover_pause=(0.2, 0.4), post_pause=(0.6, 1.0))
                await asyncio.sleep(0.8)
                recent_opt = await self._page.query_selector(
                    "li:has-text('Most recent'), div[role='option']:has-text('Most recent'), button:has-text('Most recent'), span:has-text('Most recent')"
                )
                if recent_opt and await recent_opt.is_visible():
                    await self._human_click(recent_opt, hover_pause=(0.2, 0.3), post_pause=(1.5, 2.5))
                    logger.info("✅ Wellfound sorted by 'Most recent' successfully!")
                    await asyncio.sleep(2.5)
        except Exception as sort_err:
            logger.debug(f"Sort selection note: {sort_err}")

    async def _close_all_modals(self):
        """Robustly find and click the top-right cross (X) button, dismiss surveys/overlays, and ensure the page returns cleanly to the job listings."""
        for attempt in range(4):
            try:
                # 1. Check if any dialog, modal, drawer, or overlay is currently visible
                is_modal_visible = await self._page.evaluate("""
                    () => {
                        const dialogs = document.querySelectorAll("div[role='dialog'], div[class*='modal'], div[class*='Modal'], div[class*='drawer'], div[class*='Drawer'], div[class*='overlay'], div[class*='styles_modal'], div[class*='styles_container'], aside");
                        for (const d of dialogs) {
                            const rect = d.getBoundingClientRect();
                            if (rect.width > 50 && rect.height > 50) return true;
                        }
                        return false;
                    }
                """)

                if not is_modal_visible and attempt > 0:
                    break

                logger.info(f"❌ Clicking cross button to close open modal/drawer (attempt {attempt + 1})...")

                # 2. Click any visible Close / Cross button via JS execution
                clicked = await self._page.evaluate("""
                    () => {
                        // Priority 1: Top-right close buttons with aria-label or close class
                        const closeSelectors = [
                            "button[aria-label*='Close' i]",
                            "button[aria-label*='close' i]",
                            "button[data-test*='close' i]",
                            "button[class*='close' i]",
                            "button[class*='Close' i]",
                            "button[class*='styles_closeIcon']",
                            "button:has(svg[data-icon='xmark'])",
                            "button:has(svg.close)",
                            "button:has(svg[data-icon='x'])",
                            "svg[data-icon='xmark']",
                            "svg[data-icon='x']",
                            "aside button:first-of-type",
                            "div[role='dialog'] button:first-of-type"
                        ];
                        for (const sel of closeSelectors) {
                            const btns = Array.from(document.querySelectorAll(sel));
                            for (const b of btns) {
                                if (b.offsetParent !== null || b.getBoundingClientRect().height > 0) {
                                    b.click();
                                    return true;
                                }
                            }
                        }

                        // Priority 2: Look inside active dialog / drawer for SVG close button
                        const dialogs = document.querySelectorAll("div[role='dialog'], div[class*='modal'], aside, div[class*='drawer']");
                        for (const d of dialogs) {
                            const btns = Array.from(d.querySelectorAll("button"));
                            for (const b of btns) {
                                const txt = (b.innerText || '').trim();
                                const hasSvg = b.querySelector('svg');
                                if (txt === '✕' || txt === '×' || txt === 'X' || (hasSvg && txt.length === 0)) {
                                    b.click();
                                    return true;
                                }
                            }
                        }

                        // Priority 3: Dismiss / Skip / Done buttons on surveys
                        const actionBtns = Array.from(document.querySelectorAll("button")).filter(b => {
                            const txt = (b.innerText || '').trim().toLowerCase();
                            return ['skip', 'later', 'done', 'not now', 'close', 'cancel'].includes(txt);
                        });
                        if (actionBtns.length > 0 && actionBtns[0].offsetParent !== null) {
                            actionBtns[0].click();
                            return true;
                        }

                        return false;
                    }
                """)

                # Also try Playwright element handle click
                if not clicked:
                    cross_btn = await self._page.query_selector(
                        "button[aria-label*='Close' i], button.styles_closeIcon, svg[data-icon='xmark'], button:has(svg[data-icon='xmark']), div[role='dialog'] button:has(svg), aside button:has(svg)"
                    )
                    if cross_btn and await cross_btn.is_visible():
                        await self._human_click(cross_btn, hover_pause=(0.1, 0.2), post_pause=(0.3, 0.5))
                        clicked = True

                # Press Escape key
                await self._page.keyboard.press("Escape")
                await asyncio.sleep(0.6)

                # If still visible, click backdrop / left side of screen
                if not clicked:
                    await self._page.mouse.click(60, 200)
                    await asyncio.sleep(0.4)

            except Exception as e:
                logger.debug(f"Modal close attempt note: {e}")
                await self._page.keyboard.press("Escape")
                await asyncio.sleep(0.5)

        await asyncio.sleep(0.8)

    async def extract_and_apply_jobs(
        self,
        target_applied: int = 5,
        max_inspect_per_page: int = 25,
        current_keyword: str = "",
    ) -> tuple[list[dict], int]:
        """Inspect job cards on current Wellfound page, evaluate experience, and submit application."""
        results = []
        applied_count = 0

        # Scroll page down smoothly to trigger lazy-loaded listings
        try:
            await self._page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(1.5)
            await self._page.evaluate("window.scrollBy(0, -500)")
            await asyncio.sleep(1.0)
        except Exception:
            pass

        # Discover Job Elements (Cards with 'Learn more', 'Apply', or Job Links) from Wellfound DOM
        jobs_data = await self._page.evaluate("""
            () => {
                const results = [];
                const seenKeys = new Set();
                const NAV_FILTER = [
                    'home', 'applied', 'messages', 'saved', 'hidden', 'matches',
                    'overview', 'discover', 'tracker', 'settings', 'profile', 'apply'
                ];

                // 1. Look for all 'Learn more' and 'Apply' buttons or candidate job containers
                const allButtons = Array.from(document.querySelectorAll("button, a"));
                const candidateButtons = allButtons.filter(b => {
                    const txt = (b.innerText || b.textContent || "").trim();
                    return txt === "Learn more" || txt === "Apply" || (txt.startsWith("Apply") && !txt.toLowerCase().includes("filter") && !txt.toLowerCase().includes("applied"));
                });

                if (candidateButtons.length > 0) {
                    candidateButtons.forEach((btn, bIdx) => {
                        const card = btn.closest("div[data-test='JobListing']")
                                  || btn.closest("div[class*='styles_jobListing']")
                                  || btn.closest("div[class*='styles_result']")
                                  || btn.closest("div[class*='styles_component']")
                                  || btn.closest("div.border-b")
                                  || btn.closest("div.p-4")
                                  || btn.parentElement?.parentElement?.parentElement;
                        
                        if (!card) return;

                        let title = "";
                        let href = "";
                        const titleLink = card.querySelector("a[href*='/jobs/'], a[href*='/job/'], h2, h3, h4, a.font-semibold, div.font-semibold");
                        if (titleLink) {
                            title = (titleLink.innerText || titleLink.textContent || "").trim().split("\\n")[0].trim();
                            href = titleLink.getAttribute("href") || "";
                        }

                        if (!title) {
                            const lines = (card.innerText || "").split("\\n").map(s => s.trim()).filter(Boolean);
                            for (const l of lines) {
                                if (l.length > 3 && !NAV_FILTER.includes(l.toLowerCase()) && !l.toLowerCase().includes("apply") && !l.toLowerCase().includes("posted") && !l.toLowerCase().includes("active") && !l.toLowerCase().includes("learn more") && !l.toLowerCase().includes("save")) {
                                    title = l;
                                    break;
                                }
                            }
                        }

                        let company = "";
                        const compInCard = card.querySelector("a[href*='/company/'], a[href*='/companies/'], div.text-sm");
                        if (compInCard) {
                            const rawComp = (compInCard.innerText || compInCard.textContent || "").trim();
                            company = rawComp.split("•")[0].replace(/Actively Hiring/gi, "").trim();
                        }

                        if (!company) {
                            let p = card.parentElement;
                            while (p && p !== document.body && !company) {
                                const compEl = p.querySelector("h2, h3, a[href*='/company/'], a[href*='/companies/'], div.font-bold");
                                if (compEl && !compEl.contains(card)) {
                                    const rawComp = (compEl.innerText || compEl.textContent || "").trim();
                                    company = rawComp.split("•")[0].replace(/Actively Hiring/gi, "").trim();
                                }
                                p = p.parentElement;
                            }
                        }

                        if (!company) company = "Startup";
                        if (!title || NAV_FILTER.includes(title.toLowerCase()) || title.length < 3) return;

                        const fullHref = href ? (href.startsWith("http") ? href : "https://wellfound.com" + href) : window.location.href;
                        const key = (company + "_" + title).toLowerCase();

                        if (!seenKeys.has(key)) {
                            seenKeys.add(key);
                            results.push({
                                title: title,
                                company: company,
                                href: fullHref,
                                snippet: (card.innerText || card.textContent || "").trim(),
                                button_index: bIdx
                            });
                        }
                    });
                }

                // 2. Fallback: query distinct job link anchors if no direct buttons found
                if (results.length === 0) {
                    const links = Array.from(document.querySelectorAll("a[href*='/jobs/'], a[href*='/job/']")).filter(l => {
                        const h = (l.getAttribute("href") || "").toLowerCase();
                        return !NAV_FILTER.some(nav => h === `/jobs/${nav}` || h.endsWith(`/${nav}`));
                    });

                    for (const link of links) {
                        const href = link.getAttribute("href") || "";
                        if (!href) continue;

                        const title = (link.innerText || link.textContent || "").trim().split("\\n")[0].trim();
                        if (!title || title.length < 3 || NAV_FILTER.includes(title.toLowerCase())) continue;

                        const card = link.closest("div[data-test='JobListing']") || link.closest("div.border-b") || link.parentElement?.parentElement;
                        let company = "Startup";
                        if (card) {
                            const compEl = card.querySelector("a[href*='/company/'], h2, h3, div.text-sm");
                            if (compEl) company = (compEl.innerText || compEl.textContent || "").trim().split("\\n")[0].trim();
                        }

                        const fullHref = href.startsWith("http") ? href : ("https://wellfound.com" + href);
                        const key = (company + "_" + title).toLowerCase();

                        if (!seenKeys.has(key)) {
                            seenKeys.add(key);
                            results.push({
                                title: title,
                                company: company,
                                href: fullHref,
                                snippet: card ? (card.innerText || card.textContent || "").trim() : title,
                                button_index: -1
                            });
                        }
                    }
                }

                return results;
            }
        """)

        card_count = len(jobs_data)
        logger.info(f"📋 Discovered {card_count} real job listings on Wellfound")

        if card_count == 0:
            logger.warning("No job cards found on Wellfound for this keyword. Checking if page needs a reload or filter adjustment...")
            return results, applied_count

        total_to_inspect = min(card_count, max_inspect_per_page)

        for idx in range(total_to_inspect):
            if applied_count >= target_applied:
                logger.info(f"🎯 Target of {target_applied} applications reached for this role!")
                break

            job_meta = jobs_data[idx]
            title = job_meta.get("title") or "Software Engineer"
            company = job_meta.get("company") or "Startup"
            job_url = job_meta.get("href") or self._page.url
            snippet = job_meta.get("snippet") or ""

            # DEDUPLICATION CHECK 1
            if JobTracker.is_applied_or_emailed("wellfound", company, title, job_url):
                logger.info(f"⏭️ Skipping already applied job: '{title}' @ {company}")
                continue

            try:
                logger.info(f"\n[{idx + 1}/{total_to_inspect}] 🔎 [Wellfound] Processing: '{title}' @ {company}")

                # 1. OPEN JOB DETAILS — Click strictly on the JOB ROLE / TITLE link or Learn more (NEVER on company name)
                clicked_job = await self._page.evaluate("""
                    (jobIdx) => {
                        const candidateCards = Array.from(document.querySelectorAll(
                            "div[data-test='JobListing'], div[class*='styles_jobListing'], div[class*='styles_result'], div[class*='styles_component'], div.border-b"
                        ));
                        
                        let targetCard = candidateCards[jobIdx];
                        if (!targetCard) {
                            const btns = Array.from(document.querySelectorAll("button, a")).filter(b => {
                                const t = (b.innerText || '').trim();
                                return t === 'Learn more' || t === 'Apply';
                            });
                            if (btns[jobIdx]) {
                                btns[jobIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
                                btns[jobIdx].click();
                                return true;
                            }
                            return false;
                        }

                        targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });

                        // Priority 1: Direct 'Learn more' or 'Apply' button inside this card
                        const actionBtn = targetCard.querySelector("button:has-text('Learn more'), a:has-text('Learn more'), button:has-text('Apply'), a:has-text('Apply')")
                                       || Array.from(targetCard.querySelectorAll("button, a")).find(b => (b.innerText || '').trim() === 'Learn more' || (b.innerText || '').trim() === 'Apply');
                        if (actionBtn) {
                            actionBtn.click();
                            return true;
                        }

                        // Priority 2: Direct Job Role title link (explicitly NOT company links)
                        const roleLinks = Array.from(targetCard.querySelectorAll("a, h2, h3, h4, div.font-semibold")).filter(el => {
                            const href = (el.getAttribute('href') || '').toLowerCase();
                            const isCompanyLink = href.includes('/company/') || href.includes('/companies/');
                            const txt = (el.innerText || '').trim();
                            return !isCompanyLink && txt.length > 3 && !txt.toLowerCase().includes('actively hiring');
                        });

                        if (roleLinks.length > 0) {
                            roleLinks[0].click();
                            return true;
                        }

                        return false;
                    }
                """, idx)

                if not clicked_job:
                    # Fallback Playwright click on Learn more or Job Title
                    learn_more_btns = await self._page.query_selector_all("button:has-text('Learn more'), a:has-text('Learn more')")
                    if idx < len(learn_more_btns) and await learn_more_btns[idx].is_visible():
                        await learn_more_btns[idx].scroll_into_view_if_needed()
                        await self._human_click(learn_more_btns[idx], hover_pause=(0.3, 0.5), post_pause=(1.5, 2.5))
                        clicked_job = True

                if not clicked_job:
                    logger.warning(f"Could not click job role {idx + 1} ('{title}') in UI — skipping to next")
                    continue

                # Wait for right-side questionnaire / job drawer to appear
                await asyncio.sleep(2.0)

                # 2. EXTRACT FULL JOB DESCRIPTION FROM DETAILS VIEW (For tailoring resume & note)
                full_jd = snippet
                try:
                    jd_text = await self._page.evaluate("""
                        () => {
                            const selectors = [
                                "div[data-test='JobDescription']",
                                "div[class*='styles_description']",
                                "div[class*='jobDescription']",
                                "div[class*='styles_jobDetails']",
                                "div[class*='styles_component']",
                                "aside",
                                "div[role='dialog']",
                                "div.p-6",
                                "article",
                                "main"
                            ];
                            for (const sel of selectors) {
                                const el = document.querySelector(sel);
                                if (el && (el.innerText || '').length > 150) {
                                    return (el.innerText || el.textContent || '').trim();
                                }
                            }
                            return '';
                        }
                    """)
                    if jd_text and len(jd_text) > len(full_jd):
                        full_jd = jd_text
                except Exception:
                    pass

                # Refine company name from the opened drawer / modal if available
                try:
                    modal_comp = await self._page.evaluate("""
                        () => {
                            const modal = document.querySelector("div[role='dialog'], div[class*='modal'], aside, div[class*='drawer']");
                            if (modal) {
                                const h = modal.querySelector("h1, h2, h3, a[href*='/company/'], a[href*='/companies/'], div.font-bold");
                                if (h) {
                                    let t = (h.innerText || h.textContent || '').trim();
                                    if (t.toLowerCase().startsWith('apply to ')) t = t.substring(9).trim();
                                    t = t.split('•')[0].replace(/Actively Hiring/gi, '').trim();
                                    if (t.length > 2) return t;
                                }
                            }
                            return '';
                        }
                    """)
                    if modal_comp and len(modal_comp) > 2 and modal_comp.lower() not in ("startup", "company", "apply"):
                        company = modal_comp
                except Exception:
                    pass

                exp_years = 2.0
                template_name = "2+ Years Software Engineer"

                # 4. LOCATE APPLY BUTTON ON DETAILS VIEW / DRAWER
                apply_btn = None
                try:
                    # Check for Apply buttons on the open job view
                    candidates = await self._page.query_selector_all(
                        "div[role='dialog'] button:has-text('Apply'), aside button:has-text('Apply'), button:has-text('Apply'), a:has-text('Apply'), button[data-test*='Apply'], button[class*='styles_applyButton'], button[class*='styles_button']"
                    )
                    for c in candidates:
                        if await c.is_visible():
                            c_txt = (await c.inner_text()).strip()
                            if c_txt.lower() == "applied":
                                logger.info(f"ℹ️ Already applied to '{title}' @ {company}")
                                JobTracker.record_job("wellfound", company, title, job_url, status="ALREADY_APPLIED", job_url=job_url)
                                apply_btn = None
                                break
                            if "apply" in c_txt.lower() and "filter" not in c_txt.lower():
                                apply_btn = c
                                break
                except Exception as btn_err:
                    logger.debug(f"Apply button lookup note: {btn_err}")

                if not apply_btn:
                    logger.info(f"ℹ️ No active Apply button on '{title}' @ {company} — skipping")
                    JobTracker.record_job("wellfound", company, title, job_url, status="NO_APPLY_BUTTON", job_url=job_url)
                    await self._close_all_modals()
                    continue

                # 5. GENERATE TAILORED ATS PDF RESUME
                job_dict = {
                    "id": f"wf_{idx + 1}_{int(time.time())}",
                    "title": title,
                    "company": company,
                    "description": full_jd,
                }
                tailored_pdf_path = self.resume_service.generate_tailored_resume(
                    job=job_dict,
                    candidate_profile={},
                    exp_years=exp_years,
                    portal="wellfound",
                )
                logger.info(f"📄 Tailored ATS PDF Ready (resumes/wellfound/): {tailored_pdf_path}")

                # 6. CLICK APPLY BUTTON INSIDE DRAWER
                logger.info(f"🎯 Clicking Wellfound 'Apply' button for '{title}' @ {company}...")
                await self._human_click(apply_btn, hover_pause=(0.4, 0.7), post_pause=(2.0, 3.0))

                # 7. HANDLE WELLFOUND APPLICATION MODAL POPUP
                apply_status = await self._handle_wellfound_modal(
                    job_title=title,
                    company=company,
                    job_description=full_jd,
                    resume_pdf_path=tailored_pdf_path,
                )

                # Ensure all popups and drawer modals are completely closed before moving to next job
                await self._close_all_modals()

                if apply_status in ("APPLIED", "DRY_RUN_COMPLETED"):
                    applied_count += 1
                    logger.info(f"🎉 Wellfound Application Recorded! (Role applied: {applied_count}/{target_applied})")

                JobTracker.record_job("wellfound", company, title, job_url, status=apply_status, job_url=job_url)
                results.append({
                    "title": title,
                    "company": company,
                    "job_url": job_url,
                    "resume": tailored_pdf_path,
                    "template": template_name,
                    "status": apply_status,
                })

                # Human pacing delay
                delay = random.uniform(4.0, 7.0)
                logger.info(f"⏳ Pacing next inspection in {delay:.1f}s...")
                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing Wellfound job card {idx + 1}: {e}")
                await self._close_all_modals()

        return results, applied_count

    async def _handle_wellfound_modal(
        self,
        job_title: str,
        company: str,
        job_description: str,
        resume_pdf_path: str,
    ) -> str:
        """Handle the Wellfound Apply modal, check for constraints, write 1st-person note, click Apply, and dismiss popups."""
        # Wait up to 5s for modal to appear
        try:
            await self._page.wait_for_selector(
                "div[role='dialog'], textarea, button:has-text('Apply'), button:has-text('Send application'), button:has-text('Cancel')",
                timeout=5000,
            )
        except Exception:
            pass

        # Find Question / Textarea in Modal (e.g. 'What interests you about working for this company?')
        textareas = await self._page.query_selector_all("textarea")
        if not textareas:
            logger.warning("No textarea found in Wellfound application modal")
            await self._close_all_modals()
            return "MODAL_NO_TEXTAREA"

        main_textarea = textareas[0]
        
        # Extract question prompt text above textarea if available
        question_text = "What interests you about working for this company?"
        try:
            q_label = await self._page.evaluate("""
                (ta) => {
                    const parent = ta.closest('div');
                    if (parent) {
                        const label = parent.querySelector('label, h3, h4, p.font-medium, div.font-medium, p.font-semibold');
                        if (label) return (label.innerText || label.textContent || '').trim();
                    }
                    return 'What interests you about working for this company?';
                }
            """, main_textarea)
            if q_label and len(q_label) > 10:
                question_text = q_label
        except Exception:
            pass

        # Extract company name from modal header if available
        try:
            modal_comp = await self._page.evaluate("""
                () => {
                    const modal = document.querySelector("div[role='dialog'], div[class*='modal'], aside");
                    if (modal) {
                        const h = modal.querySelector("h1, h2, h3, a[href*='/company/'], a[href*='/companies/'], div.font-bold");
                        if (h) {
                            let t = (h.innerText || h.textContent || '').trim();
                            if (t.toLowerCase().startsWith('apply to ')) t = t.substring(9).trim();
                            t = t.split('•')[0].replace(/Actively Hiring/gi, '').trim();
                            if (t.length > 2 && !t.toLowerCase().includes('application')) return t;
                        }
                    }
                    return '';
                }
            """)
            if modal_comp and len(modal_comp) > 2 and modal_comp.lower() not in ("startup", "company", "x company", "apply"):
                company = modal_comp
        except Exception:
            pass

        logger.info(f"❓ Answering Wellfound question: '{question_text}' for {company}")
        pitch_message = self.generate_wellfound_interest_answer(
            company=company,
            job_title=job_title,
            job_description=job_description,
            question_text=question_text,
        )
        logger.info(f"✍️ Typing tailored 1st-person note to {company} ({len(pitch_message)} chars)...")
        await self._human_type(main_textarea, pitch_message)
        await asyncio.sleep(1.0)

        # Locate Apply button in the modal (black 'Apply' button or 'Send application')
        send_btn = await self._page.query_selector(
            "div[role='dialog'] button:has-text('Apply'), button:has-text('Apply'), button:has-text('Send application'), button:has-text('Submit application')"
        )

        if self.dry_run:
            logger.info("🧪 [DRY RUN] Prepared Wellfound application message successfully. Closing modal via Cancel / X...")
            await self._close_all_modals()
            return "DRY_RUN_COMPLETED"

        if send_btn and await send_btn.is_visible():
            logger.info("🚀 [LIVE] Clicking 'Apply' button to submit Wellfound application...")
            await self._human_click(send_btn, hover_pause=(0.3, 0.6), click_delay=(80, 130), post_pause=(2.0, 3.5))
            await asyncio.sleep(2.5)

            # Dismiss any subsequent AI interview / survey popup if it appears
            try:
                ai_popup = await self._page.query_selector(
                    "div[role='dialog']:has-text('interview'), div[role='dialog']:has-text('Survey'), div[role='dialog']:has-text('Feedback'), div[class*='overlay']"
                )
                if ai_popup and await ai_popup.is_visible():
                    logger.info("👋 Dismissing post-apply AI interview / survey popup...")
                    skip_btn = await ai_popup.query_selector("button:has-text('Skip'), button:has-text('Later'), button:has-text('Done'), button[aria-label='Close']")
                    if skip_btn and await skip_btn.is_visible():
                        await self._human_click(skip_btn)
                    else:
                        # Click outside popup
                        await self._page.evaluate("document.body.click()")
                    await asyncio.sleep(1.0)
            except Exception:
                pass

            # Close the main role modal popup to get back to search listing
            await self._close_all_modals()
            return "APPLIED"

        await self._close_all_modals()
        return "INCOMPLETE"

    async def close(self):
        """Safely disconnect or close browser resources."""
        try:
            if self._context and self._owns_context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
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


async def run_wellfound_auto_apply(
    keyword: str = None,
    keywords: list[str] = None,
    location: str = "India",
    target_applied: int = 5,
    max_jobs: int = 25,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run autonomous Wellfound auto-apply across matching resume roles.
    Adds all roles simultaneously into the Wellfound search bar as chips,
    applies 0-2 yrs filter, sorts by most recent, and applies up to target_applied jobs.
    """
    agent = WellfoundBrowserAgent(dry_run=dry_run)
    all_results = []

    search_roles = keywords or ([keyword] if keyword else [
        "Backend Engineer",
        "Java Backend Developer",
        "Java Full Stack Developer",
        "Spring Boot Developer",
        "Python Backend Developer",
    ])

    try:
        await agent.connect()

        logger.info("\n" + "#" * 65)
        logger.info(f"🎯 [WELLFOUND MULTI-ROLE SEARCH] Searching Wellfound for: {search_roles} [Target: {target_applied} applied]")
        logger.info("#" * 65)

        # 1. Enter all roles in the search bar to accumulate search chips
        await agent.search_and_filter_jobs(keywords=search_roles, location=location)

        # 2. Extract and apply to matching jobs on the page
        role_results, count = await agent.extract_and_apply_jobs(
            target_applied=target_applied,
            max_inspect_per_page=max_jobs,
            current_keyword=", ".join(search_roles[:3]),
        )
        all_results.extend(role_results)
        logger.info(f"📊 [WELLFOUND MULTI-ROLE SEARCH] Completed -> {count}/{target_applied} applications submitted.")

    except Exception as e:
        logger.error(f"Error during Wellfound auto-apply run: {e}", exc_info=True)
    finally:
        logger.info("🏁 Wellfound run completed. Preserving browser session.")

    return all_results
