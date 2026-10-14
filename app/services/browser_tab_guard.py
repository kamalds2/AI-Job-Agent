"""
Browser Tab Guard & Single Chrome Connection Utility.

Enforces Two Core Rules Across All Browser Agents:
Rule 1: If any 'about:' or unrelated URL tab opens or redirects, close it immediately,
        return focus to the previous working tab, and pick up application flow seamlessly.
Rule 2: Never open extra Google Chrome instances (strictly connect to / reuse single Chrome on port 9222).
"""
import asyncio
import logging
import os
import subprocess
from typing import Optional, Tuple

import httpx
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("BrowserTabGuard")

DEFAULT_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_USER_DATA_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile")
CDP_PORT = 9222


def is_about_or_blank_url(url: Optional[str]) -> bool:
    """Checks if a URL represents an empty, about:*, error, or non-content page."""
    if not url:
        return True
    u = url.strip().lower()
    return (
        u in ("about:blank", "about:blank#", "about:srcdoc", "chrome://newtab/", "edge://newtab/")
        or u.startswith("about:")
        or u.startswith("chrome-error://")
        or u.startswith("data:text/html,chromewebdata")
        or "about.linkedin.com" in u
        or u.startswith("chrome://")
        or u.startswith("edge://")
    )


def is_blank_url(url: Optional[str]) -> bool:
    """Backward compatibility alias for is_about_or_blank_url."""
    return is_about_or_blank_url(url)


def is_unrelated_or_profile_url(
    url: Optional[str],
    allowed_domains: Optional[list[str]] = None,
) -> Tuple[bool, str]:
    """
    Rule 1 Checker:
    Checks if a URL is an about URL, blank page, off-target profile/candidate settings page,
    help/legal page, or an external domain outside the active portal.
    Returns (is_unwanted, reason_str).
    """
    if is_about_or_blank_url(url):
        return True, "about_url"

    u = (url or "").strip().lower()

    # Detect unwanted profile / account settings / help / about pages that derail automation
    profile_keywords = [
        "/candidate", "/profile", "/users/edit", "/user/edit",
        "/my-profile", "/my_profile", "/settings", "/account",
        "workatastartup.com/candidate", "workatastartup.com/profile",
        "hirist.tech/candidate",
        "about.linkedin.com",
        "linkedin.com/help",
        "linkedin.com/legal",
        "linkedin.com/safety",
    ]
    for pk in profile_keywords:
        if pk in u:
            # Legitimate search pages have /jobs or /companies or /jobfeed or /all-jobs
            if not any(k in u for k in ["/jobs", "/companies?", "/jobfeed", "/all-jobs"]):
                return True, f"unwanted_page ({pk})"

    # If allowed portal domains are specified (e.g. ['linkedin.com', 'workatastartup.com'])
    if allowed_domains:
        has_allowed = any(dom.lower() in u for dom in allowed_domains)
        if not has_allowed and not u.startswith("chrome://"):
            return True, "external_unrelated_domain"

    return False, "valid"


async def check_page_has_content(page: Page) -> bool:
    """Checks if the page DOM has loaded meaningful content."""
    try:
        if page.is_closed() or is_about_or_blank_url(page.url):
            return False
        length = await page.evaluate(
            "() => (document.body ? (document.body.innerText || '').trim().length : 0)"
        )
        return length > 10
    except Exception:
        return False


