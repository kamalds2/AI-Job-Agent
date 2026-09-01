"""
Apply Service — Orchestrates application routing and dispatch.

Two Streams:
  1. Recruiter Posts with Real Email: Sends personalized cold email with tailored ATS resume attached via Gmail API.
  2. Normal Job Board Listings: Prepares direct application link, tailored ATS resume, and customized cover note for 1-click apply in Excel.
"""
import logging
import os
from typing import Optional

from app.config.settings import (
    CANDIDATE_NAME,
    EMAIL_ADDRESS,
    DRY_RUN,
)
from app.services.application_policy import (
    determine_application_strategy,
    ApplicationMode,
    ApplicationStatus,
)
from app.utils.email_validator import generate_hr_email_candidates

logger = logging.getLogger(__name__)


def guess_hr_email(company_name: str, job_url: str, jd_text: str = "") -> list[str]:
    """Extract explicit recruiter emails from job description / post."""
    return generate_hr_email_candidates(company_name, job_url, jd_text)


class ApplyService:
    """Handles qualified job application routing and link preparation."""

    async def apply_to_job(
        self,
        job_url: str,
        company_name: str,
        job_title: str,
        cover_letter: str = "",
        resume_pdf_path: Optional[str] = None,
        score: int = 85,
        hr_email: Optional[str] = None,
    ) -> dict:
        """
        Route qualified job to either Recruiter Email outreach or Direct Application Link prep.
        """
        status, mode, reason = determine_application_strategy(score, job_url, company_name, hr_email)
        logger.info(f"📋 [Application Router] '{job_title}' @ {company_name} [{score}/100]: Mode={mode.value} | {reason}")

        if status == ApplicationStatus.SKIPPED:
            return {
                "success": False,
                "method": "skipped",
                "message": f"Score {score} < 65: {reason}",
                "status": status.value,
            }

        # Stream A: Recruiter Email Outreach (Handled by email dispatch in node)
        if mode == ApplicationMode.EMAIL_HR:
            return {
                "success": True,
                "method": "recruiter_email",
                "message": f"Ready for email outreach to: {hr_email}",
                "status": status.value,
                "hr_email": hr_email,
            }

        # Stream B: Direct Application Link Preparation (No direct form botting on job boards)
        return {
            "success": True,
            "method": "direct_application_link",
            "message": f"Direct link & tailored ATS resume prepared: {job_url}",
            "status": status.value,
            "job_url": job_url,
            "resume_path": resume_pdf_path,
        }

    # Alias for node compatibility
    apply = apply_to_job
