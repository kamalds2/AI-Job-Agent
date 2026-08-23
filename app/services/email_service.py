"""
Email Service — drafts cold outreach emails using Claude → OpenAI → Template fallback.

Flow:
  1. Try Claude to draft personalized email
  2. Try OpenAI gpt-4o-mini if Claude fails
  3. Use professional template fallback if both LLMs fail
  4. Gmail OAuth2 sends the email with tailored resume attached
"""
import base64
import json
import logging
import sys
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from typing import Optional
import os

import httpx

from app.config.settings import (
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
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

logger = logging.getLogger(__name__)

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SSL_VERIFY = False if sys.platform == "win32" else True


def _make_anthropic_client():
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            http_client=httpx.Client(verify=False) if sys.platform == "win32" else None,
        )
    except ImportError:
        return None


def _make_openai_client():
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        return openai.OpenAI(
            api_key=OPENAI_API_KEY,
            http_client=httpx.Client(verify=False) if sys.platform == "win32" else None,
        )
    except ImportError:
        return None


def _template_email(
    job_title: str,
    company: str,
    match_score: int,
    recruiter_name: Optional[str] = None,
) -> dict:
    """Professional fallback template when LLMs are unavailable."""
    greeting = f"Dear {recruiter_name}," if recruiter_name else "Dear Hiring Manager,"
    subject = f"Application: {job_title} at {company}"
    body = f"""{greeting}

I am writing to express my strong interest in the {job_title} position at {company}.

I am a Java/Spring Boot backend engineer with 5+ years of experience building scalable microservices on AWS. My background includes:

- Java, Spring Boot, Spring Cloud, Microservices architecture
- AWS (EC2, ECS, Lambda, RDS, SQS, SNS, S3)
- Python, FastAPI, REST APIs, GraphQL
- Kubernetes, Docker, Terraform, CI/CD pipelines
- AI/ML integration and LangChain/LangGraph agent development

I am particularly excited about {company}'s mission and believe my experience aligns well with the {job_title} role (match score: {match_score}/100).

I have attached my tailored resume for your review. I would welcome the opportunity to discuss how my skills can contribute to your team.

Thank you for your time and consideration.

Best regards,
{CANDIDATE_NAME}
kamalkumar.doddi@gmail.com
"""
    return {
        "subject": subject,
        "body": body,
        "follow_up_day": 7,
        "_source": "template",
    }


class EmailService:
    """
    Drafts personalized cold emails via Claude → OpenAI → Template.
    Sends via Gmail OAuth2 API.
    """

    def __init__(self):
        self._claude = _make_anthropic_client()
        self._openai = _make_openai_client()
        self._access_token: Optional[str] = None

    # ── Draft email ────────────────────────────────────────────────

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
        Draft a cold outreach email. Cascade: Claude → OpenAI → Template.
        """
        user_prompt = build_email_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            recruiter_name=recruiter_name,
            resume_text=resume_text,
            match_score=match_score,
        )

        # 1. Try Claude
        if self._claude:
            try:
                msg = self._claude.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=1024,
                    system=EMAIL_DRAFTING_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                draft = self._parse_llm_response(msg.content[0].text)
                if draft:
                    draft["_source"] = "claude"
                    logger.info(f"[Claude] Email drafted for '{job_title}' @ {company}")
                    return draft
            except Exception as e:
                logger.warning(f"[Claude] Email draft failed: {e}")

        # 2. Try OpenAI
        if self._openai:
            try:
                resp = self._openai.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": EMAIL_DRAFTING_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                draft = self._parse_llm_response(resp.choices[0].message.content)
                if draft:
                    draft["_source"] = "openai"
                    logger.info(f"[OpenAI] Email drafted for '{job_title}' @ {company}")
                    return draft
            except Exception as e:
                logger.warning(f"[OpenAI] Email draft failed: {e}")

        # 3. Professional template fallback
        logger.info(f"[Template] Using fallback email for '{job_title}' @ {company}")
        return _template_email(job_title, company, match_score, recruiter_name)

    def _parse_llm_response(self, content: str) -> Optional[dict]:
        """Parse JSON from LLM response, handling markdown fences."""
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
        except Exception:
            return None

    # ── Gmail OAuth ────────────────────────────────────────────────

    def _get_access_token(self) -> Optional[str]:
        """Get fresh Gmail access token using refresh token."""
        if not GMAIL_REFRESH_TOKEN:
            logger.warning("GMAIL_REFRESH_TOKEN not set — email sending disabled")
            return None
        try:
            resp = httpx.post(
                GMAIL_TOKEN_URL,
                data={
                    "client_id": GMAIL_CLIENT_ID,
                    "client_secret": GMAIL_CLIENT_SECRET,
                    "refresh_token": GMAIL_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
                verify=SSL_VERIFY,
            )
            resp.raise_for_status()
            self._access_token = resp.json()["access_token"]
            return self._access_token
        except Exception as e:
            logger.error(f"Gmail token refresh failed: {e}")
            return None

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        pdf_attachment_path: Optional[str] = None,
    ) -> bool:
        """Send email via Gmail API with optional PDF attachment."""
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
            msg = MIMEMultipart()
            msg["From"] = f"{CANDIDATE_NAME} <{EMAIL_ADDRESS}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            if pdf_attachment_path and os.path.exists(pdf_attachment_path):
                with open(pdf_attachment_path, "rb") as f:
                    part = MIMEBase("application", "pdf")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(pdf_attachment_path)}",
                    )
                    msg.attach(part)

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            resp = httpx.post(
                GMAIL_SEND_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw},
                verify=SSL_VERIFY,
            )
            resp.raise_for_status()
            logger.info(f"Email sent to {to_email}: '{subject}'")
            return True

        except Exception as e:
            logger.error(f"Email send failed to {to_email}: {e}")
            return False
