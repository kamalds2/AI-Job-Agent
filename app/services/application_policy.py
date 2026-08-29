"""
Application Policy Manager — Source-Aware Application Strategy & Lifecycle Rules.

Application Modes:
  🟢 DIRECT_API        — Programmatic ATS API submit (Greenhouse, Lever, Ashby)
  🟡 PERSISTENT_BROWSER — Playwright using saved browser session (Wellfound, YC, LinkedIn, Workday)
  ✉️ EMAIL_HR          — Cold email outreach to verified HR emails (careers@company.com)
  🔴 MANUAL_LINK       — 1-Click application link prep for anti-bot portals (Hirist, Shine, Cutshort)

Match Score Policy:
  Score >= 85 : AUTO_APPLY (Direct submission via supported mode)
  Score 75-84 : REVIEW_REQUIRED (Tailored resume PDF + application draft for 1-click review)
  Score 65-74 : SAVE_LINK (Save job details & link for manual review)
  Score < 65  : SKIP
"""
import logging
from enum import Enum
from typing import Tuple, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ApplicationMode(str, Enum):
    DIRECT_API = "direct_api"
    PERSISTENT_BROWSER = "persistent_browser"
    EMAIL_HR = "email_hr"
    MANUAL_LINK = "manual_link"


class ApplicationStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    MATCHED = "MATCHED"
    READY = "READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUBMITTED = "SUBMITTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    SAVE_LINK = "SAVE_LINK"


# Mapping of domains/sources to application modes & anti-bot policies
DIRECT_API_DOMAINS = {"greenhouse.io", "lever.co", "ashbyhq.com"}
PERSISTENT_BROWSER_DOMAINS = {
    "wellfound.com", "ycombinator.com", "linkedin.com", "workday.com",
    "jobicy.com", "remotive.com", "adzuna.in", "adzuna.com"
}
MANUAL_ONLY_DOMAINS = {"hirist.tech", "shine.com", "cutshort.io", "foundit.in", "naukri.com"}


def get_application_mode(job_url: str, source: str, hr_email: Optional[str] = None) -> ApplicationMode:
    """Determine the optimal application mode based on source policies."""
    if hr_email:
        return ApplicationMode.EMAIL_HR

    url_lower = (job_url or "").lower()

    # Check direct API ATS domains
    for domain in DIRECT_API_DOMAINS:
        if domain in url_lower:
            return ApplicationMode.DIRECT_API

    # Check anti-bot restricted portals (require manual link prep)
    for domain in MANUAL_ONLY_DOMAINS:
        if domain in url_lower:
            return ApplicationMode.MANUAL_LINK

    # Check browser-assisted portals
    for domain in PERSISTENT_BROWSER_DOMAINS:
        if domain in url_lower:
            return ApplicationMode.PERSISTENT_BROWSER

    # Default fallback: try persistent browser first, then HR email
    return ApplicationMode.PERSISTENT_BROWSER


def determine_application_strategy(
    score: int,
    job_url: str,
    source: str,
    hr_email: Optional[str] = None,
) -> Tuple[ApplicationStatus, ApplicationMode, str]:
    """
    Determine application lifecycle status and execution mode based on match score and source capabilities.
    """
    mode = get_application_mode(job_url, source, hr_email)

    if score < 65:
        return ApplicationStatus.SKIPPED, mode, f"Score {score}/100 below 65 threshold"

    if 65 <= score < 75:
        return ApplicationStatus.SAVE_LINK, ApplicationMode.MANUAL_LINK, f"Score {score}/100 saved for 1-click manual review"

    if 75 <= score < 85:
        return ApplicationStatus.REVIEW_REQUIRED, mode, f"Score {score}/100 prepared for 1-click user review"

    # score >= 85
    return ApplicationStatus.READY, mode, f"Score {score}/100 approved for auto-apply"
