"""
Application Strategy & Policy Engine.
Routes qualified jobs into two clean streams:
  1. RECRUITER EMAIL (Verified HR/Recruiter Outreach via Gmail API)
  2. APPLICATION LINK (Direct Job Board / Portal Link Preparation + Tailored ATS Resume in Excel)
"""
import logging
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ApplicationMode(str, Enum):
    EMAIL_HR = "EMAIL_HR"          # Recruiter hiring post with real verified email -> Send tailored email & resume
    APPLY_LINK = "APPLY_LINK"      # Job board / portal listing -> 1-Click direct link + tailored ATS resume prep


class ApplicationStatus(str, Enum):
    EMAIL_SENT = "EMAIL_SENT"
    LINK_PREPARED = "LINK_PREPARED"
    SKIPPED = "SKIPPED"


def determine_application_strategy(
    match_score: int,
    job_url: str,
    company_name: str,
    hr_email: Optional[str] = None,
) -> Tuple[ApplicationStatus, ApplicationMode, str]:
    """
    Classify application mode and status based on score and contact availability.
    """
    if match_score < 65:
        return ApplicationStatus.SKIPPED, ApplicationMode.APPLY_LINK, f"Match score {match_score} below threshold (65)"

    # If explicit recruiter/HR email is present -> Mode 1: Recruiter Email Outreach
    if hr_email and "@" in hr_email:
        return (
            ApplicationStatus.EMAIL_SENT,
            ApplicationMode.EMAIL_HR,
            f"Explicit recruiter email found ({hr_email}) -> Send personalized outreach",
        )

    # Otherwise -> Mode 2: Application Link Preparation (Excel + Tailored Resume)
    return (
        ApplicationStatus.LINK_PREPARED,
        ApplicationMode.APPLY_LINK,
        f"Job board / portal listing -> Prepare direct application link and tailored ATS resume",
    )
