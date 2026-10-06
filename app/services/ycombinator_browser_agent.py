"""
Y Combinator (Work at a Startup) Auto-Apply Browser Agent.

Automates live searching on Y Combinator / Work at a Startup (workatastartup.com/jobs),
0-2 yrs experience filtering, tailored ATS PDF resume generation (resumes/yc/),
and auto-submitting applications via the 'Reach out to {Hiring Lead}' modal.

Features:
  - Real Google Chrome CDP (Remote Debugging Port 9222) connection & persistent profile (AgentProfile).
  - Multi-Role Sequential Sweep across target roles (Java Backend, Full Stack, Spring Boot, Python, AI Agent, Cloud).
  - Sort by Newest filter application.
  - Strict 0-2 years experience filtering (skips 3+ yrs, 5+ yrs, Senior/Lead roles).
  - Deeply tailored 1-page ATS PDF resume generation in resumes/yc/.
  - AI-driven personalized message crafting to hiring managers based on company mission & JD.
  - Dynamic detection & answering of custom employer questions (e.g. 'What is something you built that you are proud of?').
  - Automatic checking of 'open to relocating' preference checkboxes.
  - Live modal submission ('Send') with full JobTracker recording.
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
    is_blank_url,
)
from app.services.email_service import EmailService
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

YC_MESSAGE_SYSTEM_PROMPT = """You are a highly articulate, persuasive job application assistant writing a personalized introductory message to a Y Combinator startup founder/hiring lead for candidate Doddi Kamal Kumar.

Candidate Profile:
- Name: Doddi Kamal Kumar (Kamal Doddi)
- Email: kamalkumar.doddi@gmail.com | Phone: +91-9398872099 | Location: Hyderabad, India
- Experience: 1.5 - 2 years of professional software / backend engineering experience
- Core Stack: Java, Spring Boot, Microservices Architecture, REST APIs, Spring Security, Python, FastAPI, React.js, MySQL, PostgreSQL, AWS (EC2, VPC, S3), Docker, AI Agents (LangGraph/LangChain), Generative AI, Prompt Engineering.
- Availability: Immediate joiner (0 days notice period)
- Relocation: Fully open and eager to relocate anywhere (worldwide / in-office / hybrid) or work remotely.
- Key Accomplishments:
  * Engineered enterprise-scale microservices backend using Java Spring Boot & React.js, reducing synchronization latency by 20%.
  * Built autonomous multi-agent AI systems orchestrating LLMs, browser automations, and external APIs.
  * Developed real-time AI conversational voice assistants integrating speech-to-text, reasoning, and synthesis.

Guidelines for Main Outreach Message:
1. Address the recipient by name if provided (e.g., "Hi Alex," or "Hi Chris,").
2. Keep it punchy, authentic, human, and between 75–120 words (must be at least 50+ characters).
3. Connect Kamal's relevant technical strengths (e.g. backend systems, Java/Spring Boot, Python, AI agents, cloud) directly to the company's product/mission from the JD.
4. Mention immediate availability (0 days notice) and complete openness to relocation.
5. Do NOT include markdown code fences or generic platitudes — return plain text message ready to send.
"""

YC_QUESTION_SYSTEM_PROMPT = """You are answering a specific employer application question on behalf of candidate Doddi Kamal Kumar.
Candidate: Software Engineer with 1.5 - 2 years experience in Java, Spring Boot, Microservices, Python, AI Agents, AWS, and modern full-stack development.
Education: B.Tech in CSE (2024, 8.0 CGPA).
Projects: Autonomous Multi-Agent AI Job Orchestrator, 24/7 AI Voice Assistant, McLean Enterprise Facility System (Spring Boot + React).

