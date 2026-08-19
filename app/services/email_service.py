"""
Email Service — drafts cold outreach emails using Claude and sends via Gmail OAuth2.

Flow:
  1. Claude drafts a personalized cold email for the job
  2. Gmail OAuth2 sends the email (if recruiter email is available)
  3. Application record updated with email_sent=True
"""
import base64
import json
import logging
import sys
from typing import Optional

import anthropic
import httpx

from app.config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    EMAIL_ADDRESS,
    GMAIL_CLIENT_ID,
    GMAIL_CLIENT_SECRET,
    GMAIL_REFRESH_TOKEN,
    DRY_RUN,
    CANDIDATE_NAME,
)
from app.prompts.email_prompt import (
    EMAIL_DRAFTING_SYSTEM_PROMPT,
    build_email_user_prompt,
)


def _make_anthropic_client():
    if sys.platform == "win32":
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client(verify=False))
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

logger = logging.getLogger(__name__)

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class EmailService:
    """
    Drafts personalized cold emails with Claude and sends via Gmail API.
    """

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.client = _make_anthropic_client()
        self.model = CLAUDE_MODEL
        self._access_token: Optional[str] = None

    # ── Draft ──────────────────────────────────────────────────────

    def draft_email(
        self,
        job_title: str,
        company: str,
        job_description: str,
        resume_text: str,
        match_score: int,
        recruiter_name: Optional[str] = None,
    ) -> dict:
        """
        Use Claude to draft a cold outreach email.

        Returns: {"subject": str, "body": str, "follow_up_day": int}
        """
        user_prompt = build_email_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            recruiter_name=recruiter_name,
            resume_text=resume_text,
            match_score=match_score,
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=EMAIL_DRAFTING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            content = message.content[0].text.strip()

            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            draft = json.loads(content)
            logger.info(f"✅ Email drafted for '{job_title}' @ {company}")
            return draft

        except Exception as e:
            logger.error(f"❌ Email draft failed: {e}")
            return {
                "subject": f"Application: {job_title} at {company}",
                "body": f"Hi,\n\nI'm {CANDIDATE_NAME} and I'm interested in the {job_title} role at {company}.\n\nBest regards,\n{CANDIDATE_NAME}",
                "follow_up_day": 7,
            }

    # ── Gmail OAuth ────────────────────────────────────────────────

    def _get_access_token(self) -> Optional[str]:
        """Get fresh Gmail access token using refresh token."""
        if not GMAIL_REFRESH_TOKEN:
            logger.warning("GMAIL_REFRESH_TOKEN not set — email sending disabled")
            return None

        try:
            import httpx as _httpx
            response = _httpx.post(
                GMAIL_TOKEN_URL,
                data={
                    "client_id": GMAIL_CLIENT_ID,
                    "client_secret": GMAIL_CLIENT_SECRET,
                    "refresh_token": GMAIL_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            self._access_token = response.json()["access_token"]
            return self._access_token

        except Exception as e:
            logger.error(f"❌ Gmail token refresh failed: {e}")
            return None

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        pdf_attachment_path: Optional[str] = None,
    ) -> bool:
        """
        Send email via Gmail API with optional PDF attachment.
        Returns True if sent successfully (or DRY_RUN mode).
        """
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would send email to {to_email}: '{subject}'")
            return True

        if not EMAIL_ADDRESS:
            logger.warning("EMAIL_ADDRESS not set — skipping send")
            return False

        access_token = self._get_access_token()
        if not access_token:
            return False

        try:
            # Build MIME message
            msg = MIMEMultipart()
            msg["From"] = f"{CANDIDATE_NAME} <{EMAIL_ADDRESS}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            # Attach PDF if provided
            if pdf_attachment_path:
                from email.mime.base import MIMEBase
                from email import encoders
                with open(pdf_attachment_path, "rb") as f:
                    part = MIMEBase("application", "pdf")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    import os
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(pdf_attachment_path)}",
                    )
                    msg.attach(part)

            # Encode as base64 for Gmail API
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

            import httpx as _httpx
            response = _httpx.post(
                GMAIL_SEND_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw},
            )
            response.raise_for_status()
            logger.info(f"📧 Email sent to {to_email}: '{subject}'")
            return True

        except Exception as e:
            logger.error(f"❌ Email send failed to {to_email}: {e}")
            return False
