"""
Cutshort Browser Auto-Apply Agent (cutshort.io).

Automates job discovery and application submissions on Cutshort:
  1. Navigates to Cutshort 'View jobs' (cutshort.io/profile/all-jobs).
  2. Applies left-sidebar filters:
     - Experience range: 0 - 2 years in total.
     - Hiring activity on job: In the last 1 Days.
  3. Leverages Cutshort Profile Matcher to review all matched roles.
  4. Expands job details via 'Read more' to extract the complete JD.
  5. Clicks 'Apply now' to open application modal:
     - Tailors a fresh 1-page ATS PDF resume in resumes/cutshort/ via ResumeService.
     - Uploads the tailored resume via 'Upload another resume'.
     - Generates a personalized, punchy 1st-person message addressed to the recruiter.
     - Types the message and submits via 'Send'.
  6. Tracks applied jobs in JobTracker and avoids duplicate applications.
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

CUTSHORT_PITCH_SYSTEM_PROMPT = """Act as an expert technical recruiter and career strategist. I am applying for a software engineering role on Cutshort and I need you to write a highly targeted, punchy, and confident application message to the recruiter.

Here is the situation:
- I am applying directly to a hiring manager / recruiter on Cutshort.
- I have 2 years of intense, high-impact, full-stack & backend software engineering experience.
- You need to highlight my modern tech stack, rapid execution velocity, ability to own features end-to-end, and immediate availability (0 days notice).

RULES FOR THE MESSAGE:
1. Keep it short and punchy (under 120 words). Recruiters skim.
2. Start with a warm greeting to the recruiter (e.g., "Hi [Recruiter Name]," or "Hi Team,").
3. Connect 2 specific requirements from their Job Description to my proven technical achievements.
4. Highlight my execution velocity, modern engineering practices, and immediate joiner status (0 days notice).
5. Write strictly in first-person ("I", "my"). NEVER use third-person pronouns ("he", "she", "Kamal", "the candidate").
6. Use the EXACT Company Name provided. NEVER write "X company", "x company", "[Company Name]", or any placeholder.
7. Output ONLY the raw message text without quotes or markdown fences.
"""


class CutshortExperienceAnalyzer:
    """Strict Experience analyzer for Cutshort job postings (0-2 years target)."""

    SENIOR_TITLE_PATTERNS = [
        r"\b(?:senior|sr\.?|lead|principal|staff|architect|manager|director|vp|head\s+of)\b",
        r"\b(?:tech\s*lead|team\s*lead|pod\s*lead|delivery\s*lead)\b",
        r"\b(?:specialist|engineer|developer|consultant)\s+(?:iii|iv|v|vi|3|4|5|6)\b",
        r"\b(?:[3-9]|\d{2})\s*\+\s*(?:years?|yrs?)\b",
    ]

    MID_EXPERIENCE_PATTERNS = [
        r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?|yr)\b",
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:to|-|–|—)\s*\d+\s*(?:years?|yrs?|yr)\b",
        r"\b(?:minimum|min|at\s+least)\s+(?:of\s+)?([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\b",
    ]

    FRESHER_PATTERNS = [
        r"\b0\s*(?:to|-|–|—)\s*[1-2]\s*(?:years?|yrs?)\b",
        r"\b0\s*\+\s*(?:years?|yrs?)\b",
        r"\b1\s*(?:to|-|–|—)\s*2\s*(?:years?|yrs?)\b",
        r"\b2\s*(?:years?|yrs?)\b",
        r"\b(?:freshers?|intern|internship|graduate|entry\s*level|junior|associate|trainee)\b",
    ]

    @classmethod
    def analyze_title(cls, job_title: str) -> dict:
        title_lower = (job_title or "").lower()
        for pat in cls.SENIOR_TITLE_PATTERNS:
            m = re.search(pat, title_lower)
            if m:
                return {
                    "eligible": False,
                    "reason": f"Title contains senior/lead keyword '{m.group(0)}'",
                    "exp_years": 0.0,
                }
        return {"eligible": True, "reason": "Title eligible (0-2 yrs)", "exp_years": 2.0}

    @classmethod
    def analyze(cls, job_title: str, job_description: str) -> dict:
        title_lower = (job_title or "").lower()
        desc_lower = (job_description or "").lower()

        title_res = cls.analyze_title(job_title)
        if not title_res["eligible"]:
            return title_res

        for pat in cls.MID_EXPERIENCE_PATTERNS:
            m = re.search(pat, desc_lower)
            if m:
                matched_text = m.group(0)
                if not any(re.search(f_pat, matched_text) for f_pat in cls.FRESHER_PATTERNS):
                    return {
                        "eligible": False,
                        "reason": f"Job description requires '{matched_text}'",
                        "exp_years": 0.0,
                    }

        return {"eligible": True, "reason": "Eligible for 0-2 yrs profile", "exp_years": 2.0}


def extract_jd_required_skills(job_description: str, job_title: str) -> list[str]:
    """Extract key technical skills and requirements directly from expanded Job Description."""
    text = (job_title + "\n" + job_description).strip()
    if not text:
        return ["Java", "Spring Boot", "REST APIs", "React"]

    # Priority tech dictionary mapping keywords to display format
    tech_patterns = [
        (r"\b(?:react\s*native|expo)\b", "React Native / Expo"),
        (r"\btypescript\b", "TypeScript"),
        (r"\bsupabase\b", "Supabase"),
        (r"\b(?:llm\s*apis?|anthropic|claude|openai|gpt|embeddings?|pgvector)\b", "LLM APIs & AI Workflows"),
        (r"\b(?:ruby\s*on\s*rails|ror|rails)\b", "Ruby on Rails"),
        (r"\b(?:spring\s*boot|spring\s*framework)\b", "Spring Boot"),
        (r"\bjava\b", "Java"),
        (r"\bmicroservices\b", "Microservices Architecture"),
        (r"\brest\s*apis?\b", "REST APIs"),
        (r"\bangular\b", "Angular"),
        (r"\breact(?:\.js)?\b", "React.js"),
        (r"\bnext(?:\.js)?\b", "Next.js"),
        (r"\bvue(?:\.js)?\b", "Vue.js"),
        (r"\bnode(?:\.js)?\b", "Node.js"),
        (r"\bpython\b", "Python"),
        (r"\b(?:fastapi|django|flask)\b", "FastAPI / Django"),
        (r"\bpostgresql\b", "PostgreSQL"),
        (r"\bmysql\b", "MySQL"),
        (r"\bmongodb\b", "MongoDB"),
        (r"\bredis\b", "Redis"),
        (r"\bkafka\b", "Apache Kafka"),
        (r"\bdocker\b", "Docker"),
        (r"\baws\b", "AWS"),
        (r"\bgcp\b", "Google Cloud"),
        (r"\bi18n\b", "i18n Localization"),
        (r"\bgraphql\b", "GraphQL"),
        (r"\btailwind\b", "Tailwind CSS"),
    ]

    matched_skills = []
    seen = set()

    # 1. Check sections labeled 'Required skills', 'Key skills', 'Requirements', 'Tech stack'
    req_match = re.search(
        r"(?:required\s*skills|key\s*skills|requirements|what\s+you(?:'ll|\s+will)\s+need|tech(?:nical)?\s+stack|must\s+have)[\s\S]*?(?=(?:nice\s+to\s+have|benefits|about\s+us|perks|company|location|$))",
        text,
        re.IGNORECASE,
    )
    search_corpus = req_match.group(0) if req_match else text

    for pattern, display_name in tech_patterns:
        if re.search(pattern, search_corpus, re.IGNORECASE) and display_name not in seen:
            matched_skills.append(display_name)
            seen.add(display_name)

    # If few skills matched in requirement section, scan full corpus
    if len(matched_skills) < 3:
        for pattern, display_name in tech_patterns:
            if re.search(pattern, text, re.IGNORECASE) and display_name not in seen:
                matched_skills.append(display_name)
                seen.add(display_name)

    return matched_skills or ["Java", "Spring Boot", "REST APIs", "React"]


def handle_windows_file_dialog(file_path: str, max_wait_sec: float = 6.0) -> bool:
    """Handle or fill native Windows 'Open' file dialog if Google Chrome opens one."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            hwnd = user32.FindWindowW(None, "Open")
            if not hwnd:
                hwnd = user32.FindWindowW("#32770", "Open")
            if not hwnd:
                hwnd = user32.FindWindowW("#32770", None)

            if hwnd and user32.IsWindowVisible(hwnd):
                time.sleep(0.2)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.2)

                # Locate the file name Edit control inside ComboBoxEx32 / ComboBox / Edit
                edit_hwnd = 0
                comboboxex = user32.FindWindowExW(hwnd, 0, "ComboBoxEx32", None)
                if comboboxex:
                    combobox = user32.FindWindowExW(comboboxex, 0, "ComboBox", None)
                    if combobox:
                        edit_hwnd = user32.FindWindowExW(combobox, 0, "Edit", None)
                    if not edit_hwnd:
                        edit_hwnd = user32.FindWindowExW(comboboxex, 0, "Edit", None)
                if not edit_hwnd:
                    edit_hwnd = user32.FindWindowExW(hwnd, 0, "Edit", None)

                if edit_hwnd:
                    user32.SendMessageW(edit_hwnd, 0x000C, 0, file_path)  # WM_SETTEXT
                    time.sleep(0.3)
                    btn_open = user32.GetDlgItem(hwnd, 1)  # IDOK / Open button
                    if btn_open:
                        user32.SendMessageW(btn_open, 0x00F5, 0, 0)  # BM_CLICK
                        time.sleep(0.2)
                    user32.PostMessageW(hwnd, 0x0100, 0x0D, 0)  # VK_RETURN
                    logger.info(f"🪟 Handled native Windows file dialog with: {os.path.basename(file_path)}")
                    return True
                else:
                    user32.PostMessageW(hwnd, 0x0100, 0x0D, 0)
                    return True
            time.sleep(0.2)
    except Exception as e:
        logger.debug(f"Windows dialog automation note: {e}")
    return False


