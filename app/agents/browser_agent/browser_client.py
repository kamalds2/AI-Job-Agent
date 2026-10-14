"""
Shared Browser Client for Autonomous Multi-Portal Agents.
Connects to live browser via Chrome DevTools Protocol (CDP Port 9222).
Supports Google Chrome, Microsoft Edge, and system browser with persistent user profiles.
Includes sign-in detection and pause loops, humanized interactions, and native Windows dialog handling.
"""
import asyncio
import logging
import os
import random
import subprocess
import sys
import time
from typing import Optional

import httpx
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
)
from app.services.browser_tab_guard import (
    attach_context_blank_tab_monitor,
    clean_and_recover_blank_tabs,
    connect_or_launch_single_chrome,
    is_about_or_blank_url,
    is_blank_url,
)
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


def handle_windows_file_dialog(file_path: str, max_wait_sec: float = 6.0) -> bool:
    """Handle or fill native Windows 'Open' file dialog if browser opens one."""
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


class SharedBrowserClient:
    """
    Universal CDP and persistent browser controller for all portal auto-apply agents.
    Strictly reuses a single Google Chrome instance over CDP (port 9222) and protects against
    extra Chrome window spawning (Rule 2) or stray about:blank tabs (Rule 1).
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: Optional[str] = None,
        browser_executable_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.cdp_port = cdp_port
        self.user_data_dir = user_data_dir or os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile")

        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        if browser_executable_path and os.path.exists(browser_executable_path):
            self.browser_path = browser_executable_path
        else:
            self.browser_path = next((p for p in chrome_candidates if os.path.exists(p)), chrome_candidates[0])

        self.dry_run = dry_run
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._owns_context = True
        self._is_cdp = False

        self._last_mouse_x = 400.0
        self._last_mouse_y = 400.0
        self.email_service = EmailService()

    def is_cdp_port_open(self) -> bool:
        """Check if CDP remote debugging port responds."""
        try:
            r = httpx.get(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    async def connect(self, context=None, page=None) -> Page:
        """Connect to live browser via CDP, reusing the single instance without spawning extra Chromes."""
        if context:
            self._context = context
            self._owns_context = False
            if page and not page.is_closed():
                self._page = page
            else:
                self._page = await self.ensure_active_page()
            attach_context_blank_tab_monitor(
                self._context,
                lambda: self._page,
                default_portal_url=None,
                allowed_domains=None,
            )
            return self._page

        self._playwright = await async_playwright().start()

        # Connect or launch strictly ONE Chrome instance
        self._context, self._page, self._is_cdp = await connect_or_launch_single_chrome(
            self._playwright,
            cdp_port=self.cdp_port,
            user_data_dir=self.user_data_dir,
            chrome_path=self.browser_path,
        )

        # Attach monitor to close about:blank or unrelated popups immediately
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url=None,
            allowed_domains=None,
        )

        # Stealth overrides
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        return self._page

    async def ensure_active_page(self) -> Page:
        """Ensure we have a valid, non-closed Page object from current context without blank/about tabs."""
        try:
            if self._page and not self._page.is_closed():
                if not is_about_or_blank_url(self._page.url):
                    return self._page
        except Exception:
            pass

        if self._context:
            try:
                self._page, _ = await clean_and_recover_blank_tabs(
                    self._context,
                    self._page,
                    auto_refresh=False,
                )
                if self._page and not self._page.is_closed() and not is_about_or_blank_url(self._page.url):
                    return self._page
                pages = [p for p in self._context.pages if not p.is_closed() and not is_about_or_blank_url(p.url)]
                if pages:
                    self._page = pages[-1]
                    await self._page.bring_to_front()
                    return self._page
                self._page = await self._context.new_page()
                return self._page
            except Exception as e:
                logger.warning(f"Could not get/create page from context: {e}")

        # If context is also gone, reconnect
        return await self.connect()

    async def safe_goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 45000,
        max_retries: int = 3,
    ) -> bool:
        """
        Safely navigates to URL, canceling any background navigation conflicts and retrying.
        """
        for attempt in range(1, max_retries + 1):
            try:
                page = await self.ensure_active_page()
                try:
                    await page.evaluate("window.stop();")
                except Exception:
                    pass
                await asyncio.sleep(0.4)
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                await asyncio.sleep(1.2)
                return True
            except Exception as e:
                logger.warning(f"safe_goto attempt {attempt}/{max_retries} for '{url}' note: {e}")
                if attempt == max_retries:
                    raise e
                await asyncio.sleep(1.5 * attempt)
        return False

    async def wait_for_portal_signin(
        self,
        portal_name: str,
        logged_in_selectors: list[str],
        logged_out_selectors: Optional[list[str]] = None,
        auth_url_patterns: Optional[list[str]] = None,
    ) -> bool:
        """
        Rigorous Sign-in Verification & Active Wait Loop:
        1. Checks whether user is explicitly logged in.
        2. Detects explicit logged-out / login page states.
        3. If not signed in, pauses, sends an Action Required email notification,
           and loops until the user logs in in the browser window.
        """
        logged_out_selectors = logged_out_selectors or []
        auth_url_patterns = auth_url_patterns or ["/login", "/auth", "signin", "sign_in", "checkpoint"]

        for attempt in range(300):
            try:
                page = await self.ensure_active_page()
                current_url = page.url.lower()

                # 1. Check if URL matches authentication / login page
                is_on_auth_url = any(pat.lower() in current_url for pat in auth_url_patterns)

                # 2. Check if logged-out elements are visible
                has_logged_out_elem = False
                for sel in logged_out_selectors:
                    elem = await page.query_selector(sel)
                    if elem and await elem.is_visible():
                        has_logged_out_elem = True
                        break

                # 3. Check if logged-in elements are visible
                has_logged_in_elem = False
                for sel in logged_in_selectors:
                    elem = await page.query_selector(sel)
                    if elem and await elem.is_visible():
                        has_logged_in_elem = True
                        break

                # Confirmed authenticated:
                # If logged_in elements are found and NOT on an auth/login page, user is signed in!
                if has_logged_in_elem and not is_on_auth_url:
                    if attempt > 0:
                        logger.info(f"✅ {portal_name} sign-in detected! Resuming agent execution...")
                    else:
                        logger.info(f"✅ Logged in to {portal_name} successfully!")
                    return True

                # If not logged in yet -> Send Email and Wait
                if attempt == 0 or attempt % 30 == 0:
                    logger.info("\n" + "=" * 68)
                    logger.info(f"🔐  {portal_name.upper()} SIGN-IN REQUIRED!")
                    logger.info(f"👉  Please log in to your {portal_name} account in the opened Microsoft Edge window.")
                    logger.info("⏳  The agent is paused and waiting for you to complete sign-in...")
                    logger.info("=" * 68 + "\n")
                    if attempt == 0:
                        try:
                            self.email_service.send_email(
                                to_email=CANDIDATE_EMAIL,
                                subject=f"🔐 [ACTION REQUIRED] Please Sign In to {portal_name}",
                                body=(
                                    f"Hello {CANDIDATE_NAME},\n\n"
                                    f"The {portal_name} Auto-Apply Agent requires you to log in.\n\n"
                                    f"👉 Please switch to the open Microsoft Edge browser window on your computer and sign in to {portal_name}.\n\n"
                                    f"The agent is actively monitoring the window and will automatically resume applications as soon as you sign in.\n\n"
                                    f"Best regards,\nAI Job Agent Orchestrator"
                                ),
                            )
                            logger.info(f"📧 Sent sign-in notification email to {CANDIDATE_EMAIL}")
                        except Exception as e:
                            logger.warning(f"Could not send sign-in notification email: {e}")

                await asyncio.sleep(3.0)
            except Exception as wait_err:
                logger.debug(f"Sign-in check polling note: {wait_err}")
                await asyncio.sleep(2.0)
        return False

    # ── Human-like Mouse and Keyboard Interactions ─────────────────
    async def human_move_to(self, target_x: float, target_y: float, steps: int = 6):
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

    async def human_click(
        self,
        element,
        hover_pause: tuple = (0.2, 0.45),
        click_delay: tuple = (65, 125),
        post_pause: tuple = (0.4, 0.8),
    ):
        try:
            if not element:
                return
            await element.scroll_into_view_if_needed()
            box = await element.bounding_box()
            if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
                target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                await self.human_move_to(target_x, target_y)
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

    async def human_type(self, element, text: str):
        try:
            if not element:
                return
            await self.human_click(element, hover_pause=(0.1, 0.25), post_pause=(0.15, 0.3))
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

    async def close(self):
        """Cleanly disconnect or close browser resources without terminating the single CDP Chrome."""
        try:
            if self._context and not self._context.is_closed():
                pages = [p for p in self._context.pages if not p.is_closed()]
                for p in pages[1:]:
                    try:
                        await p.close()
                    except Exception:
                        pass
            if not self._is_cdp and self._context and self._owns_context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
