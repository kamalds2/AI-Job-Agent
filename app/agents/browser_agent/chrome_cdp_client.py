"""
Chrome CDP Client — Manages connection to user's active Chrome browser session.
Supports connecting to running Chrome via Remote Debugging (CDP) or launching persistent context.
"""
import asyncio
import logging
import os
import random
import subprocess
from typing import Optional

import httpx
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.config.browser_settings import (
    CHROME_CDP_URL,
    CHROME_EXECUTABLE_PATH,
    CHROME_USER_DATA_DIR,
)

logger = logging.getLogger(__name__)


class ChromeCDPClient:
    """
    Manages Playwright connection to existing logged-in Chrome instance via CDP.
    """

    def __init__(self, cdp_url: str = CHROME_CDP_URL):
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._launched_process = None

    async def is_cdp_ready(self) -> bool:
        """Check if Chrome Remote Debugging port is answering HTTP requests."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.cdp_url}/json/version")
                return resp.status_code == 200
        except Exception:
            return False

    async def ensure_chrome_running(self) -> bool:
        """
        Verify Chrome is reachable on CDP port.
        If not, attempts to launch Chrome with remote debugging.
        """
        if await self.is_cdp_ready():
            logger.info(f"✅ Connected to existing Chrome session at {self.cdp_url}")
            return True

        logger.info(f"Chrome not detected on {self.cdp_url}. Attempting to launch with remote debugging...")
        if os.path.exists(CHROME_EXECUTABLE_PATH):
            cmd = [
                CHROME_EXECUTABLE_PATH,
                f"--remote-debugging-port=9222",
                f"--user-data-dir={CHROME_USER_DATA_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            try:
                self._launched_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # Wait up to 5 seconds for CDP port to open
                for _ in range(10):
                    await asyncio.sleep(0.5)
                    if await self.is_cdp_ready():
                        logger.info("✅ Chrome successfully launched and listening on port 9222")
                        return True
            except Exception as e:
                logger.warning(f"Could not launch Chrome process: {e}")

        return False

    async def connect(self) -> Page:
        """
        Establish connection to Chrome via Playwright CDP.
        Returns active Page.
        """
        self._playwright = await async_playwright().start()

        is_ready = await self.ensure_chrome_running()
        if is_ready:
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
                if self._browser.contexts:
                    self._context = self._browser.contexts[0]
                else:
                    self._context = await self._browser.new_context()

                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                else:
                    self._page = await self._context.new_page()

                logger.info("🌐 Connected to Chrome browser context via CDP")
                return self._page
            except Exception as e:
                logger.warning(f"CDP connection failed ({e}), falling back to persistent context")

        # Fallback: Launch persistent context with user data dir
        logger.info(f"Launching persistent Chrome context from {CHROME_USER_DATA_DIR}...")
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=CHROME_USER_DATA_DIR,
            executable_path=CHROME_EXECUTABLE_PATH if os.path.exists(CHROME_EXECUTABLE_PATH) else None,
            headless=False,
            args=["--start-maximized", "--no-sandbox"],
            viewport=None,
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        return self._page

    @property
    def page(self) -> Optional[Page]:
        return self._page

    async def human_delay(self, min_sec: float = 1.0, max_sec: float = 2.5):
        """Random humanized delay to prevent rate limiting or bot detection."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def human_type(self, selector_or_locator, text: str, delay_range: tuple = (30, 80)):
        """Type characters with human-like varying micro-delays."""
        if isinstance(selector_or_locator, str):
            loc = self._page.locator(selector_or_locator)
        else:
            loc = selector_or_locator

        await loc.click()
        await self.human_delay(0.2, 0.5)
        for char in text:
            await self._page.keyboard.type(char, delay=random.randint(*delay_range))

    async def smooth_scroll(self, scroll_element_selector: Optional[str] = None, distance: int = 400):
        """Perform a smooth, human-like scroll down."""
        if not self._page:
            return
        if scroll_element_selector:
            await self._page.evaluate(
                f"""(selector) => {{
                    const el = document.querySelector(selector);
                    if (el) el.scrollBy({{ top: {distance}, behavior: 'smooth' }});
                }}""",
                scroll_element_selector,
            )
        else:
            await self._page.evaluate(f"window.scrollBy({{ top: {distance}, behavior: 'smooth' }});")
        await self.human_delay(0.4, 0.8)

    async def close(self):
        """Cleanly close browser session and Playwright instance."""
        try:
            if self._browser:
                await self._browser.close()
            elif self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug(f"Error during browser client shutdown: {e}")