class CutshortBrowserAgent:
    """Automates job discovery and applications on Cutshort (cutshort.io)."""

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: str = None,
        chrome_path: str = None,
        dry_run: bool = False,
    ):
        self.cdp_port = cdp_port
        self.user_data_dir = user_data_dir or os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile")
        self.chrome_path = chrome_path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        self.dry_run = dry_run

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._owns_context = True
        self._is_cdp = False

        self._last_mouse_x = 400.0
        self._last_mouse_y = 400.0

        self.resume_service = ResumeService()
        self.email_service = EmailService()
        self.gemini_client = get_gemini_client()

        self.resumes_dir = Path("resumes/cutshort")
        self.resumes_dir.mkdir(parents=True, exist_ok=True)

    def is_cdp_port_open(self) -> bool:
        try:
            r = httpx.get(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    def _launch_native_chrome(self):
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
        """Connect to live Google Chrome via CDP (Port 9222) or persistent browser context."""
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
        cdp_max_retries = 3
        for cdp_attempt in range(1, cdp_max_retries + 1):
            try:
                if self.is_cdp_port_open():
                    logger.info(f"🔌 Connecting to real Google Chrome on port {self.cdp_port} (attempt {cdp_attempt}/{cdp_max_retries})...")
                    self._browser = await self._playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{self.cdp_port}",
                        timeout=20000,
                    )
                    contexts = self._browser.contexts
                    self._context = contexts[0] if contexts else await self._browser.new_context()
                    pages = self._context.pages
                    self._page = pages[0] if pages else await self._context.new_page()
                    self._is_cdp = True
                    connected_via_cdp = True
                    logger.info("✅ Connected to live Chrome instance via CDP!")
                    break
                else:
                    logger.info(f"  CDP port not open yet (attempt {cdp_attempt}), waiting...")
            except Exception as e:
                logger.warning(f"  CDP attempt {cdp_attempt}/{cdp_max_retries} note: {type(e).__name__}. {'Retrying in 5s...' if cdp_attempt < cdp_max_retries else 'Falling back to persistent launch.'}")
                if cdp_attempt < cdp_max_retries:
                    # Wait for the previous agent's Playwright WebSocket to fully release
                    await asyncio.sleep(5.0)

        if not connected_via_cdp:
            logger.info("🚀 Launching persistent Google Chrome for Cutshort Agent...")
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

        # Clean any stuck about:blank tabs and attach context monitor
        self._page, _ = await clean_and_recover_blank_tabs(
            self._context,
            self._page,
            fallback_url="https://cutshort.io/profile/all-jobs",
            allowed_domains=["cutshort.io"],
        )
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url="https://cutshort.io/profile/all-jobs",
            allowed_domains=["cutshort.io"],
        )

        logger.info("🔍 Checking Cutshort session status...")
        await self._page.goto("https://cutshort.io/profile/all-jobs", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._check_and_wait_for_signin()

    async def _check_and_wait_for_signin(self):
        """Check if Cutshort requires login and pause until user signs in."""
        for attempt in range(300):
            try:
                current_url = self._page.url.lower()

                # Active logged-in indicators on Cutshort
                is_logged_in = await self._page.query_selector(
                    "a:has-text('View jobs'), a:has-text('Dashboard'), a:has-text('Messages'), div:has-text('Profile matcher is ON'), a[href*='/profile/all-jobs'], button[aria-label*='user'], div[class*='user-avatar']"
                )
                if is_logged_in:
                    if attempt > 0:
                        logger.info("✅ Cutshort sign-in detected! Resuming agent...")
                    else:
                        logger.info("✅ Logged in to Cutshort successfully!")
                    return

                # If not logged in yet
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info("🔐  CUTSHORT SIGN-IN REQUIRED!")
                    logger.info("👉  Please log in to your Cutshort account in the opened Chrome window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email="kamalkumar.doddi@gmail.com",
                                subject="🔐 [ACTION REQUIRED] Please Sign In to Cutshort",
                                body="Hello Kamal,\n\nThe Cutshort Auto-Apply Agent requires you to log in.\n\n👉 Please switch to the open Chrome browser window on your computer and sign in to Cutshort.\n\nThe agent will automatically detect that you have signed in and start applying immediately.\n\nBest,\nAI Job Agent"
                            )
                            logger.info("📧 Sent sign-in notification email to kamalkumar.doddi@gmail.com")
                        except Exception as e:
                            logger.warning(f"Could not send sign-in email: {e}")

                await asyncio.sleep(3.0)
            except Exception:
                await asyncio.sleep(2.0)

    # -------------------------------------------------------------------------
    # HUMAN-LIKE INTERACTION HELPERS
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
    # AI CONTENT GENERATOR FOR CUTSHORT RECRUITER MESSAGE
    # -------------------------------------------------------------------------
    def _clean_recruiter_name(self, raw_name: str) -> str:
        """Sanitize raw recruiter text to a single clean first name."""
        if not raw_name:
            return ""
        lines = [line.strip() for line in raw_name.strip().splitlines() if line.strip()]
        for line in lines:
            line_clean = re.sub(r"^(?:posted\s+by|via|to|by)\s*", "", line, flags=re.IGNORECASE).strip()
            if not line_clean:
                continue
            if len(line_clean) > 35 or any(bad in line_clean.lower() for bad in [
                "developer", "engineer", "company", "apply", "fast-growing", "agency", "recruiters", "answers", "save for later", "hiring", "candid answer"
            ]):
                continue
            parts = line_clean.split()
            if parts:
                return parts[0].capitalize()
        return ""

    def generate_cutshort_pitch(
        self,
        company: str,
        job_title: str,
        job_description: str,
        recruiter_name: str = "",
    ) -> str:
        """Generate a personalized, high-converting recruiter note for Cutshort in strictly first-person."""
        clean_company = company.replace("•", "").strip() if company else "your team"
        greeting_name = self._clean_recruiter_name(recruiter_name)
        extracted_skills = extract_jd_required_skills(job_description, job_title)

        user_prompt = f"""Recruiter Name: {greeting_name or 'Hiring Team'}
Company Name: {clean_company}
Target Role: {job_title}
KEY REQUIRED SKILLS FROM JD: {', '.join(extracted_skills[:6])}

MY RESUME & CORE PROFILE:
- 2 years of intense software engineering experience shipping full-stack systems, backend services, and scalable web/AI applications.
- Strong hands-on proficiency in: {', '.join(extracted_skills[:4])}, plus robust testing and clean architecture.
- Built high-throughput services, optimized performance, and shipped production features with high execution velocity.
- Availability: Immediate joiner (0 days notice).

JOB DESCRIPTION:
{job_description[:3000]}

Generate the targeted application message for {clean_company} to {greeting_name or 'the recruiter'} now:"""

        if self.gemini_client:
            try:
                resp = self.gemini_client.generate_content(
                    prompt=user_prompt,
                    system_instruction=CUTSHORT_PITCH_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=1024,
                )
                if resp and len(resp.strip()) >= 50:
                    clean = resp.strip().replace("```", "").strip()
                    clean = re.sub(r"\[(?:Insert\s+)?Company(?:\s+Name)?\]", clean_company, clean, flags=re.IGNORECASE)
                    clean = re.sub(r"\b[Xx]\s+company\b", clean_company, clean, flags=re.IGNORECASE)
                    logger.info(f"🤖 [AI Cutshort Pitch] Generated note for {clean_company} ({len(clean)} chars)")
                    return clean
            except Exception as e:
                logger.warning(f"AI message generation note: {e}")

        # High quality dynamic first-person fallback matching exact JD skills
        salutation = f"Hi {greeting_name}," if greeting_name else "Hi Team,"
        top_skills_str = ", ".join(extracted_skills[:3]) if extracted_skills else "Java, Spring Boot microservices, REST APIs, and React"
        if len(extracted_skills) >= 4:
            top_skills_str = f"{', '.join(extracted_skills[:3])}, and {extracted_skills[3]}"

        return (
            f"{salutation}\n\n"
            f"I am excited to apply for the {job_title} role at {clean_company}. "
            f"With 2 years of intense software engineering experience specializing in {top_skills_str}, "
            f"I build high-uptime distributed systems and ship features end-to-end with high velocity. "
            f"As an immediate joiner (0 days notice), I would love to connect and discuss how I can contribute to {clean_company}."
        )




    # -------------------------------------------------------------------------
    # RESUME UPLOAD HANDLER IN APPLICATION MODAL
    # -------------------------------------------------------------------------
    async def _upload_resume_in_modal(self, tailored_pdf_path: str) -> bool:
        """Upload tailored resume PDF in Cutshort application modal dialog or verify pre-attached resume."""
        abs_path = os.path.abspath(tailored_pdf_path)
        if not os.path.exists(abs_path):
            logger.error(f"Tailored PDF path does not exist: {abs_path}")
            return False

        clean_upload_path = os.path.join(os.path.dirname(abs_path), "Kamal_Kumar_Resume.pdf")
        try:
            import shutil
            shutil.copy2(abs_path, clean_upload_path)
            target_path = clean_upload_path
        except Exception:
            target_path = abs_path

        uploaded = False

        # 1. Check if candidate resume is already pre-attached in modal (e.g. Kamal_Kumar_Resume_rS0q pdf)
        pre_attached_resume = await self._page.evaluate(r"""
            () => {
                const modal = document.querySelector("div[role='dialog'], div.modal, div[class*='modal'], [aria-modal='true']");
                if (!modal) return null;
                const text = (modal.innerText || modal.textContent || '');
                // Cutshort displays pre-attached resume as: "Kamal_Kumar_Resume_xxxx\npdf\nUpload another resume"
                const match = text.match(/([A-Za-z0-9_\-\.]+(?:\.pdf|\s*\n?\s*pdf))/i) ||
                              text.match(/(Kamal_Kumar_Resume[A-Za-z0-9_\-]*)/i);
                if (match) {
                    return match[1].replace(/\s*\n?\s*/g, '.');
                }
                if (text.toLowerCase().includes('upload another resume') && text.toLowerCase().includes('kamal')) {
                    return 'Kamal_Kumar_Resume.pdf';
                }
                return null;
            }
        """)

        if pre_attached_resume:
            logger.info(f"📄 Verified resume already attached in Cutshort modal: '{pre_attached_resume}'")
            # If a verified profile resume is already pre-attached, Cutshort requires no risky Turnstile upload
            return True

        # 2. If not pre-attached, attempt upload via 'Upload another resume' link
        logger.info(f"📤 Uploading tailored resume ({os.path.basename(target_path)}) via 'Upload another resume'...")
        dialog_task = asyncio.create_task(asyncio.to_thread(handle_windows_file_dialog, target_path, 6.0))

        try:
            modal = self._page.locator("div[role='dialog'], div.modal, [aria-modal='true']").first
            upload_trigger = modal.locator("div:has-text('Upload another resume'), span:has-text('Upload another resume'), button:has-text('Upload'), :text('Upload another resume')").last
            if await upload_trigger.count() > 0:
                logger.info("👆 Triggering file chooser in modal...")
                try:
                    async with self._page.expect_file_chooser(timeout=4000) as fc_info:
                        await upload_trigger.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(target_path)
                    logger.info(f"✅ Tailored resume set via Playwright file chooser: {os.path.basename(target_path)}")
                    uploaded = True
                except Exception as fc_err:
                    logger.debug(f"expect_file_chooser note: {fc_err}")
        except Exception as trig_err:
            logger.debug(f"Upload trigger note: {trig_err}")

        # Check native dialog handler result
        try:
            native_result = await dialog_task
            if native_result:
                uploaded = True
        except Exception:
            pass

        # 3. Direct file input fallback
        if not uploaded:
            try:
                modal_el = await self._page.query_selector("div[role='dialog'], div.modal, div[class*='modal']")
                root = modal_el or self._page
                file_inputs = await root.query_selector_all("input[type='file']")
                for fi in file_inputs:
                    try:
                        await fi.set_input_files(target_path)
                        logger.info(f"✅ Attached tailored resume directly to file input: {os.path.basename(target_path)}")
                        uploaded = True
                        break
                    except Exception:
                        pass
            except Exception:
                pass

        # 4. Wait up to 15s for upload settlement
        logger.info("⏳ Waiting for resume upload confirmation (up to 15s)...")
        filename_base = os.path.splitext(os.path.basename(target_path))[0]
        for sec in range(1, 16):
            await asyncio.sleep(1.0)
            status = await self._page.evaluate("""
                (fname) => {
                    const modal = document.querySelector("div[role='dialog'], div.modal, div[class*='modal'], div[class*='dialog']");
                    if (!modal) return { done: false, isUploading: false };
                    const text = (modal.innerText || modal.textContent || '').toLowerCase();
                    const isUploading = text.includes('uploading') || text.includes('processing') || text.includes('please wait');
                    const hasFile = text.includes(fname.toLowerCase()) || text.includes('.pdf') || text.includes('kamal');
                    return { done: !isUploading && hasFile, isUploading: isUploading };
                }
            """, filename_base)
            if status.get("done") and not status.get("isUploading"):
                logger.info(f"✅ Resume upload confirmed after {sec}s: {os.path.basename(target_path)}")
                return True

        return uploaded or bool(pre_attached_resume)

    # -------------------------------------------------------------------------
    # FILTER CONFIGURATION (PROFILE MATCHER, 0-2 YRS & 1-DAY HIRING ACTIVITY)
    # -------------------------------------------------------------------------
    async def _enable_profile_matcher(self):
        """Ensure 'Profile matcher is ON' is enabled on the 'View jobs' page."""
        logger.info("  💜 Checking Profile matcher status...")
        try:
            status = await self._page.evaluate("""
                () => {
                    const heading = Array.from(document.querySelectorAll('*')).find(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === 'Profile matcher is ON' || t === 'Profile matcher is OFF';
                    });
                    const inp = document.querySelector("input[role='switch']");
                    return {
                        text: heading ? (heading.innerText || heading.textContent || '').trim() : '',
                        isOff: (heading ? heading.innerText.includes('OFF') : false) || (inp ? inp.getAttribute('aria-checked') === 'false' : false)
                    };
                }
            """)

            if status.get("isOff") or status.get("text") == "Profile matcher is OFF":
                logger.info("  💜 Profile matcher is OFF -> Toggling ON via switch...")
                switch_loc = self._page.locator("label:has(input[role='switch']), input[role='switch'], .handle").first
                if await switch_loc.count() > 0:
                    await switch_loc.click()
                    await asyncio.sleep(2.0)
                else:
                    await self._page.evaluate("""
                        () => {
                            const lbl = document.querySelector("label:has(input[role='switch']), label.sc-cb95968a-0");
                            if (lbl) lbl.click();
                            else {
                                const inp = document.querySelector("input[role='switch']");
                                if (inp) inp.click();
                            }
                        }
                    """)
                    await asyncio.sleep(2.0)

                # Verify toggle result
                new_text = await self._page.evaluate("""
                    () => {
                        const heading = Array.from(document.querySelectorAll('*')).find(el => {
                            const t = (el.innerText || el.textContent || '').trim();
                            return t === 'Profile matcher is ON' || t === 'Profile matcher is OFF';
                        });
                        return heading ? (heading.innerText || heading.textContent || '').trim() : '';
                    }
                """)
                if "ON" in new_text:
                    logger.info("  ✅ Profile matcher successfully turned ON!")
                else:
                    logger.info("  ✅ Profile matcher toggle clicked!")
            else:
                logger.info("  ✅ Profile matcher is already ON!")
        except Exception as pm_err:
            logger.debug(f"Profile matcher check note: {pm_err}")

    async def _configure_experience_range(self):
        """Configure left sidebar Experience range filter to strictly 0 - 2 years in total."""
        logger.info("  🎯 Setting Experience range filter to 0-2 years...")
        try:
            # 1. Click 'Experience range' in left sidebar
            await self._page.evaluate("""
                () => {
                    const allEls = Array.from(document.querySelectorAll("div, button, span, a, p"));
                    const expItem = allEls.find(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === 'Experience range' || t.startsWith('Experience range');
                    });
                    if (expItem) {
                        const row = expItem.closest("div.cursor-pointer, button, div[role='button'], div.flex") || expItem;
                        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        row.click();
                        return true;
                    }
                    return false;
                }
            """)
            await asyncio.sleep(1.2)

            # 2. Check if already strictly 0 - 2 years
            already_set = await self._page.evaluate("""
                () => {
                    const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                    const popover = popovers.find(p => (p.innerText || '').includes('years in total') || (p.innerText || '').includes('Clear this filter'));
                    if (!popover) return false;
                    const text = (popover.innerText || '');
                    return /\\b0\\s*(?:-|to)\\s*2\\s+years\\b/i.test(text);
                }
            """)

            if already_set:
                logger.info("  ✅ Experience range is already set to 0 - 2 years!")
            else:
                logger.info("  🔄 Dragging experience slider to 0 - 2 years...")
                # Focus max handle
                await self._page.evaluate("""
                    () => {
                        const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                        const popover = popovers.find(p => (p.innerText || '').includes('years in total') || (p.innerText || '').includes('Clear this filter'));
                        if (!popover) return;
                        const handles = Array.from(popover.querySelectorAll(".rc-slider-handle, [role='slider'], div[class*='handle'], div[class*='thumb'], div.rounded-full"));
                        if (handles.length >= 2) {
                            handles[1].focus();
                        } else if (handles.length === 1) {
                            handles[0].focus();
                        }
                    }
                """)
                await asyncio.sleep(0.3)

                # Reset to 0 with Home key, then step to 2 with ArrowRight
                await self._page.keyboard.press("Home")
                await asyncio.sleep(0.2)
                await self._page.keyboard.press("ArrowRight")
                await asyncio.sleep(0.1)
                await self._page.keyboard.press("ArrowRight")
                await asyncio.sleep(0.3)

                # Check if it reached 0 - 2 years
                check_text = await self._page.evaluate("""
                    () => {
                        const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                        const popover = popovers.find(p => (p.innerText || '').includes('years in total'));
                        return popover ? (popover.innerText || '') : '';
                    }
                """)

                # If Home/Arrow keys did not set it, dispatch click at 10% on track and fine tune
                if not re.search(r"\b0\s*(?:-|to)\s*2\s+years\b", check_text, re.IGNORECASE):
                    await self._page.evaluate("""
                        () => {
                            const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                            const popover = popovers.find(p => (p.innerText || '').includes('years in total') || (p.innerText || '').includes('Clear this filter'));
                            if (!popover) return;
                            const track = popover.querySelector(".rc-slider-rail, .rc-slider-track, div[class*='rail'], div[class*='track'], div.h-1, div.h-2, div.bg-gray-200, div.bg-gray-300");
                            if (track) {
                                const rect = track.getBoundingClientRect();
                                const clickX = rect.left + rect.width * 0.10;
                                const clickY = rect.top + rect.height / 2;
                                const clickEvt = new MouseEvent('click', {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window,
                                    clientX: clickX,
                                    clientY: clickY
                                });
                                track.dispatchEvent(clickEvt);
                            }
                        }
                    """)
                    await asyncio.sleep(0.5)

                    for _ in range(25):
                        t = await self._page.evaluate("""
                            () => {
                                const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                                const popover = popovers.find(p => (p.innerText || '').includes('years in total'));
                                return popover ? (popover.innerText || '') : '';
                            }
                        """)
                        if re.search(r"\b0\s*(?:-|to)\s*2\s+years\b", t, re.IGNORECASE):
                            logger.info(f"  ✅ Experience range set to 0 - 2 years ({t.splitlines()[-1] if t else ''})")
                            break
                        await self._page.keyboard.press("ArrowLeft")
                        await asyncio.sleep(0.08)

            # Close popover
            await self._page.keyboard.press("Escape")
            await asyncio.sleep(1.0)
            logger.info("  ✅ Experience range filter applied (0-2 years)!")
        except Exception as exp_err:
            logger.warning(f"Experience filter setting note: {exp_err}")
            await self._page.keyboard.press("Escape")

    async def _configure_hiring_activity(self):
        """Configure left sidebar Hiring activity filter to 'In the last 1 Days'."""
        logger.info("  ⚡ Setting Hiring activity filter to 'In the last 1 Days'...")
        try:
            # 1. Click 'Hiring activity on job' in left sidebar
            await self._page.evaluate("""
                () => {
                    const allEls = Array.from(document.querySelectorAll("div, button, span, a, p"));
                    const hiringItem = allEls.find(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === 'Hiring activity on job' || t.startsWith('Hiring activity');
                    });
                    if (hiringItem) {
                        const row = hiringItem.closest("div.cursor-pointer, button, div[role='button'], div.flex") || hiringItem;
                        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        row.click();
                        return true;
                    }
                    return false;
                }
            """)
            await asyncio.sleep(1.2)

            # 2. Select 'In the last' radio option
            await self._page.evaluate("""
                () => {
                    const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                    const popover = popovers.find(p => (p.innerText || '').includes('Clear this filter') && (p.innerText || '').includes('In the last'));
                    if (popover) {
                        const allEls = Array.from(popover.querySelectorAll("label, span, div, p"));
                        const inTheLastEl = allEls.find(el => (el.innerText || el.textContent || '').trim().includes('In the last'));
                        if (inTheLastEl) {
                            const container = inTheLastEl.closest("label, div.flex, div.cursor-pointer") || inTheLastEl;
                            container.click();
                            const radio = container.querySelector("input[type='radio']") || inTheLastEl.parentElement?.querySelector("input[type='radio']");
                            if (radio) radio.click();
                        }
                    }
                }
            """)
            await asyncio.sleep(0.5)

            # 3. Enter '1' in numeric input
            await self._page.evaluate("""
                () => {
                    const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                    const popover = popovers.find(p => (p.innerText || '').includes('Clear this filter') && (p.innerText || '').includes('In the last'));
                    if (popover) {
                        const input = popover.querySelector("input[type='number'], input[type='text'], input.border");
                        if (input) {
                            input.focus();
                            input.value = '1';
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                }
            """)
            await asyncio.sleep(0.5)

            # 4. Click dropdown next to input (which currently shows 'Months', 'Weeks', etc.)
            await self._page.evaluate("""
                () => {
                    const popovers = Array.from(document.querySelectorAll("div[role='dialog'], div[class*='popover'], div[class*='popup'], div.shadow-lg, div.shadow-md, div.rounded-lg, div.border"));
                    const popover = popovers.find(p => (p.innerText || '').includes('Clear this filter') && (p.innerText || '').includes('In the last'));
                    if (popover) {
                        const dropdownBtn = popover.querySelector("button, div.cursor-pointer.border, div.cursor-pointer.rounded, div[role='combobox'], div[class*='select']");
                        if (dropdownBtn) {
                            dropdownBtn.click();
                            return true;
                        }
                        const unitEl = Array.from(popover.querySelectorAll("div, span, button")).find(el => {
                            const t = (el.innerText || '').trim();
                            return t === 'Months' || t === 'Days' || t === 'Weeks' || t === 'Years';
                        });
                        if (unitEl) {
                            unitEl.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            await asyncio.sleep(0.8)

            # 5. Select 'Days' from the dropdown menu
            selected_days = await self._page.evaluate("""
                () => {
                    const allMenuItems = Array.from(document.querySelectorAll("li, div, button, span, option, a"));
                    const daysItem = allMenuItems.find(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === 'Days';
                    });
                    if (daysItem) {
                        daysItem.click();
                        return true;
                    }
                    return false;
                }
            """)
            if selected_days:
                logger.info("  ✅ Selected 'Days' unit from dropdown!")
            await asyncio.sleep(0.8)

            # 6. Close popover to apply filter
            await self._page.keyboard.press("Escape")
            await asyncio.sleep(1.5)
            logger.info("  ✅ Hiring activity filter set to 'In the last 1 Days'!")
        except Exception as hiring_err:
            logger.warning(f"Hiring activity filter setting note: {hiring_err}")
            await self._page.keyboard.press("Escape")

    async def configure_filters(self):
        """Configure left sidebar filters: Profile Matcher ON, Experience range (0-2 yrs), and Hiring activity (1 Days)."""
        logger.info("⚙️ Configuring Cutshort filters (Profile Matcher ON, 0-2 Yrs Experience, 1-Day Hiring Activity)...")

        # 1. Navigate to target URL with exact 0-2 yrs and 1-Day hiring activity params
        target_url = "https://cutshort.io/profile/all-jobs?minexp=0&maxexp=2&hiringActivityOnJob=1-days"
        current_url = self._page.url.lower()
        if "minexp=0" not in current_url or "maxexp=2" not in current_url or "1-days" not in current_url:
            await self._page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3.0)

        # 2. Turn ON Profile Matcher if OFF
        await self._enable_profile_matcher()
        await asyncio.sleep(2.0)

        logger.info("✅ All Cutshort filters configured successfully!")


    # -------------------------------------------------------------------------
    # EXTRACT & APPLY TO JOBS (CONTINUOUS SCROLL & TOP-DOWN APPLICATION)
    # -------------------------------------------------------------------------
    async def extract_and_apply_jobs(
        self,
        target_applied: int = 5,
        max_inspect_per_page: int = 50,
    ) -> tuple[list[dict], int]:
        """
        Continuously iterate through Cutshort jobs from top to bottom,
        expand JD via 'Read more', tailor resume, and submit application.
        """
        results = []
        applied_count = 0
        inspected_keys = set()
        consecutive_empty_scrolls = 0
        max_scroll_attempts = 3

        logger.info(f"🎯 Beginning Cutshort auto-apply run starting from top jobs (Target: {target_applied} applied)...")

        # Wait for job cards to load in DOM
        try:
            await self._page.wait_for_selector(
                "button:has-text('Apply now'), a:has-text('Apply now')",
                timeout=12000,
            )
            await asyncio.sleep(2.0)
        except Exception:
            pass

        while applied_count < target_applied and consecutive_empty_scrolls < max_scroll_attempts:
            # 1. Find total Apply now buttons currently visible on page with settlement retries
            total_cards = 0
            for _ in range(6):
                total_cards = await self._page.evaluate("""
                    () => {
                        const allButtons = Array.from(document.querySelectorAll("button, a"));
                        const applyButtons = allButtons.filter(b => {
                            const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                            return txt === 'apply now' || txt === 'apply';
                        });
                        return applyButtons.length;
                    }
                """)
                if total_cards > 0:
                    break
                await asyncio.sleep(1.5)

            if total_cards == 0:
                consecutive_empty_scrolls += 1
                logger.info(f"📜 No jobs visible in viewport. Scrolling down to load ({consecutive_empty_scrolls}/{max_scroll_attempts})...")
                await self._trigger_scroll_load()
                await asyncio.sleep(3.0)
                continue

            logger.info(f"📋 Checking {total_cards} job card(s) visible on Cutshort...")
            found_new_in_batch = False

            for card_idx in range(total_cards):
                if applied_count >= target_applied:
                    break

                # Guard against any stuck about:blank or secondary popup tabs
                fallback_cutshort_url = "https://cutshort.io/profile/all-jobs?minexp=0&maxexp=2&hiringActivityOnJob=1-days"
                self._page, _ = await clean_and_recover_blank_tabs(
                    self._context,
                    self._page,
                    fallback_url=fallback_cutshort_url,
                    allowed_domains=["cutshort.io"],
                )

                # 1. Scroll card into view & click 'Read more' to expand full JD
                try:
                    clicked_read_more = await self._page.evaluate("""
                        (cardIdx) => {
                            const allButtons = Array.from(document.querySelectorAll("button, a"));
                            const applyButtons = allButtons.filter(b => {
                                const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                                return txt === 'apply now' || txt === 'apply';
                            });
                            const btn = applyButtons[cardIdx];
                            if (btn) {
                                const card = btn.closest("div.border, div.rounded-lg, div.shadow, div.p-4, div[class*='card'], div[class*='Card']")
                                          || btn.parentElement?.parentElement?.parentElement?.parentElement
                                          || btn.parentElement?.parentElement;
                                if (card) {
                                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    const readMore = Array.from(card.querySelectorAll("button, a, span, p, div, b, strong")).find(b => {
                                        const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                                        return t === 'read more' || t.startsWith('read more');
                                    });
                                    if (readMore) {
                                        readMore.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        readMore.click();
                                        return true;
                                    }
                                }
                            }
                            return false;
                        }
                    """, card_idx)
                    if clicked_read_more:
                        await asyncio.sleep(1.2)
                except Exception:
                    pass

                # 2. Extract metadata and full expanded JD from card
                card_meta = await self._page.evaluate("""
                    (cardIdx) => {
                        const allButtons = Array.from(document.querySelectorAll("button, a"));
                        const applyButtons = allButtons.filter(b => {
                            const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                            return txt === 'apply now' || txt === 'apply';
                        });
                        const btn = applyButtons[cardIdx];
                        if (!btn) return null;

                        const card = btn.closest("div.border, div.rounded-lg, div.shadow, div.p-4, div[class*='card'], div[class*='Card']")
                                  || btn.parentElement?.parentElement?.parentElement?.parentElement
                                  || btn.parentElement?.parentElement?.parentElement;

                        if (!card) return null;

                        let title = "";
                        let company = "";
                        let recruiter = "";

                        const h = card.querySelector("h1, h2, h3, h4, a[href*='/job/'], div.font-semibold, div.font-bold");
                        if (h) title = (h.innerText || h.textContent || '').trim().split('\\n')[0].trim();

                        const fullText = (card.innerText || card.textContent || '').trim();

                        // Try extracting company from 'Company: <Name>' or 'at <Name>'
                        const compMatch = fullText.match(/Company:\\s*([^\\n\\r]+)/i) || fullText.match(/\\bat\\s+([A-Za-z0-9&.,\\-\\s]{2,40})/i);
                        if (compMatch) {
                            company = compMatch[1].trim().split('\\n')[0].trim();
                        } else {
                            let compEl = card.querySelector("a[href*='/company/'], a[href*='/companies/']");
                            if (compEl) {
                                company = (compEl.innerText || compEl.textContent || '').trim().split('\\n')[0].trim();
                            }
                        }

                        // Try extracting recruiter from 'Posted by <Name>'
                        const recMatch = fullText.match(/Posted by\\s+([^\\n\\r•]+)/i);
                        if (recMatch) {
                            recruiter = recMatch[1].replace(/via Cutshort.*/gi, '').trim().split('\\n')[0].trim();
                        }

                        if (!title) title = "Software Engineer";
                        if (!company) company = "Tech Company";

                        const key = (company + "_" + title).toLowerCase();
                        return {
                            cardIdx: cardIdx,
                            key: key,
                            title: title,
                            company: company,
                            recruiter: recruiter,
                            fullJd: fullText
                        };
                    }
                """, card_idx)

                if not card_meta:
                    continue

                card_key = card_meta["key"]
                if card_key in inspected_keys:
                    continue

                found_new_in_batch = True
                inspected_keys.add(card_key)

                title = card_meta.get("title") or "Software Engineer"
                company = card_meta.get("company") or "Startup"
                recruiter = card_meta.get("recruiter") or ""
                full_jd = card_meta.get("fullJd") or ""
                job_url = self._page.url
                extracted_skills = extract_jd_required_skills(full_jd, title)
                logger.info(f"📖 Read expanded JD for '{title}' ({len(full_jd)} chars). Required skills: {', '.join(extracted_skills[:5])}")

                # Apply to all available matched jobs directly
                try:
                    logger.info(f"\n[{applied_count + 1}/{target_applied}] 🔎 [Cutshort] Processing job {card_idx + 1}: '{title}' @ {company}...")

                    # 5. Click 'Apply now' button on this card
                    clicked_apply = await self._page.evaluate("""
                        (cardIdx) => {
                            const allButtons = Array.from(document.querySelectorAll("button, a"));
                            const applyButtons = allButtons.filter(b => {
                                const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                                return txt === 'apply now' || txt === 'apply';
                            });
                            const btn = applyButtons[cardIdx];
                            if (btn) {
                                btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                btn.click();
                                return true;
                            }
                            return false;
                        }
                    """, card_idx)

                    if not clicked_apply:
                        logger.warning(f"Could not click 'Apply now' for job {card_idx + 1} ('{title}' @ {company}) — skipping")
                        continue

                    # Wait for application popup modal to appear
                    await asyncio.sleep(2.0)

                    modal_visible = await self._page.query_selector("div[role='dialog'], div.modal, textarea[placeholder*='message' i], div:has-text('You are applying for')")
                    if not modal_visible:
                        logger.warning("Application modal did not open. Skipping card...")
                        continue

                    # 6. Extract authoritative Title, Company, and Recruiter directly from modal dialog
                    try:
                        modal_info = await self._page.evaluate("""
                            () => {
                                const modal = document.querySelector("div[role='dialog'], div.modal, div[class*='modal'], div[class*='dialog']");
                                if (!modal) return null;

                                let headerTitle = "";
                                let headerCompany = "";
                                let recruiterName = "";

                                const allEls = Array.from(modal.querySelectorAll("*"));
                                const appEl = allEls.find(el => (el.innerText || el.textContent || '').includes('You are applying for') && el.children.length <= 4);
                                
                                if (appEl) {
                                    const bolds = Array.from(appEl.querySelectorAll("b, strong, span.font-bold, span.font-semibold, div.font-bold, div.font-semibold"));
                                    if (bolds.length >= 2) {
                                        headerTitle = (bolds[0].innerText || bolds[0].textContent || '').trim();
                                        headerCompany = (bolds[1].innerText || bolds[1].textContent || '').trim();
                                    } else {
                                        const rawText = (appEl.innerText || appEl.textContent || '').replace(/\\s+/g, ' ').trim();
                                        const match = rawText.match(/You are applying for\\s+(.+?)\\s+at\\s+(.+)/i);
                                        if (match) {
                                            headerTitle = match[1].trim();
                                            let cRaw = match[2].trim();
                                            headerCompany = cRaw.split(/\\s+To\\s+|\\s+Upload\\s+|\\s+Follow\\s+/i)[0].trim();
                                        }
                                    }
                                }

                                // Check "Follow <Company> to get alerts" for clean company name
                                const followEl = allEls.find(el => (el.innerText || el.textContent || '').includes('Follow ') && (el.innerText || '').includes('to get alerts'));
                                if (followEl) {
                                    const fText = (followEl.innerText || followEl.textContent || '').replace(/\\s+/g, ' ').trim();
                                    const fMatch = fText.match(/Follow\\s+(.+?)\\s+to get alerts/i);
                                    if (fMatch && fMatch[1].trim().length < 40) {
                                        headerCompany = fMatch[1].trim();
                                    }
                                }

                                // Extract Recruiter from "To" section
                                const toLabel = allEls.find(el => {
                                    const t = (el.innerText || el.textContent || '').trim();
                                    return t === 'To' || t.startsWith('To\\n');
                                });
                                if (toLabel) {
                                    const container = toLabel.closest("div.flex, div") || toLabel.parentElement;
                                    if (container) {
                                        const lines = (container.innerText || container.textContent || '').split('\\n').map(l => l.trim()).filter(l => l && l !== 'To' && l.length > 1 && l.length < 40);
                                        if (lines.length > 0) {
                                            recruiterName = lines[0];
                                        }
                                    }
                                }

                                return {
                                    title: headerTitle,
                                    company: headerCompany,
                                    recruiter: recruiterName
                                };
                            }
                        """)
                        if modal_info:
                            if modal_info.get("title"):
                                title = modal_info["title"]
                            if modal_info.get("company"):
                                clean_c = re.split(r"\s+(?:To\b|Upload\b|Follow\b|Kamal_|\.pdf)", modal_info["company"], flags=re.IGNORECASE)[0].strip()
                                if clean_c:
                                    company = clean_c
                            if modal_info.get("recruiter"):
                                recruiter = modal_info["recruiter"]
                    except Exception as m_err:
                        logger.debug(f"Modal extraction note: {m_err}")

                    # 7. Tailor 1-page ATS PDF resume matching the full expanded JD and exact company
                    job_dict = {
                        "id": f"cutshort_{applied_count + 1}_{int(time.time())}",
                        "title": title,
                        "company": company,
                        "description": full_jd,
                        "portal": "cutshort",
                    }
                    logger.info(f"📄 Generating tailored 1-page ATS PDF resume in resumes/cutshort/ for {company}...")
                    tailored_pdf_path = self.resume_service.generate_tailored_resume(
                        job=job_dict,
                        candidate_profile={},
                        portal="cutshort",
                    )
                    logger.info(f"✅ Generated tailored resume: {tailored_pdf_path}")

                    # 8. Click 'Upload another resume' in modal and upload the tailored PDF
                    try:
                        await self._upload_resume_in_modal(tailored_pdf_path)
                    except Exception as upload_err:
                        logger.warning(f"Resume upload note: {upload_err}")

                    # Strict Gate: Guarantee upload is 100% finished before proceeding to message writing or sending
                    for _ in range(40):
                        is_busy = await self._page.evaluate("""
                            () => {
                                const modal = document.querySelector("div[role='dialog'], div.modal, div[class*='modal']");
                                if (!modal) return false;
                                const text = (modal.innerText || modal.textContent || '').toLowerCase();
                                return text.includes('uploading') || 
                                       text.includes('processing') || 
                                       text.includes('attaching') || 
                                       text.includes('please wait') ||
                                       !!modal.querySelector("div[class*='spin'], div[class*='progress'], svg[class*='animate-spin'], div[role='progressbar'], .spinner, .loading");
                            }
                        """)
                        if not is_busy:
                            break
                        logger.info("⏳ Modal is finalizing resume upload. Waiting before drafting/typing message...")
                        await asyncio.sleep(1.5)

                    # 9. Generate personalized recruiter note with clean recruiter name & full JD context
                    pitch_message = self.generate_cutshort_pitch(
                        company=company,
                        job_title=title,
                        job_description=full_jd,
                        recruiter_name=recruiter,
                    )

                    textarea = await self._page.query_selector("textarea, textarea[placeholder*='message' i], div[contenteditable='true']")
                    if textarea and await textarea.is_visible():
                        greeting_preview = self._clean_recruiter_name(recruiter) or company
                        logger.info(f"✍️ Typing personalized message to {greeting_preview} ({len(pitch_message)} chars)...")
                        await self._human_type(textarea, pitch_message)
                        await asyncio.sleep(1.0)

                    # 10. Submit application via 'Send'
                    send_btn = await self._page.query_selector("button:has-text('Send'), button[type='submit']:has-text('Send')")

                    if self.dry_run:
                        logger.info(f"🧪 [DRY RUN] Prepared Cutshort application for '{title}' @ {company}. Closing modal...")
                        await self._close_modal()
                        JobTracker.record_job("cutshort", company, title, job_url, status="DRY_RUN", job_url=job_url)
                        results.append({"title": title, "company": company, "status": "DRY_RUN"})
                        applied_count += 1
                        continue

                    if send_btn and await send_btn.is_visible():
                        logger.info(f"🚀 [LIVE] Submitting application for '{title}' @ {company}...")
                        await self._human_click(send_btn, hover_pause=(0.3, 0.5), post_pause=(2.0, 3.0))
                        await asyncio.sleep(2.5)

                        await self._close_modal()

                        JobTracker.record_job("cutshort", company, title, job_url, status="APPLIED", job_url=job_url)
                        try:
                            self.email_service.send_application_notification(
                                job_title=title,
                                company=company,
                                portal="Cutshort",
                                job_url=job_url,
                            )
                        except Exception:
                            pass

                        applied_count += 1
                        logger.info(f"🎉 Successfully applied to '{title}' @ {company}! Total applied: {applied_count}/{target_applied}")
                        results.append({"title": title, "company": company, "status": "APPLIED"})

                        await asyncio.sleep(3.0)

                except Exception as card_err:
                    logger.error(f"Error processing Cutshort job card {card_idx + 1}: {card_err}", exc_info=True)
                    await self._close_modal()

            # If all cards in current view processed and target not reached, scroll down to load more
            if applied_count < target_applied:
                if not found_new_in_batch:
                    consecutive_empty_scrolls += 1
                else:
                    consecutive_empty_scrolls = 0
                logger.info(f"📊 Progress: {applied_count}/{target_applied} applied. Scrolling down for more matching jobs...")
                await self._trigger_scroll_load()
                await asyncio.sleep(2.5)

        return results, applied_count

    async def _trigger_scroll_load(self):
        """Scroll bottom-most elements and containers to trigger Cutshort infinite lazy loading."""
        try:
            await self._page.evaluate("""
                () => {
                    const allButtons = Array.from(document.querySelectorAll("button, a")).filter(b => {
                        const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                        return t === 'apply now' || t === 'apply';
                    });
                    if (allButtons.length > 0) {
                        const lastBtn = allButtons[allButtons.length - 1];
                        const card = lastBtn.closest("div.border, div.rounded-lg, div.shadow, div.p-4") || lastBtn;
                        card.scrollIntoView({ behavior: 'smooth', block: 'end' });
                    }
                    window.scrollBy(0, 1000);
                    document.documentElement.scrollTop += 1000;
                    document.body.scrollTop += 1000;
                    Array.from(document.querySelectorAll("div")).filter(d => d.scrollHeight > d.clientHeight && d.clientHeight > 300).forEach(d => d.scrollTop += 1000);
                }
            """)
            await self._page.keyboard.press("PageDown")
            await asyncio.sleep(0.5)
            await self._page.keyboard.press("PageDown")
        except Exception:
            pass

    async def _close_modal(self):
        """Close open modal via close button or Escape key."""
        try:
            close_btn = await self._page.query_selector(
                "button[aria-label='Close'], button.close, svg[data-icon='xmark'], button:has-text('Cancel'), button:has-text('✕'), button:has-text('×')"
            )
            if close_btn and await close_btn.is_visible():
                await self._human_click(close_btn, hover_pause=(0.1, 0.2), post_pause=(0.3, 0.5))
            else:
                await self._page.keyboard.press("Escape")
        except Exception:
            await self._page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

    async def close(self):
        """Safely disconnect or close browser resources."""
        try:
            if self._context:
                for p in list(self._context.pages):
                    if p != self._page:
                        try:
                            await p.close()
                        except Exception:
                            pass
            if self._page:
                try:
                    await self._page.close()
                except Exception:
                    pass
            if self._context and self._owns_context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass


async def run_cutshort_auto_apply(
    target_applied: int = 40,
    max_jobs: int = 50,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run autonomous Cutshort auto-apply on 'View jobs' matching Kamal's profile.
    Applies target_applied count per portal (40-50 apps) and advances to the next browser agent.
    Configures 0-2 yrs & 1-day hiring activity filters, then iterates through all matched jobs.
    """
    agent = CutshortBrowserAgent(dry_run=dry_run)
    all_results = []

    try:
        await agent.connect()

        logger.info("\n" + "#" * 65)
        logger.info(f"🎯 [CUTSHORT AUTO-APPLY AGENT] Applying across matched profile jobs [Target: {target_applied} applied]")
        logger.info("#" * 65)

        # 1. Configure Experience (0-2 yrs) & Hiring Activity (1 Days)
        await agent.configure_filters()

        # 2. Extract, tailor resume, type recruiter message, and submit
        results, count = await agent.extract_and_apply_jobs(
            target_applied=target_applied,
            max_inspect_per_page=max_jobs,
        )
        all_results.extend(results)
        logger.info(f"📊 [CUTSHORT RUN COMPLETE] Submitted {count}/{target_applied} applications.")

    except Exception as e:
        logger.error(f"Error during Cutshort auto-apply run: {e}", exc_info=True)
    finally:
        try:
            await agent.close()
        except Exception:
            pass
        logger.info("🏁 Cutshort run completed. Cleaned up browser session.")

    return all_results