Guidelines:
- Answer directly and compellingly under 150 words (or character limit if specified).
- Highlight genuine engineering achievements, problem solving, scale, and technical depth.
- Return plain text only.
"""


class YCExperienceAnalyzer:
    """Strict Experience filter for Y Combinator job postings (0-2 years target)."""

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

        # Default eligible for standard general roles
        return {
            "eligible": True,
            "reason": "Standard developer role (0-2 years eligible) -> Using 1.5 Years Resume Template.",
            "exp_years": 2.0,
        }


class YCombinatorBrowserAgent:
    """Automated Browser Agent for Y Combinator / Work at a Startup (workatastartup.com/jobs)."""

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

        if not self.is_cdp_port_open():
            self._launch_native_chrome()
            for _ in range(12):
                await asyncio.sleep(1.0)
                if self.is_cdp_port_open():
                    break

        connected_via_cdp = False
        try:
            if self.is_cdp_port_open():
                logger.info(f"🔌 Connecting to real Google Chrome on port {self.cdp_port}...")
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self.cdp_port}",
                    timeout=15000,
                )
                contexts = self._browser.contexts
                self._context = contexts[0] if contexts else await self._browser.new_context()
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
                self._is_cdp = True
                connected_via_cdp = True
                logger.info("✅ Connected to live Chrome instance!")
        except Exception as e:
            logger.warning(f"CDP connection attempt note: {e}. Falling back to persistent launch...")

        if not connected_via_cdp:
            logger.info("🚀 Launching persistent Google Chrome for Y Combinator Agent...")
            try:
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    executable_path=self.chrome_path,
                    headless=False,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    viewport=None,
                )
            except Exception:
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile2"),
                    executable_path=self.chrome_path,
                    headless=False,
                    args=["--start-maximized"],
                    viewport=None,
                )

            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()

        # Stealth overrides
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        target_initial_url = "https://www.workatastartup.com/jobs?demographic=any&hasEquity=any&hasSalary=any&industry=any&interviewProcess=any&jobType=any&layout=list-compact&query=full%20stack%20developer&remote=yes&sortBy=keyword&tab=any&usVisaNotRequired=any"

        # Clean any stuck about:blank or secondary tabs and attach context monitor
        self._page, _ = await clean_and_recover_blank_tabs(
            self._context,
            self._page,
            fallback_url=target_initial_url,
            allowed_domains=["workatastartup.com", "ycombinator.com"],
        )
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url=target_initial_url,
            allowed_domains=["workatastartup.com", "ycombinator.com"],
        )

        # Navigate to Work at a Startup Jobs
        logger.info("🔍 Checking Y Combinator / Work at a Startup session status...")
        await self._page.goto(target_initial_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._check_and_wait_for_signin()

    async def _check_and_wait_for_signin(self):
        """Check if Y Combinator / Work at a Startup requires login and pause until the user signs in."""
        for attempt in range(300):
            try:
                current_url = self._page.url.lower()

                # Check for active logged in session
                is_logged_in = await self._page.query_selector(
                    "a:has-text('My profile'), div:has-text('My profile'), a[href*='/candidate'], a[href*='/profile'], a[href*='/users/edit'], a:has-text('Account'), button[aria-label*='User menu'], button[aria-label*='Account'], img[alt*='Kamal'], img[alt*='profile'], img[alt*='avatar']"
                )
                if is_logged_in and not any(p in current_url for p in ["sign_in", "login", "auth", "account.ycombinator.com"]):
                    if attempt > 0:
                        logger.info("✅ Y Combinator sign-in detected! Resuming agent...")
                    else:
                        logger.info("✅ Logged in to Y Combinator (Work at a Startup) successfully!")
                    return

                # If not logged in yet
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info("🔐  Y COMBINATOR (WORK AT A STARTUP) SIGN-IN REQUIRED!")
                    logger.info("👉  Please log in to your YC / Work at a Startup account in the opened Chrome window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email="kamalkumar.doddi@gmail.com",
                                subject="🔐 [ACTION REQUIRED] Please Sign In to Y Combinator / Work at a Startup",
                                body="Hello Kamal,\n\nThe Y Combinator Auto-Apply Agent requires you to log in.\n\n👉 Please switch to the open Chrome browser window on your computer and sign in.\n\nThe agent will automatically detect that you have signed in and start applying immediately.\n\nBest,\nAI Job Agent"
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
    # AI CONTENT GENERATORS FOR YC OUTREACH
    # -------------------------------------------------------------------------
    def generate_hiring_manager_message(
        self,
        recipient_name: str,
        company: str,
        job_title: str,
        job_description: str,
    ) -> str:
        """Generate a personalized, tailored message to the YC founder/hiring lead."""
        clean_name = recipient_name.strip() if recipient_name else ""
        is_generic_team = (
            not clean_name
            or clean_name.lower() in ["the team", "team", "the", "someone", "hiring team", "recruiting team", "founders", "founder"]
        )

        if not is_generic_team:
            name_greeting = f"Hi {clean_name},"
        else:
            name_greeting = f"Dear Recruiting Team at {company},"

        prompt = f"""Target Company: {company}
