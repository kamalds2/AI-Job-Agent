"""
Agent 1: LinkedIn Browser Harvester
Navigates LinkedIn Jobs, applies precise filters (Past 24 Hours, Easy Apply, Location),
expands full job descriptions ('See more'), and extracts rich structured job payloads.
"""
import asyncio
import logging
import urllib.parse
from typing import AsyncGenerator, Dict, List, Optional

from playwright.async_api import Locator, Page

from app.config.browser_settings import (
    LINKEDIN_EASY_APPLY_ONLY,
    LINKEDIN_LOCATION,
    LINKEDIN_PAST_24_HOURS,
    LINKEDIN_SEARCH_KEYWORDS,
)

logger = logging.getLogger(__name__)


class LinkedInHarvester:
    """
    Agent 1: Discovers and extracts full job descriptions from LinkedIn Jobs.
    """

    def __init__(self, page: Page):
        self.page = page

    def build_search_url(
        self,
        keyword: str,
        location: str = LINKEDIN_LOCATION,
        past_24h: bool = LINKEDIN_PAST_24_HOURS,
        easy_apply: bool = LINKEDIN_EASY_APPLY_ONLY,
        experience_levels: str = "1,2,3",
    ) -> str:
        """Constructs an optimized LinkedIn Jobs URL with active filters (Internship, Entry level, Associate)."""
        params = {
            "keywords": keyword,
            "location": location,
            "sortBy": "DD",  # Most Recent
            "f_E": experience_levels,  # 1=Internship, 2=Entry level, 3=Associate
        }
        if past_24h:
            params["f_TPR"] = "r86400"  # Past 24 hours
        if easy_apply:
            params["f_AL"] = "true"  # Easy Apply

        query_string = urllib.parse.urlencode(params)
        return f"https://www.linkedin.com/jobs/search/?{query_string}"

    async def search_and_harvest(
        self,
        keyword: str,
        max_jobs: int = 15,
    ) -> AsyncGenerator[Dict, None]:
        """
        Navigates to LinkedIn jobs search, iterates through job listings,
        clicks 'See more' to reveal full JD, and yields complete job payloads.
        """
        search_url = self.build_search_url(keyword=keyword)
        logger.info(f"🌐 [Agent 1] Navigating to LinkedIn search: '{keyword}' (Past 24h: {LINKEDIN_PAST_24_HOURS}, Easy Apply: {LINKEDIN_EASY_APPLY_ONLY})")
        
        try:
            await self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.5)

            # Wait for job list container
            list_selector = "ul.scaffold-layout__list-container, div.jobs-search-results-list, div.scaffold-layout__list"
            try:
                await self.page.wait_for_selector(list_selector, timeout=12000)
            except Exception:
                logger.warning("[Agent 1] Job list container not found immediately — checking page state")

            # Collect job card items
            job_cards_selector = (
                "li.jobs-search-results__list-item, "
                "div.job-card-container, "
                "div.job-card-job-posting-card-wrapper, "
                "div.artdeco-entity-lockup"
            )
            job_cards = await self.page.locator(job_cards_selector).all()
            logger.info(f"📋 [Agent 1] Found {len(job_cards)} job cards on current page for '{keyword}'")

            harvested_count = 0
            seen_job_ids = set()

            for idx, card in enumerate(job_cards):
                if harvested_count >= max_jobs:
                    break

                try:
                    # Scroll card into view
                    await card.scroll_into_view_if_needed(timeout=3000)
                    await asyncio.sleep(0.4)

                    # Click job card to load right details pane
                    await card.click(timeout=4000)
                    await asyncio.sleep(1.2)

                    # Extract Job Title & Company
                    title_elem = self.page.locator(
                        "h1.job-details-jobs-unified-top-card__job-title, "
                        "h2.job-details-jobs-unified-top-card__job-title, "
                        "h1.t-24"
                    ).first
                    title = await title_elem.inner_text() if await title_elem.count() > 0 else "Unknown Title"

                    company_elem = self.page.locator(
                        "div.job-details-jobs-unified-top-card__company-name a, "
                        "a.job-details-jobs-unified-top-card__company-name, "
                        "span.job-details-jobs-unified-top-card__company-name"
                    ).first
                    company = await company_elem.inner_text() if await company_elem.count() > 0 else "Unknown Company"

                    location_elem = self.page.locator(
                        "span.job-details-jobs-unified-top-card__bullet, "
                        "div.job-details-jobs-unified-top-card__primary-description-container span"
                    ).first
                    location = await location_elem.inner_text() if await location_elem.count() > 0 else LINKEDIN_LOCATION

                    # Expand Full Description ('See more')
                    see_more_selectors = [
                        "button.jobs-description__footer-button",
                        "button[aria-label*='more']",
                        "button:has-text('See more')",
                        "button:has-text('...more')",
                        "button:has-text('Show more')",
                    ]
                    for btn_sel in see_more_selectors:
                        see_more_btn = self.page.locator(btn_sel).first
                        if await see_more_btn.count() > 0 and await see_more_btn.is_visible():
                            try:
                                await see_more_btn.click(timeout=1500)
                                await asyncio.sleep(0.5)
                                break
                            except Exception:
                                pass

                    # Extract Full Description Text
                    desc_elem = self.page.locator(
                        "div.jobs-description__content, "
                        "div#job-details, "
                        "article.jobs-description__container"
                    ).first
                    description = await desc_elem.inner_text() if await desc_elem.count() > 0 else ""

                    # Detect Apply Button (Easy Apply vs External)
                    easy_apply_btn = self.page.locator(
                        "button.jobs-apply-button:has-text('Easy Apply'), "
                        "button:has-text('Easy Apply')"
                    ).first
                    is_easy_apply = (await easy_apply_btn.count() > 0) and (await easy_apply_btn.is_visible())

                    job_url = self.page.url
                    job_key = f"{title.strip()}_{company.strip()}"
                    if job_key in seen_job_ids or len(description.strip()) < 50:
                        continue

                    seen_job_ids.add(job_key)
                    harvested_count += 1

                    job_payload = {
                        "job_title": title.strip().replace("\n", " "),
                        "company": company.strip().replace("\n", " "),
                        "location": location.strip(),
                        "description": description.strip(),
                        "is_easy_apply": is_easy_apply,
                        "job_url": job_url,
                        "keyword": keyword,
                        "index": idx,
                    }

                    logger.info(f"✨ [Agent 1] Harvested [{harvested_count}/{max_jobs}] '{job_payload['job_title']}' @ {job_payload['company']} (Easy Apply: {is_easy_apply})")
                    yield job_payload

                except Exception as card_err:
                    logger.debug(f"[Agent 1] Skipping card {idx} due to error: {card_err}")
                    continue

        except Exception as e:
            logger.error(f"[Agent 1] Search and harvest error for '{keyword}': {e}")