async def clean_and_recover_blank_tabs(
    context: BrowserContext,
    primary_page: Page,
    last_valid_url: Optional[str] = None,
    fallback_url: Optional[str] = None,
    allowed_domains: Optional[list[str]] = None,
    auto_refresh: bool = False,
) -> Tuple[Page, bool]:
    """
    Rule 1 Implementation:
    Scans all open tabs in the browser context:
    - Closes any 'about:*' or secondary unrelated/profile tabs.
    - Brings the primary working tab to the front.
    - If the primary tab landed on an unwanted about/profile/external page, navigates back to fallback_url.
    - By default does NOT reload primary tab if it is already valid, so in-progress modals / job selection pick up immediately.
    - Returns (active_page, recovered_flag).
    """
    if not context:
        return primary_page, False

    pages = context.pages
    if not pages:
        try:
            new_p = await context.new_page()
            target_url = last_valid_url or fallback_url
            if target_url:
                await new_p.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            return new_p, True
        except Exception as e:
            logger.warning(f"Error creating fallback page: {e}")
            return primary_page, False

    unwanted_secondary = []
    valid_pages = []

    for p in pages:
        if p.is_closed():
            continue
        try:
            is_unwanted, reason = is_unrelated_or_profile_url(p.url, allowed_domains=allowed_domains)
            if p != primary_page and is_unwanted:
                unwanted_secondary.append((p, reason))
            else:
                valid_pages.append(p)
        except Exception:
            if p != primary_page:
                unwanted_secondary.append((p, "exception"))
            else:
                valid_pages.append(p)

    # Close all secondary unwanted tabs (popups, about:blank, external redirects)
    if unwanted_secondary:
        logger.warning(
            f"⚠️ [Tab Guard] Detected and closing {len(unwanted_secondary)} secondary about/unwanted tab(s)..."
        )
        for sp, reason in unwanted_secondary:
            try:
                if not sp.is_closed():
                    await sp.close()
                    logger.info(f"  🗑️ Auto-closed secondary tab ({reason}).")
            except Exception as e:
                logger.debug(f"Note closing secondary tab: {e}")

    # Ensure primary page is valid and not stuck on a profile or external page
    target_page = primary_page if (primary_page in valid_pages and not primary_page.is_closed()) else (valid_pages[0] if valid_pages else None)

    if not target_page or target_page.is_closed():
        try:
            target_page = await context.new_page()
        except Exception:
            return primary_page, False

    # Check if target page is itself on an unwanted about or profile page
    target_unwanted, t_reason = is_unrelated_or_profile_url(target_page.url, allowed_domains=allowed_domains)
    recovery_url = fallback_url or last_valid_url

    if target_unwanted and recovery_url:
        logger.warning(f"⚠️ [Tab Guard] Active page is on {t_reason} ('{target_page.url}'). Reloading search URL: {recovery_url}...")
        try:
            await target_page.bring_to_front()
            await target_page.goto(recovery_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.0)
            logger.info("  ✅ Active page successfully recovered to search URL!")
            return target_page, True
        except Exception as e:
            logger.warning(f"Error recovering active page: {e}")

    try:
        await target_page.bring_to_front()
        if auto_refresh and unwanted_secondary:
            logger.info(f"  🔄 Refreshing primary page to ensure clean state: {target_page.url}...")
            await target_page.reload(wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(1.5)
        elif unwanted_secondary:
            logger.info("  🎯 Returned focus to previous tab — picking up application flow!")
    except Exception:
        pass

    return target_page, bool(unwanted_secondary)


def attach_context_blank_tab_monitor(
    context: BrowserContext,
    get_primary_page_fn,
    default_portal_url: Optional[str] = None,
    allowed_domains: Optional[list[str]] = None,
):
    """
    Rule 1 Event Monitor:
    Attaches an event handler to the browser context to automatically
    detect and close any newly opened popup or tab that remains 'about:*',
    lands on an unwanted profile/settings/about page, or strays to an external domain.
    Refocuses the primary working tab immediately so the agent picks up application flow.
    """
    async def on_new_page(new_page: Page):
        try:
            primary = get_primary_page_fn() if callable(get_primary_page_fn) else None
            # If this is the primary page itself, do not auto-close
            if primary and new_page == primary:
                return

            # Monitor the newly opened tab for up to 3 seconds
            for _ in range(6):
                await asyncio.sleep(0.5)
                if new_page.is_closed():
                    return
                url = new_page.url
                is_unwanted, reason = is_unrelated_or_profile_url(url, allowed_domains=allowed_domains)
                if is_unwanted:
                    break

            if not new_page.is_closed():
                url = new_page.url
                is_unwanted, reason = is_unrelated_or_profile_url(url, allowed_domains=allowed_domains)
                if is_unwanted:
                    logger.warning(f"⚠️ [Tab Guard Event] Newly opened tab is {reason} ('{url}'). Auto-closing tab...")
                    await new_page.close()
                    logger.info("  🗑️ Auto-closed about/unrelated popup tab.")

                    # Refocus primary page so agent immediately picks up
                    if primary and not primary.is_closed():
                        try:
                            await primary.bring_to_front()
                            # If primary itself is on profile/unwanted, navigate back to default_portal_url
                            p_unwanted, _ = is_unrelated_or_profile_url(primary.url, allowed_domains=allowed_domains)
                            if p_unwanted and default_portal_url:
                                logger.info(f"  🔄 Primary page was off-target. Navigating back to: {default_portal_url}")
                                await primary.goto(default_portal_url, wait_until="domcontentloaded", timeout=30000)
                            else:
                                logger.info("  ✅ Returned focus to primary tab — picking up workflow seamlessly!")
                        except Exception as e:
                            logger.debug(f"Note recovering primary page in monitor: {e}")
        except Exception as err:
            logger.debug(f"Tab guard page event handler note: {err}")

    def sync_listener(p: Page):
        asyncio.create_task(on_new_page(p))

    try:
        context.on("page", sync_listener)
        logger.info("🛡️ Tab Guard attached to browser context (Auto-closes about/unrelated tabs & preserves single Chrome window).")
    except Exception as e:
        logger.warning(f"Could not attach tab guard listener: {e}")


def is_cdp_port_open(port: int = CDP_PORT) -> bool:
    """Check if Chrome remote debugging port is open and listening."""
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=1.5)
        return resp.status_code == 200
    except Exception:
        return False


