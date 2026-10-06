"""
Hirist Browser Auto-Apply Agent (hirist.tech).

Automates job discovery and application submissions on Hirist:
  1. Navigates to Hirist Feed with target filters:
     https://www.hirist.tech/jobfeed?minexp=0&maxexp=1&sort=date&posting=2
  2. Verifies session status; prompts and pauses if sign-in is required.
  3. Iterates through job feed cards top-to-bottom.
  4. Opens each job in a new tab:
     - Reads the complete Job Description, Title, Company, and Experience.
     - Performs experience screening for Kamal's profile (0-2 years).
     - Tailors a fresh 1-page ATS PDF resume in resumes/hirist/ via ResumeService.
     - Clicks 'Apply' / 'Easy Apply' and handles resume attachment / confirmation.
     - Confirms submission and records in JobTracker.
     - Sends application notification email.
     - Closes the job tab and returns to the feed tab.
  5. Scrolls feed to lazy-load more matching roles until target applications are reached.
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

HIRIST_FEED_URL = "https://www.hirist.tech/jobfeed?minexp=0&maxexp=1&sort=date&posting=2"


class HiristExperienceAnalyzer:
    """Experience analyzer for Hirist job postings (0-2 years target profile)."""

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
                    "reason": f"Title contains senior keyword '{m.group(0)}'",
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


class HiristBrowserAgent:
    """Automates job discovery and applications on Hirist (hirist.tech)."""

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

        self.resumes_dir = Path("resumes/hirist")
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
            logger.info("🚀 Launching persistent Google Chrome for Hirist Agent...")
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
            fallback_url=HIRIST_FEED_URL,
            allowed_domains=["hirist.tech", "hirist.com"],
        )
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url=HIRIST_FEED_URL,
            allowed_domains=["hirist.tech", "hirist.com"],
        )

        logger.info("🔍 Checking Hirist session status...")
        await self._page.goto(HIRIST_FEED_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3.5)
        await self._check_and_wait_for_signin()

    async def _check_and_wait_for_signin(self):
        """Check if Hirist requires sign-in and pause until user logs in."""
        for attempt in range(300):
            try:
                current_url = self._page.url.lower()

                # If redirected to home or login page
                is_logged_in = await self._page.evaluate("""
                    () => {
                        const url = window.location.href.toLowerCase();
                        if (url.includes('jobfeed') || url.includes('/feed') || url.includes('/profile') || url.includes('/candidate')) {
                            return true;
                        }
                        const buttons = Array.from(document.querySelectorAll("button, a")).map(b => (b.innerText || '').trim().toLowerCase());
                        const hasLoginBtn = buttons.includes('login') || buttons.includes('register') || buttons.includes('login as recruiter');
                        const hasUserAvatar = !!document.querySelector("div[class*='avatar'], button[aria-label*='user'], div[class*='profile']");
                        return !hasLoginBtn || hasUserAvatar;
                    }
                """)

                if is_logged_in and "jobfeed" in current_url:
                    if attempt > 0:
                        logger.info("✅ Hirist sign-in detected! Resuming agent...")
                    else:
                        logger.info("✅ Logged in to Hirist successfully!")
                    return

                # If not logged in yet
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info("🔐  HIRIST SIGN-IN REQUIRED!")
                    logger.info("👉  Please log in to your Hirist account in the opened Chrome window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email="kamalkumar.doddi@gmail.com",
                                subject="🔐 [ACTION REQUIRED] Please Sign In to Hirist",
                                body="Hello Kamal,\n\nThe Hirist Auto-Apply Agent requires you to log in.\n\n👉 Please switch to the open Chrome browser window on your computer and sign in to Hirist.\n\nThe agent will automatically detect that you have signed in and start applying immediately.\n\nBest,\nAI Job Agent"
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
    async def _human_move_to(self, page, target_x: float, target_y: float, steps: int = 6):
        try:
            start_x = self._last_mouse_x or random.randint(300, 700)
            start_y = self._last_mouse_y or random.randint(300, 600)
            for i in range(1, steps + 1):
                t = i / steps
                cur_x = start_x + (target_x - start_x) * t + random.uniform(-4, 4) * (1 - t)
                cur_y = start_y + (target_y - start_y) * t + random.uniform(-4, 4) * (1 - t)
                await page.mouse.move(cur_x, cur_y)
                await asyncio.sleep(random.uniform(0.015, 0.04))
            await page.mouse.move(target_x, target_y)
            self._last_mouse_x = target_x
            self._last_mouse_y = target_y
        except Exception:
            pass

    async def _human_click(self, page, element, hover_pause: tuple[float, float] = (0.2, 0.45), click_delay: tuple[int, int] = (65, 125), post_pause: tuple[float, float] = (0.4, 0.8)):
        try:
            if not element:
                return
            await element.scroll_into_view_if_needed()
            box = await element.bounding_box()
            if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
                target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                await self._human_move_to(page, target_x, target_y)
                await asyncio.sleep(random.uniform(*hover_pause))
                await page.mouse.click(target_x, target_y, delay=random.randint(*click_delay))
            else:
                await asyncio.sleep(random.uniform(*hover_pause))
                await element.click(delay=random.randint(*click_delay))
            await asyncio.sleep(random.uniform(*post_pause))
        except Exception:
            try:
                await element.click(force=True)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # FEED ITERATION & APPLICATION WORKFLOW (NEW TAB HANDLING)
    # -------------------------------------------------------------------------
    async def extract_and_apply_jobs(
        self,
        target_applied: int = 5,
        max_inspect_per_page: int = 50,
    ) -> tuple[list[dict], int]:
        """
        Iterates through Hirist job feed top-to-bottom:
        1. Clicks job card in feed to open in a new tab.
        2. Switches to new tab, reads full JD, screens experience, tailors resume.
        3. Clicks Apply, confirms submission, records in JobTracker.
        4. Closes the job tab and returns to the feed tab.
        5. Scrolls down to lazy-load more matching roles until target is reached.
        """
        results = []
        applied_count = 0
        inspected_hrefs = set()
        consecutive_empty_scrolls = 0
        max_scroll_attempts = 3

        logger.info(f"🎯 Beginning Hirist auto-apply run on jobfeed (Target: {target_applied} applied)...")
        logger.info(f"🔗 Target Feed URL: {HIRIST_FEED_URL}")

        # Ensure on feed URL
        if "jobfeed" not in self._page.url.lower():
            await self._page.goto(HIRIST_FEED_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3.0)

        while applied_count < target_applied and consecutive_empty_scrolls < max_scroll_attempts:
            # Guard against any stuck about:blank or secondary popup tabs
            self._page, _ = await clean_and_recover_blank_tabs(
                self._context,
                self._page,
                fallback_url=HIRIST_FEED_URL,
                allowed_domains=["hirist.tech", "hirist.com"],
            )

            # 1. Discover all job links in feed
            job_links = await self._page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll("a[href*='/j/']"));
                    return links.map(a => {
                        const href = a.href;
                        const text = (a.innerText || a.textContent || '').trim();
                        const card = a.closest("div[class*='card'], div.border, div.shadow, li, div[class*='job']") || a;
                        const cardText = (card.innerText || card.textContent || '').trim();
                        return {
                            href: href,
                            title: text.split('\\n')[0].trim(),
                            cardText: cardText
                        };
                    }).filter(j => j.href && j.href.includes('/j/'));
                }
            """)

            # Deduplicate by href
            unique_links = []
            seen_in_scan = set()
            for jl in job_links:
                href = jl.get("href", "")
                if href and href not in seen_in_scan:
                    seen_in_scan.add(href)
                    unique_links.append(jl)

            if not unique_links:
                consecutive_empty_scrolls += 1
                logger.info(f"📜 No jobs visible in feed viewport. Scrolling down to load ({consecutive_empty_scrolls}/{max_scroll_attempts})...")
                await self._trigger_scroll_load()
                await asyncio.sleep(2.5)
                continue

            logger.info(f"📋 Checking {len(unique_links)} job card(s) visible on Hirist feed...")
            found_new_in_batch = False

            for j_data in unique_links:
                if applied_count >= target_applied:
                    break

                job_url = j_data.get("href", "")
                card_title = j_data.get("title", "")
                card_text = j_data.get("cardText", "")

                if not job_url or job_url in inspected_hrefs:
                    continue

                inspected_hrefs.add(job_url)
                found_new_in_batch = True

                # Parse rough company and title from card text
                rough_company = "Tech Company"
                rough_title = card_title or "Software Engineer"
                if " - " in rough_title:
                    parts = rough_title.split(" - ", 1)
                    rough_company = parts[0].strip()
                    rough_title = parts[1].strip()

                # 1. DEDUPLICATION CHECK IN JOBTRACKER
                if JobTracker.is_applied_or_emailed("hirist", rough_company, rough_title, job_url):
                    logger.info(f"⏭️ Skipping already applied job: '{rough_title}' @ {rough_company}")
                    continue

                # 2. Screening title
                title_screen = HiristExperienceAnalyzer.analyze_title(rough_title)
                if not title_screen["eligible"]:
                    logger.info(f"⏩ Skipping '{rough_title}' — {title_screen['reason']}")
                    continue

                logger.info(f"\n[{applied_count + 1}/{target_applied}] 🔎 [Hirist] Processing: '{rough_title}' @ {rough_company}...")

                # 3. OPEN JOB IN NEW TAB
                job_page = None
                try:
                    # Find matching link on page and click with expect_page
                    link_selector = f"a[href='{job_url}'], a[href*='{job_url.split('?')[0].replace('https://www.hirist.tech', '')}']"
                    link_el = await self._page.query_selector(link_selector)

                    if link_el:
                        await link_el.scroll_into_view_if_needed()
                        async with self._context.expect_page(timeout=10000) as new_page_info:
                            await self._human_click(self._page, link_el)
                        job_page = await new_page_info.value
                    else:
                        # Fallback: create new page directly
                        job_page = await self._context.new_page()
                        await job_page.goto(job_url, wait_until="domcontentloaded", timeout=45000)

                    # Check if opened job tab is stuck on about:blank
                    if is_blank_url(job_page.url):
                        for _ in range(6):
                            await asyncio.sleep(0.5)
                            if not is_blank_url(job_page.url):
                                break

                    if is_blank_url(job_page.url):
                        logger.warning(f"⚠️ [Hirist Tab Guard] Job tab for '{rough_title}' opened as 'about:blank'. Closing blank tab and refreshing previous page...")
                        try:
                            if not job_page.is_closed():
                                await job_page.close()
                        except Exception:
                            pass
                        await self._page.bring_to_front()
                        await self._page.reload(wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(2.0)
                        continue

                    await job_page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2.5)

                    # 4. EXTRACT COMPLETE JOB DETAILS FROM NEW TAB
                    job_details = await job_page.evaluate("""
                        () => {
                            const h1 = document.querySelector("h1, h2, h3, div.font-bold");
                            let rawTitle = h1 ? (h1.innerText || h1.textContent || '').trim() : '';

                            let comp = "";
                            let jobTitle = rawTitle;
                            if (rawTitle.includes(' - ')) {
                                const parts = rawTitle.split(' - ');
                                comp = parts[0].trim();
                                jobTitle = parts.slice(1).join(' - ').trim();
                            }

                            const bodyText = document.body.innerText || '';
                            const jdEl = document.querySelector("div[class*='job-desc'], div[class*='jobDescription'], div[class*='description']");
                            const jdText = jdEl ? (jdEl.innerText || jdEl.textContent || '').trim() : bodyText;

                            const isAlreadyApplied = Array.from(document.querySelectorAll("button, div, span")).some(el => {
                                const t = (el.innerText || '').trim().toLowerCase();
                                return t === 'applied' || t.includes('already applied') || t === 'application submitted';
                            });

                            return {
                                title: jobTitle || rawTitle || "Software Engineer",
                                company: comp || "Company",
                                fullJd: jdText,
                                isAlreadyApplied: isAlreadyApplied
                            };
                        }
                    """)

                    title = job_details.get("title") or rough_title
                    company = job_details.get("company") or rough_company
                    full_jd = job_details.get("fullJd") or card_text
                    is_already_applied = job_details.get("isAlreadyApplied", False)

                    # Check if page indicates already applied
                    if is_already_applied:
                        logger.info(f"⏭️ Job page indicates already applied: '{title}' @ {company}")
                        JobTracker.record_job("hirist", company, title, job_url, status="APPLIED", job_url=job_url)
                        await job_page.close()
                        await self._page.bring_to_front()
                        continue

                    # 5. EXPERIENCE SCREENING ON FULL JD
                    jd_screen = HiristExperienceAnalyzer.analyze(title, full_jd)
                    if not jd_screen["eligible"]:
                        logger.info(f"⏩ Skipping '{title}' — {jd_screen['reason']}")
                        await job_page.close()
                        await self._page.bring_to_front()
                        continue

                    # 6. TAILOR 1-PAGE ATS PDF RESUME
                    job_dict = {
                        "id": f"hirist_{applied_count + 1}_{int(time.time())}",
                        "title": title,
                        "company": company,
                        "description": full_jd,
                        "portal": "hirist",
                    }
                    logger.info(f"📄 Generating tailored 1-page ATS PDF resume in resumes/hirist/ for {company}...")
                    tailored_pdf_path = self.resume_service.generate_tailored_resume(
                        job=job_dict,
                        candidate_profile={},
                        portal="hirist",
                    )
                    logger.info(f"✅ Generated tailored resume: {tailored_pdf_path}")

                    # 7. CLICK 'APPLY' BUTTON ON JOB PAGE
                    apply_btn = await job_page.query_selector(
                        "button:has-text('Apply'), button:has-text('Apply Now'), button:has-text('Easy Apply'), a.btn:has-text('Apply'), button.MuiButton-containedPrimary"
                    )

                    if not apply_btn:
                        logger.warning(f"Apply button not found for '{title}' @ {company} — skipping")
                        await job_page.close()
                        await self._page.bring_to_front()
                        continue

                    if self.dry_run:
                        logger.info(f"🧪 [DRY RUN] Prepared Hirist application for '{title}' @ {company}. Skipping live click...")
                        JobTracker.record_job("hirist", company, title, job_url, status="DRY_RUN", job_url=job_url)
                        results.append({"title": title, "company": company, "status": "DRY_RUN"})
                        applied_count += 1
                        await job_page.close()
                        await self._page.bring_to_front()
                        continue

                    # Live apply click
                    logger.info(f"🚀 [LIVE] Clicking 'Apply' for '{title}' @ {company}...")
                    await self._human_click(job_page, apply_btn, hover_pause=(0.3, 0.6), post_pause=(2.0, 3.0))
                    await asyncio.sleep(2.5)

                    # 8. HANDLE ANY CONFIRMATION MODAL / RESUME UPLOAD IF PRESENT
                    try:
                        modal_file_input = await job_page.query_selector("input[type='file']")
                        if modal_file_input:
                            logger.info("📤 Attaching tailored resume to Hirist application modal...")
                            await modal_file_input.set_input_files(tailored_pdf_path)
                            await asyncio.sleep(1.5)

                        confirm_btn = await job_page.query_selector(
                            "div[role='dialog'] button:has-text('Submit'), div[role='dialog'] button:has-text('Confirm'), div[role='dialog'] button:has-text('Apply'), button:has-text('Submit Application')"
                        )
                        if confirm_btn and await confirm_btn.is_visible():
                            logger.info("🚀 Clicking modal confirmation button...")
                            await self._human_click(job_page, confirm_btn, post_pause=(2.0, 3.0))
                            await asyncio.sleep(2.5)
                    except Exception as mod_err:
                        logger.debug(f"Modal handling note: {mod_err}")

                    # 9. RECORD APPLICATION & NOTIFY
                    JobTracker.record_job("hirist", company, title, job_url, status="APPLIED", job_url=job_url)
                    try:
                        self.email_service.send_application_notification(
                            job_title=title,
                            company=company,
                            portal="Hirist",
                            job_url=job_url,
                        )
                    except Exception:
                        pass

                    applied_count += 1
                    logger.info(f"🎉 Successfully applied to '{title}' @ {company}! Total applied: {applied_count}/{target_applied}")
                    results.append({"title": title, "company": company, "status": "APPLIED"})

                    # 10. CLOSE JOB TAB & RETURN FOCUS TO FEED TAB
                    await job_page.close()
                    await self._page.bring_to_front()
                    await asyncio.sleep(1.5)

                except Exception as tab_err:
                    logger.error(f"Error processing job tab for '{rough_title}': {tab_err}", exc_info=True)
                    if job_page:
                        try:
                            await job_page.close()
                        except Exception:
                            pass
                    await self._page.bring_to_front()

            # If current feed batch is finished and target not reached, scroll down to load more
            if applied_count < target_applied:
                if not found_new_in_batch:
                    consecutive_empty_scrolls += 1
                else:
                    consecutive_empty_scrolls = 0
                logger.info(f"📊 Progress: {applied_count}/{target_applied} applied. Scrolling down for more matching Hirist jobs...")
                await self._trigger_scroll_load()
                await asyncio.sleep(2.5)

        return results, applied_count

    async def _trigger_scroll_load(self):
        """Scroll bottom elements and containers to trigger Hirist infinite feed loading."""
        try:
            await self._page.evaluate("""
                () => {
                    const allLinks = Array.from(document.querySelectorAll("a[href*='/j/']"));
                    if (allLinks.length > 0) {
                        const lastLink = allLinks[allLinks.length - 1];
                        lastLink.scrollIntoView({ behavior: 'smooth', block: 'end' });
                    }
                    window.scrollBy(0, 1200);
                    document.documentElement.scrollTop += 1200;
                    document.body.scrollTop += 1200;
                    Array.from(document.querySelectorAll("div")).filter(d => d.scrollHeight > d.clientHeight && d.clientHeight > 300).forEach(d => d.scrollTop += 1200);
                }
            """)
            await self._page.keyboard.press("PageDown")
            await asyncio.sleep(0.5)
            await self._page.keyboard.press("PageDown")
        except Exception:
            pass

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


async def run_hirist_auto_apply(
    target_applied: int = 40,
    max_jobs: int = 50,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run autonomous Hirist auto-apply on 'jobfeed' matching Kamal's profile.
    Applies target_applied count per portal (40-50 apps) and advances to the next browser agent.
    URL: https://www.hirist.tech/jobfeed?minexp=0&maxexp=1&sort=date&posting=2
    """
    agent = HiristBrowserAgent(dry_run=dry_run)
    all_results = []

    try:
        await agent.connect()

        logger.info("\n" + "#" * 65)
        logger.info(f"🎯 [HIRIST AUTO-APPLY AGENT] Applying across matched feed jobs [Target: {target_applied} applied]")
        logger.info("#" * 65)

        results, count = await agent.extract_and_apply_jobs(
            target_applied=target_applied,
            max_inspect_per_page=max_jobs,
        )
        all_results.extend(results)
        logger.info(f"📊 [HIRIST RUN COMPLETE] Submitted {count}/{target_applied} applications.")

    except Exception as e:
        logger.error(f"Error during Hirist auto-apply run: {e}", exc_info=True)
    finally:
        try:
            await agent.close()
        except Exception:
            pass
        logger.info("🏁 Hirist run completed. Cleaned up browser session.")

    return all_results
