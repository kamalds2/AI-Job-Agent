"""
Browser Tab Guard & Blank Page Auto-Recovery Utility.

Monitors Playwright browser contexts for stuck 'about:blank' tabs,
unwanted profile/candidate settings pages, and unrelated external popups.

Key Features:
1. Auto-detects and closes stuck 'about:blank' tabs.
2. Closes external / third-party popup tabs to prevent multiple browser windows.
3. Detects if the primary page was steered into candidate profile/account pages
   (e.g., /candidate, /profile) and recovers it back to the jobs search URL.
4. Brings the primary page to front and refreshes it so application flow continues uninterrupted.
"""
import asyncio
import logging
from typing import Optional, Tuple

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("BrowserTabGuard")


def is_blank_url(url: Optional[str]) -> bool:
    """Checks if a URL represents an empty or uninitialized page."""
    if not url:
        return True
    u = url.strip().lower()
    return (
        u in ("about:blank", "about:blank#", "about:srcdoc", "chrome://newtab/", "edge://newtab/")
        or u.startswith("about:")
        or u.startswith("chrome-error://")
        or u.startswith("data:text/html,chromewebdata")
    )


def is_unrelated_or_profile_url(
    url: Optional[str],
    allowed_domains: Optional[list[str]] = None,
) -> Tuple[bool, str]:
    """
    Checks if a URL is blank, an off-target profile/candidate settings page,
    or an external domain outside the active portal.
    Returns (is_unwanted, reason_str).
    """
    if is_blank_url(url):
        return True, "about_blank"

    u = (url or "").strip().lower()

    # Detect unwanted profile / account settings pages that derail automation
    profile_keywords = [
        "/candidate", "/profile", "/users/edit", "/user/edit",
        "/my-profile", "/my_profile", "/settings", "/account",
        "workatastartup.com/candidate", "workatastartup.com/profile",
        "hirist.tech/candidate",
    ]
    for pk in profile_keywords:
        if pk in u:
            # Legitimate search pages have /jobs or /companies or /jobfeed or /all-jobs
            if not any(k in u for k in ["/jobs", "/companies?", "/jobfeed", "/all-jobs"]):
                return True, f"profile_page ({pk})"

    # If allowed portal domains are specified (e.g. ['workatastartup.com', 'ycombinator.com'])
    if allowed_domains:
        has_allowed = any(dom.lower() in u for dom in allowed_domains)
        if not has_allowed and not u.startswith("chrome://"):
            return True, "external_unrelated_domain"

    return False, "valid"


async def check_page_has_content(page: Page) -> bool:
    """Checks if the page DOM has loaded meaningful content."""
    try:
        if page.is_closed() or is_blank_url(page.url):
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
    auto_refresh: bool = True,
) -> Tuple[Page, bool]:
    """
    Scans all open tabs in the browser context:
    - Closes any 'about:blank' or secondary unrelated/profile tabs.
    - Brings the primary working tab to front.
    - If the primary tab landed on an unwanted profile or external page, navigates back to fallback_url.
    - Refreshes the page to ensure the application flow continues uninterrupted.
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
            f"⚠️ [Tab Guard] Closing {len(unwanted_secondary)} secondary unwanted/popup tab(s)..."
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

    # Check if target page is itself on an unwanted page
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
    Attaches an event handler to the browser context to automatically
    detect and close any newly opened popup or tab that remains 'about:blank',
    lands on an unwanted profile/settings page, or strays to an external domain.
    """
    async def on_new_page(new_page: Page):
        try:
            primary = get_primary_page_fn() if callable(get_primary_page_fn) else None
            # If this is the primary page itself, do not auto-close
            if primary and new_page == primary:
                return

            # Monitor the newly opened tab for up to 3.5 seconds
            for _ in range(7):
                await asyncio.sleep(0.5)
                if new_page.is_closed():
                    return
                # Check url
                url = new_page.url
                is_unwanted, reason = is_unrelated_or_profile_url(url, allowed_domains=allowed_domains)
                if is_unwanted:
                    break

            if not new_page.is_closed():
                url = new_page.url
                is_unwanted, reason = is_unrelated_or_profile_url(url, allowed_domains=allowed_domains)
                if is_unwanted:
                    logger.warning(f"⚠️ [Tab Guard Event] Newly opened tab is {reason} ('{url}'). Closing tab to prevent multiple windows...")
                    await new_page.close()
                    logger.info("  🗑️ Auto-closed unwanted popup tab.")

                    # Refocus primary page
                    if primary and not primary.is_closed():
                        try:
                            await primary.bring_to_front()
                            # If primary itself is on profile/unwanted, navigate back to default_portal_url
                            p_unwanted, _ = is_unrelated_or_profile_url(primary.url, allowed_domains=allowed_domains)
                            if p_unwanted and default_portal_url:
                                logger.info(f"  🔄 Primary page was off-target. Navigating back to: {default_portal_url}")
                                await primary.goto(default_portal_url, wait_until="domcontentloaded", timeout=30000)
                            else:
                                await primary.reload(wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(1.5)
                            logger.info("  ✅ Resumed application flow on primary page!")
                        except Exception as e:
                            logger.debug(f"Note recovering primary page in monitor: {e}")
        except Exception as err:
            logger.debug(f"Tab guard page event handler note: {err}")

    def sync_listener(p: Page):
        asyncio.create_task(on_new_page(p))

    try:
        context.on("page", sync_listener)
        logger.info("🛡️ Tab Guard attached to browser context (Auto-closes blank/unrelated tabs and keeps single active window).")
    except Exception as e:
        logger.warning(f"Could not attach tab guard listener: {e}")
