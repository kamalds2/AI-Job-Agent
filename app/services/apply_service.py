"""
Auto-Apply Service — submits applications directly to job boards.

Supported boards:
  1. Greenhouse  — POST https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}/apply
  2. Lever       — POST https://api.lever.co/v0/postings/{postingId}/apply
  3. Ashby       — POST https://api.ashbyhq.com/applicationForm.submit
  4. Email/HR    — Sends cold email to guessed HR email (careers@company.com etc.)

Each method returns:
  {"success": bool, "method": str, "message": str}
"""
import logging
import os
import re
import sys
import base64
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config.settings import (
    CANDIDATE_NAME,
    EMAIL_ADDRESS,
    DRY_RUN,
)

logger = logging.getLogger(__name__)

SSL_VERIFY = False if sys.platform == "win32" else True

# ── Candidate details (from settings / env) ──────────────────
CANDIDATE_PHONE = os.getenv("CANDIDATE_PHONE", "+919630488311")
CANDIDATE_LINKEDIN = os.getenv("CANDIDATE_LINKEDIN", "https://linkedin.com/in/kamal-kumar-doddi")
CANDIDATE_GITHUB = os.getenv("CANDIDATE_GITHUB", "https://github.com/kamalds2")

# HR email patterns to try for cold outreach
HR_EMAIL_PATTERNS = [
    "careers@{domain}",
    "jobs@{domain}",
    "talent@{domain}",
    "hiring@{domain}",
    "hr@{domain}",
    "recruiting@{domain}",
    "recruit@{domain}",
]


def extract_greenhouse_info(job_url: str) -> Optional[dict]:
    """Extract company slug and job ID from a Greenhouse URL."""
    # Pattern: greenhouse.io/{company}/jobs/{job_id}
    m = re.search(r"greenhouse\.io/([a-z0-9_-]+)/jobs/(\d+)", job_url.lower())
    if m:
        return {"company": m.group(1), "job_id": m.group(2)}

    # Pattern: stripe.com/jobs/search?gh_jid={job_id}
    # For Stripe specifically — they use Greenhouse internally
    stripe_m = re.search(r"stripe\.com/jobs.*gh_jid=(\d+)", job_url)
    if stripe_m:
        return {"company": "stripe", "job_id": stripe_m.group(1)}

    # Pattern: careers.airbnb.com/positions/{id}?gh_jid={job_id}
    airbnb_m = re.search(r"airbnb\.com/positions/\d+\?gh_jid=(\d+)", job_url)
    if airbnb_m:
        return {"company": "airbnb", "job_id": airbnb_m.group(1)}

    # Generic: any domain with ?gh_jid=
    generic_m = re.search(r"gh_jid=(\d+)", job_url)
    if generic_m:
        domain_m = re.search(r"https?://(?:www\.)?([a-z0-9_-]+)\.", job_url)
        if domain_m:
            return {"company": domain_m.group(1), "job_id": generic_m.group(1)}

    return None


def extract_lever_posting_id(job_url: str) -> Optional[str]:
    """Extract Lever posting ID from URL."""
    # Pattern: jobs.lever.co/{company}/{posting_id}
    m = re.search(r"lever\.co/[^/]+/([a-f0-9-]+)", job_url.lower())
    if m:
        posting_id = m.group(1).split("?")[0].split("/")[0]
        return posting_id
    return None


def extract_ashby_info(job_url: str) -> Optional[dict]:
    """Extract Ashby company slug and job ID."""
    # Pattern: jobs.ashbyhq.com/{company}/{job_id}
    m = re.search(r"ashbyhq\.com/([^/?#]+)/([a-f0-9-]+)", job_url.lower())
    if m:
        return {"company": m.group(1), "job_id": m.group(2)}
    return None


ATS_DOMAINS = {
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "remoteok.com",
    "weworkremotely.com",
    "arbeitnow.com",
    "himalayas.app",
    "naukri.com",
    "adzuna.com",
    "ycombinator.com",
    "recruitee.com",
    "smartrecruiters.com",
    "bamboohr.com",
    "jobvite.com",
}


from app.utils.email_validator import (
    generate_hr_email_candidates,
    extract_emails_from_text,
    domain_has_valid_dns,
)

def guess_hr_email(company_name: str, job_url: str, jd_text: str = "") -> list[str]:
    """
    Generate candidate HR email addresses for a company (hr@, careers@ across .com, .in, .co, .ai)
    with DNS validation and explicit email extraction from JD.
    """
    return generate_hr_email_candidates(company_name, job_url, jd_text)