Target Role: {job_title}
Recipient / Greeting: {name_greeting}
Job Description Summary:
{job_description[:3000]}

Write the personalized introductory outreach message starting with '{name_greeting}'.
Mention Kamal's strong engineering alignment with the required stack, immediate availability (0 days notice), and complete openness to relocate."""

        if self.gemini_client:
            try:
                resp = self.gemini_client.generate_content(
                    prompt=prompt,
                    system_instruction=YC_MESSAGE_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=300,
                )
                if resp and len(resp.strip()) >= 50:
                    clean = resp.strip().replace("```", "").strip()
                    logger.info(f"🤖 [AI YC Pitch Generator] Generated customized message for {clean_name or company} ({len(clean)} chars)")
                    return clean
            except Exception as e:
                logger.warning(f"AI message generation note: {e}")

        # Robust Fallback
        return (
            f"{name_greeting}\n\n"
            f"I came across the {job_title} role at {company} and was immediately drawn to what your team is building. "
            f"I have 1.5 - 2 years of backend and full-stack engineering experience specializing in Java, Spring Boot microservices, "
            f"Python, REST APIs, and building autonomous AI agent workflows. "
            f"I am an immediate joiner (0 days notice) and fully open to relocating or working in-person. "
            f"I would love the chance to contribute to {company}'s growth!"
        )

    def generate_custom_question_answer(
        self,
        question_text: str,
        company: str,
        job_title: str,
        job_description: str,
    ) -> str:
        """Generate tailored answers for custom employer questions (e.g. proudest build, technical problem solved)."""
        prompt = f"""Question from {company} for role '{job_title}':
"{question_text}"

Job Description Context:
{job_description[:2000]}

Provide a concise, direct answer under 150 words highlighting Kamal Doddi's technical excellence, architecture decisions, and quantifiable impact."""

        if self.gemini_client:
            try:
                resp = self.gemini_client.generate_content(
                    prompt=prompt,
                    system_instruction=YC_QUESTION_SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=250,
                )
                if resp and len(resp.strip()) > 20:
                    clean = resp.strip().replace("```", "").strip()
                    logger.info(f"🤖 [AI Custom Question] '{question_text[:40]}...' -> ({len(clean)} chars)")
                    return clean
            except Exception as e:
                logger.warning(f"AI question answer note: {e}")

        q_lower = question_text.lower()
        if "built" in q_lower or "proud" in q_lower or "project" in q_lower:
            return (
                "I am disproportionately proud of architecting an Autonomous Multi-Agent AI Job Application system that integrates "
                "real-time Chrome CDP automation, deep AST/DOM parsing, and dynamic LLM reasoning. It dynamically generates tailored ATS-compliant "
                "resumes per job description, resolves dynamic employer questionnaires, and self-heals against layout changes. "
                "I also built the McLean Enterprise Facility System using Java Spring Boot microservices, optimizing database transactions and reducing latency by 20%."
            )
        elif "relocate" in q_lower or "location" in q_lower:
            return "Yes, I am fully open and eager to relocate immediately for this role."
        elif "notice" in q_lower or "start" in q_lower:
            return "I am an immediate joiner and can start in 0 days."
        else:
            return "With 1.5 - 2 years of hands-on experience in Java, Spring Boot, Microservices, Python, and AI Agent workflows, I focus on building resilient, low-latency distributed systems and shipping customer-focused features quickly."

    # -------------------------------------------------------------------------
    # SEARCH & APPLICATION FLOW
    # -------------------------------------------------------------------------
    async def search_and_sort_newest(self, keyword: str):
        """Navigate to YC Work at a Startup using the exact jobs search URL (compact layout, remote ok, query per role)."""
        search_url = (
            f"https://www.workatastartup.com/jobs?"
            f"demographic=any&hasEquity=any&hasSalary=any&industry=any&interviewProcess=any&jobType=any&"
            f"layout=list-compact&query={quote_plus(keyword)}&remote=yes&"
            f"sortBy=keyword&tab=any&usVisaNotRequired=any"
        )
        self._current_search_url = search_url
        logger.info(f"🌐 Navigating to YC Work at a Startup Jobs for '{keyword}' (jobs feed, Remote OK)...")
        await self._page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3.5)

        # Check if page was steered away into candidate profile
        if any(p in self._page.url.lower() for p in ["/candidate", "/profile", "/users/edit"]):
            logger.warning(f"⚠️ [YC Guard] Landed on candidate profile page ('{self._page.url}'). Re-navigating to jobs search URL...")
            await self._page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.5)

    async def _find_yc_apply_button(self):
        """Find the real orange Apply / Reach Out button on YC Work at a Startup job details page, strictly excluding profile and navigation links."""
        try:
            js_btn = await self._page.evaluate_handle("""
                () => {
                    const allCandidates = Array.from(document.querySelectorAll("a, button, div[role='button']"));
                    for (const el of allCandidates) {
                        if (!el.offsetParent && el.offsetWidth === 0 && el.offsetHeight === 0) continue;
                        
                        const href = (el.getAttribute('href') || '').toLowerCase();
                        // CRITICAL: Exclude candidate profile, navigation links, and settings (never click /application)
                        if (href.includes('/application') || href.includes('/candidate') || href.includes('/profile') || 
                            href.includes('/users') || href.includes('/inbox') || href.includes('/conversations') || 
                            href.includes('/companies') || href.includes('/events') || href.includes('/jobs')) {
                            if (href.length > 0 && !href.startsWith('#') && !href.startsWith('javascript:')) {
                                continue;
                            }
                        }
                        
                        const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                        const cls = (el.className || '').toLowerCase();
                        
                        // Strict check: must not be a navigation tab or menu item
                        if (txt.includes('my profile') || txt.includes('inbox') || txt.includes('companies & jobs') || 
                            txt.includes('filter') || txt.includes('sign in') || txt.includes('log in') || 
                            txt.includes('education') || txt.includes('clear filter')) {
                            continue;
                        }
                        
                        const isApplyText = txt === 'apply' || 
                                            txt === 'apply to this job' || 
                                            txt === 'apply to company' || 
                                            txt === 'reach out' || 
                                            txt.startsWith('reach out to') || 
                                            txt.startsWith('apply to');
                                            
                        if (isApplyText) {
                            return el;
                        }
                        
                        // Check button classes (orange brand button on YC)
                        if ((cls.includes('bg-orange') || cls.includes('bg-brand') || cls.includes('bg-waas')) && 
                            (txt.includes('apply') || txt.includes('reach out'))) {
                            return el;
                        }
                    }
                    return null;
                }
            """)
            if js_btn and js_btn.as_element() and await js_btn.as_element().is_visible():
                return js_btn.as_element()
        except Exception as e:
            logger.debug(f"Apply button search error: {e}")

        # Fallback to direct Playwright locator on the orange button
        try:
            orange_btn = self._page.locator("a.bg-orange-500, button.bg-orange-500, a.bg-brand, button.bg-brand").first
            if await orange_btn.count() > 0 and await orange_btn.is_visible():
                txt = ((await orange_btn.inner_text()) or "").strip().lower()
                if "apply" in txt or "reach" in txt:
                    return orange_btn
        except Exception:
            pass

        return None

    async def extract_and_apply_jobs(
        self,
        target_applied: int = 5,
        max_inspect_per_page: int = 25,
        current_keyword: str = "",
    ) -> tuple[list[dict], int]:
        """Inspect job listings on YC Work at a Startup, evaluate experience, and submit applications."""
        results = []
        applied_count = 0

        # Discover Job Elements from Work at a Startup DOM
        jobs_data = await self._page.evaluate(r"""
            () => {
                const results = [];
                const seenLinks = new Set();
                const links = Array.from(document.querySelectorAll("a[href*='/jobs/'], a.job-name"));

                links.forEach((linkEl) => {
                    const href = linkEl.getAttribute("href") || "";
                    if (!href || seenLinks.has(href)) return;

                    // Filter out category directory links
                    if (href.includes('/jobs/r/') || href.includes('/jobs/l/') || href.includes('/jobs/san-francisco') || href.includes('/jobs/new-york')) return;

                    const title = (linkEl.innerText || linkEl.textContent || '').trim();
                    if (!title || title.length < 2 || title.toLowerCase().includes("jobs in") || title.toLowerCase() === 'view job') return;

                    const container = linkEl.closest("div.job-details, div.job-card, div.w-full, tr, li, div.p-4, div.border") || linkEl.parentElement;
                    const companyEl = container ? container.querySelector("a[href*='/companies/'], span.company-name, div.company-name, .font-semibold") : null;
                    let rawCompany = (companyEl ? (companyEl.innerText || companyEl.textContent) : '').trim() || "YC Startup";
                    // Clean company name: e.g. "Mason (W16)•Mason is the fastest..." -> "Mason"
                    let company = rawCompany.split(/[\(•\n\r|]/)[0].trim() || "YC Startup";
                    const snippet = container ? (container.innerText || container.textContent || '').trim() : title;

                    seenLinks.add(href);
                    results.push({
                        href: href.startsWith('http') ? href : ('https://www.workatastartup.com' + href),
                        title: title,
                        company: company,
                        snippet: snippet
                    });
                });
                return results;
            }
        """)

        card_count = len(jobs_data)
        logger.info(f"📋 Discovered {card_count} unique job listings on YC Work at a Startup")

        total_to_inspect = min(card_count if card_count > 0 else max_inspect_per_page, max_inspect_per_page)

        for idx in range(total_to_inspect):
            # Guard against any stuck about:blank or secondary popup tabs
            search_url = getattr(self, "_current_search_url", "https://www.workatastartup.com/jobs")
            self._page, _ = await clean_and_recover_blank_tabs(
                self._context,
                self._page,
                fallback_url=search_url,
                allowed_domains=["workatastartup.com", "ycombinator.com"],
            )

            # Auto-recover if active page landed on candidate profile page
            if any(p in self._page.url.lower() for p in ["/candidate", "/profile", "/users/edit"]):
                logger.warning(f"⚠️ [YC Guard] Detected profile page ('{self._page.url}'). Navigating back to jobs search...")
                await self._page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.0)

            if applied_count >= target_applied:
                logger.info(f"🎯 Target of {target_applied} applications reached for this role!")
                break

            job_meta = jobs_data[idx]
            title = job_meta.get("title") or "Software Engineer"
            company = job_meta.get("company") or "YC Startup"
            job_url = job_meta.get("href") or self._page.url
            snippet = job_meta.get("snippet") or ""

            # DEDUPLICATION CHECK 1
            if JobTracker.is_applied_or_emailed("ycombinator", company, title, job_url):
                logger.info(f"⏭️ Skipping already applied job: '{title}' @ {company}")
                continue

            # FAST TITLE SCREENING
            title_screening = YCExperienceAnalyzer.analyze_title(title)
            if not title_screening["eligible"]:
                logger.info(f"\n[{idx + 1}/{total_to_inspect}] ⏩ Skipping '{title}' @ {company} — {title_screening['reason']}")
                JobTracker.record_job("ycombinator", company, title, job_url, status="SKIPPED_EXP", job_url=job_url)
                results.append({"title": title, "company": company, "reason": title_screening["reason"], "status": "SKIPPED_EXP"})
                continue

            try:
                # Open job details (navigate or open tab)
                logger.info(f"\n[{idx + 1}/{total_to_inspect}] 🔎 [YC] Opening & Inspecting: '{title}' @ {company}")
                
                # Navigate page to job_url to view full JD
                await self._page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.5)

                if is_blank_url(self._page.url):
                    logger.warning(f"⚠️ [YC Tab Guard] Navigation to '{job_url}' opened as 'about:blank'. Refreshing...")
                    await self._page.reload(wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2.0)

                # Scroll down to hydrate entire JD body
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await asyncio.sleep(0.5)

                # Multi-source full JD extraction
                full_jd_text = await self._page.evaluate("""
                    () => {
                        const parts = [];
                        const main = document.querySelector("div.job-description, div.prose, #job-description, div[class*='description'], div[class*='jobDetails'], main");
                        if (main) parts.push(main.innerText || main.textContent || '');
                        parts.push(document.body.innerText || '');
                        return parts.join('\\n\\n');
                    }
                """)

                job_desc = full_jd_text.strip() if full_jd_text else snippet

                # EXPERIENCE ELIGIBILITY ANALYSIS
                analysis = YCExperienceAnalyzer.analyze(job_title=title, job_description=job_desc)
                if not analysis["eligible"]:
                    logger.info(f"⏩ Skipping '{title}' @ {company} — {analysis['reason']}")
                    JobTracker.record_job("ycombinator", company, title, job_url, status="SKIPPED_EXP", job_url=job_url)
                    results.append({"title": title, "company": company, "reason": analysis["reason"], "status": "SKIPPED_EXP"})
                    continue

                exp_years = analysis["exp_years"]
                template_name = "2+ Years Software Engineer" if exp_years >= 2.0 else "1.5 Years Full Stack Developer"
                logger.info(f"✅ Experience Matched: {analysis['reason']}")
                logger.info(f"📑 Eligible for: {template_name} (exp_years={exp_years})")

                # Generate tailored ATS PDF resume
                job_dict = {
                    "id": f"yc_{idx + 1}_{int(time.time())}",
                    "title": title,
                    "company": company,
                    "description": job_desc,
                }
                tailored_pdf_path = self.resume_service.generate_tailored_resume(
                    job=job_dict,
                    candidate_profile={},
                    exp_years=exp_years,
                    portal="yc",
                )
                logger.info(f"📄 Tailored ATS PDF Ready (resumes/yc/): {tailored_pdf_path}")

                # Locate the Apply / Reach out button across all possible YC elements
                apply_btn = await self._find_yc_apply_button()
                if not apply_btn or not await apply_btn.is_visible():
                    logger.info(f"ℹ️ No active Apply button on '{title}' @ {company} — skipping")
                    JobTracker.record_job("ycombinator", company, title, job_url, status="NO_APPLY_BUTTON", job_url=job_url)
                    continue

                btn_text = ((await apply_btn.inner_text()) or "Apply").strip()
                logger.info(f"🎯 Clicking YC '{btn_text}' button with natural movement...")
                await self._human_click(apply_btn, hover_pause=(0.3, 0.6), post_pause=(1.5, 2.5))

                # Handle Modal Popup ('Reach out to {Name} at {Company}')
                apply_status = await self._handle_yc_modal(
                    job_title=title,
                    company=company,
                    job_description=job_desc,
                    resume_pdf_path=tailored_pdf_path,
                )

                if apply_status in ("APPLIED", "DRY_RUN_COMPLETED"):
                    applied_count += 1
                    logger.info(f"🎉 Y Combinator Application Recorded! (Role applied: {applied_count}/{target_applied})")

                JobTracker.record_job("ycombinator", company, title, job_url, status=apply_status, job_url=job_url)
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
                logger.error(f"Error processing YC job card {idx + 1}: {e}")

        return results, applied_count

    async def _handle_yc_modal(
        self,
        job_title: str,
        company: str,
        job_description: str,
        resume_pdf_path: str,
    ) -> str:
        """Handle the YC Reach Out modal popup, fill textareas and answers, check relocation box, and send."""
        # Wait up to 5s for modal to appear
        try:
            await self._page.wait_for_selector(
                "div[role='dialog'], div.modal, textarea, button:has-text('Send'), button:has-text('Close')",
                timeout=5000,
            )
        except Exception:
            pass

        # Extract Recipient / Hiring Manager name & Company directly from the 1st line of the live modal dialog
        recipient_name = ""
        modal_company = company
        try:
            modal_header_info = await self._page.evaluate("""
                () => {
                    const dialog = document.querySelector("div[role='dialog'], div.modal, [aria-modal='true']");
                    const root = dialog || document;
                    
                    // Search for heading or 1st prominent text element in modal
                    const candidates = Array.from(root.querySelectorAll("h1, h2, h3, div.text-xl, div.text-lg, div.font-bold, div.font-semibold, p"));
                    for (const el of candidates) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (txt.toLowerCase().includes("reach out") || txt.toLowerCase().includes("start a conversation with")) {
                            return txt;
                        }
                    }
                    
                    // Fallback to first non-empty heading
                    const firstHeading = root.querySelector("h1, h2, h3");
                    if (firstHeading) {
                        return (firstHeading.innerText || firstHeading.textContent || '').trim();
                    }
                    return "";
                }
            """)

            if modal_header_info:
                logger.info(f"📋 YC Live Modal 1st Line: '{modal_header_info}'")

                # Pattern A: "Reach out to the team at <Company>" or "Reach out to team at <Company>"
                m_team = re.search(r"Reach\s+out\s+to\s+(?:the\s+team|team|the\s+founders|founders)\s+at\s+([A-Za-z0-9\s\.\-_&]+)", modal_header_info, re.IGNORECASE)
                if m_team:
                    extracted_comp = m_team.group(1).strip()
                    if extracted_comp:
                        modal_company = extracted_comp
                    recipient_name = ""  # No individual person, use team greeting
                else:
                    # Pattern B: "Reach out to <Person> at <Company>"
                    m_person = re.search(r"Reach\s+out\s+to\s+(.+?)\s+at\s+([A-Za-z0-9\s\.\-_&]+)", modal_header_info, re.IGNORECASE)
                    if m_person:
                        p_name = m_person.group(1).strip()
                        extracted_comp = m_person.group(2).strip()
                        if extracted_comp:
                            modal_company = extracted_comp
                        if p_name.lower() in ["the team", "team", "the", "a team", "hiring team", "founders", "recruiting team", "the founders"]:
                            recipient_name = ""
                        else:
                            recipient_name = p_name
                    else:
                        # Pattern C: "Reach out to <Company>"
                        m_comp = re.search(r"Reach\s+out\s+to\s+([A-Za-z0-9\s\.\-_&]+)", modal_header_info, re.IGNORECASE)
                        if m_comp:
                            extracted_comp = m_comp.group(1).strip()
                            if extracted_comp.lower() not in ["the team", "team"]:
                                modal_company = extracted_comp
                            recipient_name = ""
                        else:
                            # Pattern D: "Start a conversation with the team at <Company>"
                            m_conv = re.search(r"with\s+the\s+team\s+at\s+([A-Za-z0-9\s\.\-_&]+)", modal_header_info, re.IGNORECASE)
                            if m_conv:
                                modal_company = m_conv.group(1).strip()
                                recipient_name = ""

            logger.info(f"🎯 Target Context: Recruiter='{recipient_name or 'Dear Recruiting Team at ' + modal_company}', Company='{modal_company}'")
        except Exception as e:
            logger.warning(f"Modal header extraction note: {e}")

        # 1. Main Outreach Message Textarea
        textareas = await self._page.query_selector_all("textarea")
        if not textareas:
            logger.warning("No textarea found in YC application modal")
            return "MODAL_NO_TEXTAREA"

        main_textarea = textareas[0]
        outreach_message = self.generate_hiring_manager_message(
            recipient_name=recipient_name,
            company=modal_company,
            job_title=job_title,
            job_description=job_description,
        )
        logger.info(f"✍️ Typing personalized message to {recipient_name or modal_company} ({len(outreach_message)} chars)...")
        await self._human_type(main_textarea, outreach_message)
        await asyncio.sleep(1.0)

        # 2. Dynamic Custom Question Textareas (if modal has secondary textareas)
        if len(textareas) > 1:
            for extra_idx, extra_ta in enumerate(textareas[1:], start=2):
                # Try to extract question label above the textarea
                question_label = await self._page.evaluate(
                    """(el) => {
                        let prev = el.previousElementSibling;
                        while (prev) {
                            const txt = (prev.innerText || prev.textContent || '').trim();
                            if (txt.length > 5) return txt;
                            prev = prev.previousElementSibling;
                        }
                        const parent = el.closest('div');
                        if (parent) {
                            const label = parent.querySelector('label, p, div.font-medium, div.text-sm');
                            if (label) return (label.innerText || label.textContent || '').trim();
                        }
                        return 'Tell us about what you have built that you are proud of';
                    }""",
                    extra_ta,
                )
                logger.info(f"❓ Answering custom employer question: '{question_label[:60]}...'")
                ans = self.generate_custom_question_answer(
                    question_text=question_label,
                    company=company,
                    job_title=job_title,
                    job_description=job_description,
                )
                await self._human_type(extra_ta, ans)
                await asyncio.sleep(0.8)

        # 3. Location Preferences Checkbox ("open to relocating")
        try:
            reloc_box = await self._page.query_selector(
                "input[type='checkbox']:has-text('relocat'), input[type='checkbox']"
            )
            if reloc_box:
                is_checked = await reloc_box.is_checked()
                if not is_checked:
                    logger.info("☑️ Checking 'open to relocating' preference checkbox...")
                    await self._human_click(reloc_box, hover_pause=(0.15, 0.35))
                    await asyncio.sleep(0.5)
        except Exception:
            pass

        # 4. Final Submission or Dry Run
        send_btn = await self._page.query_selector(
            "button:has-text('Send'), button.bg-brand-orange, button[type='submit']:has-text('Send')"
        )
        if not send_btn or not await send_btn.is_visible():
            send_btn = await self._page.query_selector("button:has-text('Submit'), button:has-text('Send message')")

        if self.dry_run:
            logger.info("🧪 [DRY RUN] Prepared YC application message & questions successfully. Closing modal...")
            close_btn = await self._page.query_selector("button:has-text('Close'), button[aria-label='Close'], svg.close")
            if close_btn:
                await self._human_click(close_btn)
            else:
                await self._page.keyboard.press("Escape")
            await asyncio.sleep(1.0)
            return "DRY_RUN_COMPLETED"

        if send_btn and await send_btn.is_visible():
            logger.info("🚀 [LIVE] Clicking 'Send' to submit YC application...")
            await self._human_click(send_btn, hover_pause=(0.3, 0.6), click_delay=(80, 130), post_pause=(2.5, 4.0))
            await asyncio.sleep(3.0)
            return "APPLIED"

        return "INCOMPLETE"

    async def close(self):
        """Safely disconnect or close browser resources."""
        try:
            if self._context:
                for p in list(self._context.pages):
                    if p != self._page and not p.is_closed():
                        try:
                            await p.close()
                        except Exception:
                            pass
            if self._page and not self._page.is_closed():
                try:
                    await self._page.close()
                except Exception:
                    pass
            if self._browser and self._is_cdp:
                try:
                    await self._browser.close()
                except Exception:
                    pass
            elif self._context and self._owns_context:
                try:
                    await self._context.close()
                except Exception:
                    pass
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
        except Exception:
            pass