async def connect_or_launch_single_chrome(
    playwright,
    cdp_port: int = CDP_PORT,
    user_data_dir: Optional[str] = None,
    chrome_path: Optional[str] = None,
) -> Tuple[BrowserContext, Page, bool]:
    """
    Rule 2 Implementation:
    Strictly connects to or launches a SINGLE Google Chrome instance.
    Prevents spawning duplicate Chrome instances or multiple profiles (e.g. AgentProfile2).
    Returns (context, page, is_cdp).
    """
    c_path = chrome_path or DEFAULT_CHROME_PATH
    u_dir = user_data_dir or DEFAULT_USER_DATA_DIR

    # 1. Check if Chrome debugging port 9222 is already open
    if not is_cdp_port_open(cdp_port):
        # Spawn native Chrome with remote debugging port once
        cmd = [
            c_path,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={u_dir}",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ]
        logger.info(f"🚀 Spawning single Google Chrome instance on port {cdp_port}...")
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            logger.warning(f"Note launching native Chrome: {e}")

        # Wait up to 15 seconds for CDP port to open
        for _ in range(30):
            await asyncio.sleep(0.5)
            if is_cdp_port_open(cdp_port):
                break

    # 2. Connect over CDP to the single Chrome process
    if is_cdp_port_open(cdp_port):
        logger.info(f"🔌 Connecting to single Google Chrome over CDP (http://127.0.0.1:{cdp_port})...")
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}", timeout=15000)
        contexts = browser.contexts
        context = contexts[0] if contexts else await browser.new_context()
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        # Close any lingering about:blank or secondary tabs from previous runs
        if len(pages) > 1:
            for extra_p in pages[1:]:
                try:
                    if is_about_or_blank_url(extra_p.url):
                        await extra_p.close()
                except Exception:
                    pass

        logger.info("✅ Connected to single Chrome instance over CDP (Rule 2 enforced)!")
        return context, page, True

    # 3. Fallback: single persistent context with primary user_data_dir only (NEVER AgentProfile2)
    logger.info("🚀 Launching single persistent Google Chrome context...")
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=u_dir,
        executable_path=c_path,
        headless=False,
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        viewport=None,
    )
    pages = context.pages
    page = pages[0] if pages else await context.new_page()

    if len(pages) > 1:
        for extra_p in pages[1:]:
            try:
                if is_about_or_blank_url(extra_p.url):
                    await extra_p.close()
            except Exception:
                pass

    return context, page, False
