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
    GEMINI_API_KEY,
    GEMINI_MODEL,
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    CLAUDE_MODEL,
    LLM_PROVIDER,
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
from app.utils.gemini_client import GeminiClient, get_gemini_client

logger = logging.getLogger(__name__)

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SSL_VERIFY = False if sys.platform == "win32" else True


def _make_anthropic_client():
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize Anthropic client: {e}")
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
    job_description: str = "",
) -> dict:
    """Professional fallback template when LLMs are unavailable, strictly aligned with 0-2 yrs candidate profile."""
    greeting = f"Dear {recruiter_name}," if recruiter_name else "Dear Hiring Manager,"
    subject = f"Application: {job_title} at {company}"

    jd_lower = (job_description or "").lower()
    bullets = []
    
    # Select highlights matching JD keywords
    if any(k in jd_lower for k in ["java", "spring", "microservice", "backend"]):
        bullets.append("- Java 17/21, Spring Boot 3, Microservices architecture, Spring Cloud, Hibernate/JPA")
    if any(k in jd_lower for k in ["python", "fastapi", "django", "flask", "api"]):
        bullets.append("- Python, FastAPI, RESTful API design, Postman, Swagger/OpenAPI")
    if any(k in jd_lower for k in ["aws", "cloud", "s3", "lambda", "ecs", "ec2"]):
        bullets.append("- AWS Cloud services (EC2, ECS, Lambda, S3, RDS PostgreSQL, SQS, SNS)")
    if any(k in jd_lower for k in ["docker", "kubernetes", "k8s", "ci/cd", "devops", "sre"]):
        bullets.append("- Docker containerization, Kubernetes orchestration, CI/CD pipeline automation")
    if any(k in jd_lower for k in ["ai", "ml", "langchain", "llm", "agent", "rag"]):
        bullets.append("- Generative AI integration, LangGraph / LangChain agent orchestration")

    # Fallback to default core tech if no specific match
    if not bullets:
        bullets = [
            "- Java, Spring Boot, Microservices architecture, REST APIs",
            "- Python, FastAPI, PostgreSQL, SQL database optimization",
            "- AWS Cloud services, Docker, CI/CD pipelines",
            "- Applied AI agent development (LangChain / LangGraph)",
        ]

    bullets_text = "\n".join(bullets)

    body = f"""{greeting}

I am writing to express my strong interest in the {job_title} position at {company}.

I am an early-career Backend & Software Engineer with 1+ years of hands-on experience building scalable microservices, REST APIs, and modern backend systems. My core technical background includes:

{bullets_text}

I am excited about {company}'s work and confident that my practical skills in backend engineering and cloud deployments align well with the requirements for the {job_title} role.

I have attached my tailored ATS resume for your review. I would welcome the opportunity to discuss how my technical skills can add immediate value to your engineering team.

Thank you for your time and consideration.

Best regards,
{CANDIDATE_NAME}
kamalkumar.doddi@gmail.com
+91 6304883114
"""
    return {
        "subject": subject,
        "body": body,
        "follow_up_day": 7,
        "_source": "template",
    }


class EmailService:
    """
    Drafts personalized cold emails via Gemini → Claude → OpenAI → Template.
    Sends via Gmail OAuth2 API.
    """

    def __init__(self):
        self._gemini = get_gemini_client()
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
        Draft a cold outreach email. Cascade: Gemini → Claude → OpenAI → Template.
        """
        user_prompt = build_email_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            recruiter_name=recruiter_name,
            resume_text=resume_text,
            match_score=match_score,
        )

        pref = LLM_PROVIDER.lower()
        if pref == "gemini":
            providers = ["gemini"]
        elif pref == "claude":
            providers = ["claude"]
        elif pref == "openai":
            providers = ["openai"]
        else:
            providers = ["gemini", "claude", "openai"]

        for provider in providers:
            if provider == "gemini" and self._gemini:
                try:
                    resp_text = self._gemini.generate_content(
                        prompt=user_prompt,
                        system_instruction=EMAIL_DRAFTING_SYSTEM_PROMPT,
                        json_mode=True,
                        max_output_tokens=1024,
                    )
                    if resp_text:
                        draft = self._parse_llm_response(resp_text)
                        if draft:
                            draft["_source"] = f"gemini ({self._gemini.model})"
                            logger.info(f"[Gemini] Email drafted for '{job_title}' @ {company}")
                            return draft
                except Exception as e:
                    logger.warning(f"[Gemini] Email draft failed: {e}")

            elif provider == "claude" and self._claude:
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

            elif provider == "openai" and self._openai:
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

        # Fallback template
        logger.info(f"[Template] Using fallback email for '{job_title}' @ {company}")
        return _template_email(
            job_title=job_title,
            company=company,
            match_score=match_score,
            recruiter_name=recruiter_name,
            job_description=job_description,
        )

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
        attachment_path: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Send email via Gmail API with optional PDF / Excel attachment."""
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

            attachment = attachment_path or pdf_attachment_path or kwargs.get("attachment_path")
            if attachment and os.path.exists(attachment):
                filename = os.path.basename(attachment)
                maintype = "application"
                subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet" if filename.endswith((".xlsx", ".xls")) else "pdf"
                with open(attachment, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{filename}"',
                    )
                    msg.attach(part)
                    logger.info(f"Attached {filename} ({subtype}) to email")

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