RESUME_MATCHING_ROLES = [
    "Full Stack Developer",
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


async def run_ycombinator_auto_apply(
    keyword: str = None,
    keywords: list[str] = None,
    location: str = "Anywhere",
    target_applied: int = 40,
    max_jobs: int = 30,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run autonomous Y Combinator / Work at a Startup auto-apply across all matching resume roles.
    Applies target_applied count per portal (40-50 apps) and advances to the next browser agent.
    """
    agent = YCombinatorBrowserAgent(dry_run=dry_run)
    all_results = []
    total_applied = 0
    applied_per_role: dict[str, int] = {}

    search_roles = keywords or (
        [keyword] + [r for r in RESUME_MATCHING_ROLES if r != keyword]
        if keyword
        else RESUME_MATCHING_ROLES
    )

    try:
        await agent.connect()

        for role_idx, role_name in enumerate(search_roles, start=1):
            if total_applied >= target_applied:
                logger.info(f"🎯 Total portal target of {target_applied} applications reached on Y Combinator (applied: {total_applied})! Moving to next browser agent...")
                break

            logger.info("\n" + "#" * 65)
            logger.info(f"🎯 [YC ROLE {role_idx}/{len(search_roles)}] Searching Work at a Startup for: '{role_name}' [Target: {target_applied} applied]")
            logger.info("#" * 65)

            await agent.search_and_sort_newest(keyword=role_name)

            role_results, count = await agent.extract_and_apply_jobs(
                target_applied=target_applied - total_applied,
                max_inspect_per_page=max_jobs,
                current_keyword=role_name,
            )
            applied_per_role[role_name] = count
            total_applied += count
            all_results.extend(role_results)
            logger.info(f"📊 [YC ROLE {role_idx}/{len(search_roles)}] Completed '{role_name}' -> {count} applied. (Total session: {total_applied}/{target_applied})")

            if total_applied >= target_applied:
                logger.info(f"🎯 Target of {target_applied} applications reached on Y Combinator! Advancing to next portal...")
                break

            if role_idx < len(search_roles):
                logger.info("⏳ Pacing 4s before advancing to next YC role...")
                await asyncio.sleep(4.0)

    except Exception as e:
        logger.error(f"Error during Y Combinator auto-apply run: {e}", exc_info=True)
    finally:
        await agent.close()
        logger.info(f"🏁 Y Combinator sweep complete (Total applied: {total_applied}). Cleaned up browser session.")

    return all_results