class ApplyService:
    """
    Submits job applications directly to job boards.
    Cascade: Greenhouse API → Lever API → Ashby API → Email to HR
    """

    def __init__(self):
        self.client_kwargs = {
            "verify": SSL_VERIFY,
            "timeout": 20,
            "follow_redirects": True,
        }

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
        Apply to job based on Source-Aware Application Strategy & Match Score Policy.
        Returns: {"success": bool, "method": str, "message": str}
        """
        from app.services.application_policy import determine_application_strategy, ApplicationStatus, ApplicationMode

        status, mode, reason = determine_application_strategy(score, job_url, company_name, hr_email)
        logger.info(f"📋 [Apply Engine] Strategy for '{job_title}' @ {company_name} [{score}/100]: Mode={mode.value}, Status={status.value} ({reason})")

        if DRY_RUN:
            logger.info(f"[DRY RUN] Would apply to: {job_title} @ {company_name}")
            return {
                "success": True,
                "method": "dry_run",
                "message": f"DRY RUN: Would apply to {job_title} @ {company_name}",
            }

        # If manual review mode (e.g. anti-bot portal Hirist/Shine or score 65-74), return prepared link
        if status in (ApplicationStatus.REVIEW_REQUIRED, ApplicationStatus.SAVE_LINK, ApplicationStatus.SKIPPED) and mode == ApplicationMode.MANUAL_LINK:
            return {
                "success": False,
                "method": "manual_review_link",
                "message": f"Prepared for 1-click review at: {job_url}",
                "status": status.value,
            }

        # Mode 1: Direct ATS API Submit (Greenhouse, Lever, Ashby)
        if mode == ApplicationMode.DIRECT_API:
            gh_info = extract_greenhouse_info(job_url)
            if gh_info:
                result = await self._apply_greenhouse(gh_info["company"], gh_info["job_id"], job_title, cover_letter, resume_pdf_path)
                if result["success"]:
                    return result

            lever_id = extract_lever_posting_id(job_url)
            if lever_id:
                result = await self._apply_lever(lever_id, job_title, cover_letter, resume_pdf_path)
                if result["success"]:
                    return result

            ashby_info = extract_ashby_info(job_url)
            if ashby_info:
                result = await self._apply_ashby(ashby_info["company"], ashby_info["job_id"], job_title, cover_letter, resume_pdf_path)
                if result["success"]:
                    return result

        # Mode 2: Persistent Playwright Browser Auto-Apply (Reuses saved browser session for Wellfound/YC/LinkedIn/Jobicy)
        if mode in (ApplicationMode.PERSISTENT_BROWSER, ApplicationMode.DIRECT_API):
            try:
                from app.services.browser_apply_service import BrowserApplyService
                browser_service = BrowserApplyService(headless=True)
                browser_result = await browser_service.apply(
                    job_url=job_url,
                    job_title=job_title,
                    company_name=company_name,
                    resume_pdf_path=resume_pdf_path or "",
                    cover_letter=cover_letter,
                )
                if browser_result.get("success"):
                    return browser_result
            except Exception as be:
                logger.debug(f"[Apply] Playwright browser apply skipped: {be}")

        # Fallback: Record job URL for manual application link review
        logger.warning(
            f"[Apply] Direct automation unavailable for {job_url[:60]} — "
            f"1-click review link prepared at: {job_url}"
        )
        return {
            "success": False,
            "method": "manual_review_prepared",
            "message": f"Application link prepared: {job_url}",
        }

    # Alias for orchestrator node compatibility
    apply = apply_to_job

    async def _apply_greenhouse(
        self,
        company: str,
        job_id: str,
        job_title: str,
        cover_letter: str,
        resume_pdf_path: Optional[str] = None,
    ) -> dict:
        """Submit application via Greenhouse Job Board API."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"

        try:
            async with httpx.AsyncClient(**self.client_kwargs) as client:
                # First, verify the job exists
                check = await client.get(url)
                if check.status_code == 404:
                    return {"success": False, "method": "greenhouse", "message": "Job not found"}

                job_data = check.json()
                questions = job_data.get("questions", [])

                # Build form fields from questions
                form_data = {
                    "first_name": CANDIDATE_NAME.split()[0],
                    "last_name": " ".join(CANDIDATE_NAME.split()[1:]) or ".",
                    "email": EMAIL_ADDRESS,
                    "phone": CANDIDATE_PHONE,
                    "cover_letter": cover_letter,
                    "website": CANDIDATE_LINKEDIN,
                }

                # Add answers to required questions
                for q in questions:
                    qid = str(q.get("id", ""))
                    label = q.get("label", "").lower()
                    required = q.get("required", False)

                    if "linkedin" in label:
                        form_data[f"question_{qid}"] = CANDIDATE_LINKEDIN
                    elif "github" in label or "portfolio" in label:
                        form_data[f"question_{qid}"] = CANDIDATE_GITHUB
                    elif "website" in label or "url" in label:
                        form_data[f"question_{qid}"] = CANDIDATE_LINKEDIN
                    elif required and qid:
                        form_data[f"question_{qid}"] = "Yes"  # Default for checkboxes

                # Attach resume
                apply_url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    with open(resume_pdf_path, "rb") as f:
                        resume_b64 = base64.b64encode(f.read()).decode()
                    form_data["resume_content"] = resume_b64
                    form_data["resume_content_filename"] = os.path.basename(resume_pdf_path)

                resp = await client.post(apply_url, json=form_data)

                if resp.status_code in (200, 201):
                    logger.info(f"[Greenhouse] Applied to {job_title} @ {company}")
                    return {
                        "success": True,
                        "method": "greenhouse_api",
                        "message": f"Applied via Greenhouse API to {company}/{job_id}",
                    }
                else:
                    msg = resp.text[:200]
                    logger.warning(f"[Greenhouse] Apply failed {resp.status_code}: {msg}")
                    return {
                        "success": False,
                        "method": "greenhouse",
                        "message": f"HTTP {resp.status_code}: {msg}",
                    }

        except Exception as e:
            logger.warning(f"[Greenhouse] Apply error: {e}")
            return {"success": False, "method": "greenhouse", "message": str(e)}

    async def _apply_lever(
        self,
        posting_id: str,
        job_title: str,
        cover_letter: str,
        resume_pdf_path: Optional[str] = None,
    ) -> dict:
        """Submit application via Lever public posting API."""
        apply_url = f"https://api.lever.co/v0/postings/{posting_id}/apply"

        try:
            async with httpx.AsyncClient(**self.client_kwargs) as client:
                files = {}
                data = {
                    "name": CANDIDATE_NAME,
                    "email": EMAIL_ADDRESS,
                    "phone": CANDIDATE_PHONE,
                    "comments": cover_letter[:2000],
                    "website": CANDIDATE_LINKEDIN,
                    "org": "Self",
                }

                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    with open(resume_pdf_path, "rb") as f:
                        resume_bytes = f.read()
                    files["resume"] = (
                        os.path.basename(resume_pdf_path),
                        resume_bytes,
                        "application/pdf",
                    )
                    resp = await client.post(apply_url, data=data, files=files)
                else:
                    resp = await client.post(apply_url, data=data)

                if resp.status_code in (200, 201):
                    logger.info(f"[Lever] Applied to posting {posting_id}")
                    return {
                        "success": True,
                        "method": "lever_api",
                        "message": f"Applied via Lever API to posting {posting_id}",
                    }
                else:
                    logger.warning(f"[Lever] Apply failed {resp.status_code}: {resp.text[:200]}")
                    return {
                        "success": False,
                        "method": "lever",
                        "message": f"HTTP {resp.status_code}",
                    }

        except Exception as e:
            logger.warning(f"[Lever] Apply error: {e}")
            return {"success": False, "method": "lever", "message": str(e)}

    async def _apply_ashby(
        self,
        company: str,
        job_id: str,
        job_title: str,
        cover_letter: str,
        resume_pdf_path: Optional[str] = None,
    ) -> dict:
        """Submit application via Ashby form API."""
        try:
            async with httpx.AsyncClient(**self.client_kwargs) as client:
                # Get the application form definition
                form_url = f"https://api.ashbyhq.com/applicationForm.getForPosting"
                form_resp = await client.post(
                    form_url,
                    json={"jobPostingId": job_id},
                )

                if form_resp.status_code != 200:
                    return {
                        "success": False,
                        "method": "ashby",
                        "message": f"Form fetch failed: HTTP {form_resp.status_code}",
                    }

                form_data = form_resp.json()
                form_def = form_data.get("results", {})
                field_submissions = []

                # Map standard fields
                for field in form_def.get("fieldDefinitions", []):
                    fid = field.get("id", "")
                    label = field.get("label", "").lower()

                    if "name" in label and "first" in label:
                        field_submissions.append({"path": fid, "value": CANDIDATE_NAME.split()[0]})
                    elif "name" in label and "last" in label:
                        field_submissions.append({"path": fid, "value": " ".join(CANDIDATE_NAME.split()[1:])})
                    elif "email" in label:
                        field_submissions.append({"path": fid, "value": EMAIL_ADDRESS})
                    elif "phone" in label:
                        field_submissions.append({"path": fid, "value": CANDIDATE_PHONE})
                    elif "linkedin" in label:
                        field_submissions.append({"path": fid, "value": CANDIDATE_LINKEDIN})
                    elif "cover" in label or "letter" in label:
                        field_submissions.append({"path": fid, "value": cover_letter[:2000]})

                # Submit
                submit_payload = {
                    "jobPostingId": job_id,
                    "fieldSubmissions": field_submissions,
                    "source": "Job Board",
                }

                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    with open(resume_pdf_path, "rb") as f:
                        submit_payload["resumeContent"] = base64.b64encode(f.read()).decode()
                        submit_payload["resumeFileName"] = os.path.basename(resume_pdf_path)

                submit_resp = await client.post(
                    "https://api.ashbyhq.com/applicationForm.submit",
                    json=submit_payload,
                )

                if submit_resp.status_code in (200, 201):
                    logger.info(f"[Ashby] Applied to {company}/{job_id}")
                    return {
                        "success": True,
                        "method": "ashby_api",
                        "message": f"Applied via Ashby API",
                    }
                else:
                    return {
                        "success": False,
                        "method": "ashby",
                        "message": f"HTTP {submit_resp.status_code}",
                    }

        except Exception as e:
            logger.warning(f"[Ashby] Apply error: {e}")
            return {"success": False, "method": "ashby", "message": str(e)}
