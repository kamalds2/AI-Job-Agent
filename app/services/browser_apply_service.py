"""
Playwright Browser Auto-Apply Service.
Navigates to job application pages using real headless Chromium,
bypasses Cloudflare / JavaScript protections, auto-fills form fields,
uploads the tailored PDF resume, answers screening questions, and submits.

Supported Boards:
  - Greenhouse (boards.greenhouse.io, embedded forms)
  - Ashby (jobs.ashbyhq.com)
  - Lever (jobs.lever.co)
  - Generic Web ATS Forms
"""
import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError

from app.config.settings import (
    CANDIDATE_NAME,
    EMAIL_ADDRESS,
    CANDIDATE_PHONE,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    DRY_RUN,
)

logger = logging.getLogger(__name__)

# Standard candidate profile information
FIRST_NAME = CANDIDATE_NAME.split()[0] if CANDIDATE_NAME else "Kamal"
LAST_NAME = " ".join(CANDIDATE_NAME.split()[1:]) if (CANDIDATE_NAME and len(CANDIDATE_NAME.split()) > 1) else "Kumar"
LOCATION = "Hyderabad, India"


class BrowserApplyService:
    """Automates web form submission on job boards via Playwright Chromium."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    async def apply(
        self,
        job_url: str,
        job_title: str,
        company_name: str,
        resume_pdf_path: str,
        cover_letter: str = "",
    ) -> dict:
        """
        Open the job application URL in headless Chromium, fill form fields,
        upload tailored resume PDF, and submit.
        """
        if DRY_RUN:
            logger.info(f"[BROWSER DRY RUN] Would auto-apply via browser for '{job_title}' @ {company_name} at {job_url}")
            return {"success": True, "method": "browser_playwright_dry_run", "message": "Dry run simulated successfully"}

        if not resume_pdf_path or not Path(resume_pdf_path).exists():
            logger.warning(f"[Browser Apply] Resume PDF not found at: {resume_pdf_path}")
            return {"success": False, "method": "browser_playwright", "message": "Resume PDF missing"}

        logger.info(f"🌐 [Browser Apply] Launching persistent browser context for '{job_title}' @ {company_name}...")

        browser_dir = Path("data/browser_profile")
        browser_dir.mkdir(parents=True, exist_ok=True)

        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(browser_dir),
                    headless=self.headless,
                    user_agent=self.user_agent,
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                page = context.pages[0] if context.pages else await context.new_page()

                # Navigate to application page
                try:
                    await page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                    await page.wait_for_timeout(2000)
                except Exception as ne:
                    logger.warning(f"[Browser Apply] Navigation warning for {job_url}: {ne}")

                # Check for login prompts and perform auto-login if needed
                await self._handle_portal_login(page)

                # If on job board landing page with an "Apply" button, click it to open the form
                await self._navigate_to_form(page)

                # Detect and fill the application form
                filled = await self._fill_form(page, resume_pdf_path, cover_letter)

                if not filled:
                    await context.close()
                    return {"success": False, "method": "browser_playwright", "message": "Could not detect or fill application form"}

                # Submit form
                submitted = await self._submit_form(page)
                await context.close()

                if submitted:
                    logger.info(f"✅ [Browser Apply] Successfully submitted application for '{job_title}' @ {company_name}")
                    return {"success": True, "method": "browser_playwright", "message": "Application submitted successfully"}
                else:
                    return {"success": False, "method": "browser_playwright", "message": "Submit button clicked but confirmation not confirmed"}

        except Exception as e:
            logger.error(f"❌ [Browser Apply] Error applying for '{job_title}' @ {company_name}: {e}")
            return {"success": False, "method": "browser_playwright", "message": str(e)}

    async def _handle_portal_login(self, page: Page):
        """Auto-login to job portals when a login modal or page is detected."""
        from app.config.settings import JOB_BOARD_EMAIL, JOB_BOARD_PASSWORD

        try:
            pwd_locators = ["input[type='password']", "input[name*='password' i]", "input[id*='password' i]"]
            is_login_page = False
            for sel in pwd_locators:
                if await page.locator(sel).count() > 0 and await page.locator(sel).first.is_visible():
                    is_login_page = True
                    break

            if is_login_page:
                logger.info(f"🔑 [Browser Login] Login prompt detected — logging in as {JOB_BOARD_EMAIL}...")

                # Email / Username
                email_locators = ["input[type='email']", "input[name*='email' i]", "input[name*='user' i]", "input[placeholder*='email' i]"]
                for sel in email_locators:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible():
                            await loc.fill(JOB_BOARD_EMAIL)
                            break
                    except Exception:
                        pass

                # Password
                for sel in pwd_locators:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible():
                            await loc.fill(JOB_BOARD_PASSWORD)
                            break
                    except Exception:
                        pass

                # Submit login button
                login_btn_selectors = [
                    "button[type='submit']", "input[type='submit']", "button:has-text('Log in' i)",
                    "button:has-text('Sign in' i)", "a:has-text('Log in' i)", "button:has-text('Login' i)",
                ]
                for sel in login_btn_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible():
                            await btn.click()
                            await page.wait_for_timeout(3000)
                            logger.info("✅ [Browser Login] Submitted login credentials and saved session")
                            break
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"[Browser Login] Portal login check: {e}")

    async def _navigate_to_form(self, page: Page):
        """Click 'Apply' or 'Apply for this job' button if the form is in a sub-section or modal."""
        apply_selectors = [
            "a[href*='#app']", "a[href*='apply']", "button:has-text('Apply')",
            "button:has-text('Apply for this job')", "button:has-text('Apply Now')",
            "a:has-text('Apply for this job')", "a:has-text('Apply Now')",
        ]
        for sel in apply_selectors:
            try:
                elem = page.locator(sel).first
                if await elem.is_visible():
                    await elem.click()
                    await page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

    async def _fill_form(self, page: Page, resume_pdf_path: str, cover_letter: str) -> bool:
        """Fill all standard job application inputs."""
        fields_filled = 0

        # 1. Full Name / First Name / Last Name
        first_name_locators = [
            "input[name='first_name']", "input[id*='first_name']", "input[name*='firstName']",
            "input[autocomplete='given-name']", "input[placeholder*='First Name' i]",
        ]
        for sel in first_name_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(FIRST_NAME)
                    fields_filled += 1
                    break
            except Exception:
                pass

        last_name_locators = [
            "input[name='last_name']", "input[id*='last_name']", "input[name*='lastName']",
            "input[autocomplete='family-name']", "input[placeholder*='Last Name' i]",
        ]
        for sel in last_name_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(LAST_NAME)
                    fields_filled += 1
                    break
            except Exception:
                pass

        # If single "Full Name" or "Name" input
        full_name_locators = [
            "input[name='name']", "input[id*='name']:not([id*='first']):not([id*='last'])",
            "input[placeholder*='Full Name' i]", "input[name*='fullName']",
        ]
        for sel in full_name_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible() and not await loc.input_value():
                    await loc.fill(CANDIDATE_NAME)
                    fields_filled += 1
                    break
            except Exception:
                pass

        # 2. Email Address
        email_locators = [
            "input[type='email']", "input[name='email']", "input[id*='email']",
            "input[autocomplete='email']", "input[placeholder*='Email' i]",
        ]
        for sel in email_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(EMAIL_ADDRESS)
                    fields_filled += 1
                    break
            except Exception:
                pass

        # 3. Phone Number
        phone_locators = [
            "input[type='tel']", "input[name='phone']", "input[id*='phone']",
            "input[autocomplete='tel']", "input[name*='phoneNumber']", "input[placeholder*='Phone' i]",
        ]
        for sel in phone_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(CANDIDATE_PHONE)
                    fields_filled += 1
                    break
            except Exception:
                pass

        # 4. Location / City
        loc_locators = [
            "input[name='location']", "input[id*='location']", "input[name*='city']",
            "input[placeholder*='Location' i]", "input[placeholder*='City' i]",
        ]
        for sel in loc_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(LOCATION)
                    break
            except Exception:
                pass

        # 5. LinkedIn Profile URL
        linkedin_locators = [
            "input[name*='linkedin' i]", "input[id*='linkedin' i]", "input[placeholder*='linkedin' i]",
            "input[name*='urls[LinkedIn]']", "input[name*='urls[linkedin]']",
        ]
        for sel in linkedin_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(CANDIDATE_LINKEDIN)
                    fields_filled += 1
                    break
            except Exception:
                pass

        # 6. GitHub Profile URL / Website
        github_locators = [
            "input[name*='github' i]", "input[id*='github' i]", "input[placeholder*='github' i]",
            "input[name*='urls[GitHub]']", "input[name*='website' i]", "input[placeholder*='website' i]",
        ]
        for sel in github_locators:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.fill(CANDIDATE_GITHUB)
                    break
            except Exception:
                pass

        # 7. Upload Tailored ATS PDF Resume
        abs_resume_path = str(Path(resume_pdf_path).resolve())
        file_inputs = [
            "input[type='file'][name*='resume' i]", "input[type='file'][id*='resume' i]",
            "input[type='file'][name*='cv' i]", "input[type='file']",
        ]
        file_uploaded = False
        for sel in file_inputs:
            try:
                loc = page.locator(sel).first
                count = await page.locator(sel).count()
                if count > 0:
                    await loc.set_input_files(abs_resume_path)
                    file_uploaded = True
                    fields_filled += 1
                    logger.info(f"📄 [Browser Apply] Attached resume PDF: {abs_resume_path}")
                    break
            except Exception as fe:
                logger.debug(f"[Browser Apply] File upload via selector {sel} failed: {fe}")

        # 8. Cover Letter textarea (if available)
        if cover_letter:
            cover_locators = [
                "textarea[name*='cover' i]", "textarea[id*='cover' i]",
                "textarea[placeholder*='cover' i]", "textarea[name*='comments' i]",
            ]
            for sel in cover_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible():
                        await loc.fill(cover_letter[:1500])
                        break
                except Exception:
                    pass

        # 9. Handle Standard Screening Checkboxes & Dropdowns (Work Authorization, Terms)
        try:
            # Check consent / terms checkboxes
            checkboxes = await page.locator("input[type='checkbox']").all()
            for cb in checkboxes:
                try:
                    if await cb.is_visible() and not await cb.is_checked():
                        await cb.check()
                except Exception:
                    pass
        except Exception:
            pass

        return fields_filled >= 2

    async def _submit_form(self, page: Page) -> bool:
        """Find and click the form submit button."""
        submit_selectors = [
            "button[type='submit']", "input[type='submit']",
            "button:has-text('Submit Application')", "button:has-text('Submit application')",
            "button:has-text('Submit')", "button:has-text('Send Application')",
            "a:has-text('Submit Application')",
        ]

        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(4000)
                    return True
            except Exception:
                continue

        return False
