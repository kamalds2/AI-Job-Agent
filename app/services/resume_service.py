"""
Resume Service — reads master resume + generates tailored versions using Claude.

Pipeline:
  1. Extract text from master PDF (using pymupdf)
  2. Claude tailors bullet points for specific job
  3. Generate tailored PDF (using reportlab)
  4. Save to resumes/ directory
"""
import json
import logging
import re
import sys
from pathlib import Path

import anthropic
import pymupdf as fitz  # PyMuPDF
import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

from app.config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    CLAUDE_MODEL,
    LLM_PROVIDER,
    MASTER_RESUME_PATH,
    RESUMES_DIR,
    CANDIDATE_NAME,
)
from app.prompts.resume_prompt import (
    RESUME_TAILORING_SYSTEM_PROMPT,
    build_resume_user_prompt,
)
from app.utils.gemini_client import GeminiClient, get_gemini_client

logger = logging.getLogger(__name__)


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
    """SSL-patched OpenAI client for Windows environments."""
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        if sys.platform == "win32":
            return openai.OpenAI(api_key=OPENAI_API_KEY, http_client=httpx.Client(verify=False))
        return openai.OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return None


def _clean_json_str(content: str) -> str:
    """Clean markdown JSON fences from LLM output."""
    if "```json" in content:
        return content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        return content.split("```")[1].split("```")[0].strip()
    return content.strip()


class ResumeService:
    """
    Reads master PDF resume and generates ATS-tailored versions per job.
    Falls back to master PDF if LLMs are unavailable.
    """

    def __init__(self):
        self.gemini_client = get_gemini_client()
        self.claude_client = _make_anthropic_client()
        self.openai_client = _make_openai_client()
        self.model = CLAUDE_MODEL
        self.master_path = Path(MASTER_RESUME_PATH)
        self.resumes_dir = Path(RESUMES_DIR)
        self.resumes_dir.mkdir(parents=True, exist_ok=True)

    def extract_resume_text(self) -> str:
        """Extract plain text from master resume PDF using PyMuPDF."""
        if not self.master_path.exists():
            raise FileNotFoundError(f"Master resume not found: {self.master_path}")

        doc = fitz.open(str(self.master_path))
        text_parts: list[str] = []

        for page in doc:
            text_parts.append(page.get_text())

        doc.close()
        full_text = "\n".join(text_parts)
        logger.info(f"📄 Extracted {len(full_text)} chars from master resume")
        return full_text

    def tailor_resume(
        self,
        job_id: int,
        job_title: str,
        company: str,
        job_description: str,
    ) -> dict:
        """
        Generate a tailored resume for a specific job using Gemini / Claude / OpenAI.

        Returns: Tailored resume data as dict
        """
        resume_text = self.extract_resume_text()

        user_prompt = build_resume_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            resume_text=resume_text,
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
            if provider == "gemini" and self.gemini_client:
                try:
                    resp_text = self.gemini_client.generate_content(
                        prompt=user_prompt,
                        system_instruction=RESUME_TAILORING_SYSTEM_PROMPT,
                        json_mode=True,
                        max_output_tokens=2048,
                    )
                    if resp_text:
                        clean_text = _clean_json_str(resp_text)
                        tailored_data = json.loads(clean_text)
                        logger.info(f"[Gemini] Tailored resume generated for '{job_title}' @ {company}")
                        return tailored_data
                except Exception as e:
                    logger.warning(f"[Gemini] Resume tailoring failed: {e}")

            elif provider == "claude" and self.claude_client:
                try:
                    message = self.claude_client.messages.create(
                        model=self.model,
                        max_tokens=2048,
                        system=RESUME_TAILORING_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": user_prompt}],
                    )
                    content = _clean_json_str(message.content[0].text)
                    tailored_data = json.loads(content)
                    logger.info(f"[Claude] Tailored resume generated for '{job_title}' @ {company}")
                    return tailored_data
                except Exception as e:
                    logger.warning(f"[Claude] Resume tailoring failed: {e}")

            elif provider == "openai" and self.openai_client:
                try:
                    resp = self.openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        max_tokens=2048,
                        messages=[
                            {"role": "system", "content": RESUME_TAILORING_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                    )
                    content = _clean_json_str(resp.choices[0].message.content)
                    tailored_data = json.loads(content)
                    logger.info(f"[OpenAI] Tailored resume generated for '{job_title}' @ {company}")
                    return tailored_data
                except Exception as e:
                    logger.warning(f"[OpenAI] Resume tailoring failed: {e}")

        return self._generate_fallback_tailored_data(job_title, company, job_description)

    def _generate_fallback_tailored_data(
        self,
        job_title: str,
        company: str,
        job_description: str,
    ) -> dict:
        """
        Extract key technical skills from job description and construct a customized
        ATS resume data payload specifically aligned to the target job.
        """
        jd_lower = (job_title + " " + job_description).lower()

        # Skill extraction
        candidate_skills = [
            "Java", "Spring Boot", "Microservices", "Python", "FastAPI",
            "REST API", "AWS", "Docker", "Kubernetes", "SQL", "PostgreSQL",
            "MySQL", "AI Agents", "LangChain", "Git", "CI/CD", "JUnit",
        ]
        matched_skills = [s for s in candidate_skills if s.lower() in jd_lower]
        if not matched_skills:
            matched_skills = ["Java", "Spring Boot", "Python", "REST API", "AWS", "SQL"]

        summary = (
            f"Results-driven Software Engineer (0-2 years) specializing in {', '.join(matched_skills[:4])}. "
            f"Proven expertise building scalable backend services, RESTful APIs, and cloud applications. "
            f"Demonstrated success delivering robust, high-performance solutions tailored for {company}."
        )

        tailored_bullets = [
            f"Architected and deployed enterprise backend microservices utilizing {matched_skills[0]} and {matched_skills[1] if len(matched_skills) > 1 else 'Spring Boot'}, improving API response times by 35%.",
            f"Developed secure, stateless RESTful APIs with {matched_skills[2] if len(matched_skills) > 2 else 'FastAPI'}, ensuring seamless integration across distributed components.",
            f"Containerized application services using Docker & Kubernetes and deployed to AWS cloud infrastructure with automated CI/CD pipelines.",
            f"Engineered optimized SQL queries and database schemas in PostgreSQL/MySQL, reducing database latency for high-concurrency requests.",
            f"Implemented automated testing frameworks (JUnit/pytest) maintaining 90%+ code coverage across critical business endpoints.",
            f"Collaborated within Agile/Scrum sprint cycles to deliver clean, maintainable code adhering to software engineering best practices.",
        ]

        cover_intro = (
            f"I am writing to express my strong interest in the {job_title} position at {company}. "
            f"With hands-on experience developing microservices with {', '.join(matched_skills[:3])}, "
            f"I am eager to contribute to your engineering team."
        )

        return {
            "summary": summary,
            "key_skills": matched_skills,
            "tailored_bullets": tailored_bullets,
            "cover_letter_intro": cover_intro,
        }

    def generate_pdf(
        self,
        job_id: int,
        job_title: str,
        company: str,
        tailored_data: dict,
    ) -> str:
        """
        Generate a clean, professional ATS-friendly tailored PDF resume.
        Returns path to generated PDF.
        """
        safe_company = re.sub(r"[^\w]", "_", company)[:25]
        safe_title = re.sub(r"[^\w]", "_", job_title)[:25]
        filename = f"Resume_{CANDIDATE_NAME.replace(' ', '_')}_{safe_company}_{safe_title}_job{job_id}.pdf"
        output_path = self.resumes_dir / filename

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.2 * cm,
            leftMargin=1.2 * cm,
            topMargin=1.2 * cm,
            bottomMargin=1.2 * cm,
        )

        styles = getSampleStyleSheet()

        name_style = ParagraphStyle(
            "Name",
            parent=styles["Title"],
            fontSize=16,
            textColor=colors.HexColor("#111827"),
            spaceAfter=2,
            alignment=1,  # Centered
        )
        contact_style = ParagraphStyle(
            "Contact",
            parent=styles["Normal"],
            fontSize=8.5,
            textColor=colors.HexColor("#374151"),
            spaceAfter=6,
            alignment=1,
        )
        target_style = ParagraphStyle(
            "TargetStyle",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#1d4ed8"),
            spaceAfter=6,
            alignment=1,
        )
        section_header = ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=10.5,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=8,
            spaceAfter=4,
        )
        normal = ParagraphStyle(
            "CustomNormal",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=3,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=12.5,
            leftIndent=10,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=2,
        )

        story = []

        # ── Header ────────────────────────────────────────────────
        story.append(Paragraph(f"<b>{CANDIDATE_NAME}</b>", name_style))
        story.append(Paragraph("Email: kamalkumar.doddi@gmail.com | Phone: +91 6304883114 | Location: Hyderabad, India", contact_style))
        story.append(Paragraph(f"LinkedIn: linkedin.com/in/kamal-kumar-doddi | GitHub: github.com/kamalds2", contact_style))
        story.append(Paragraph(f"<b>Target Application:</b> {job_title} @ {company}", target_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a")))
        story.append(Spacer(1, 4))

        # ── Professional Summary ──────────────────────────────────
        if summary := tailored_data.get("summary"):
            story.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", section_header))
            story.append(Paragraph(summary, normal))
            story.append(Spacer(1, 4))

        # ── Key Skills ────────────────────────────────────────────
        if skills := tailored_data.get("key_skills"):
            story.append(Paragraph("<b>CORE TECHNICAL SKILLS</b>", section_header))
            skills_text = " • ".join(skills)
            story.append(Paragraph(f"<b>Languages & Frameworks:</b> {skills_text}", normal))
            story.append(Paragraph("<b>Cloud & Tools:</b> AWS, Docker, Kubernetes, Git, CI/CD, REST APIs, Microservices, SQL", normal))
            story.append(Spacer(1, 4))

        # ── Tailored Experience & Accomplishments ────────────────
        story.append(Paragraph("<b>PROFESSIONAL EXPERIENCE & HIGHLIGHTS</b>", section_header))
        story.append(Paragraph(f"<b>Software Engineer (0-2 Yrs Target)</b> | AI & Backend Engineering", normal))

        if bullets := tailored_data.get("tailored_bullets"):
            for bullet in bullets[:7]:
                text_b = bullet if bullet.startswith("•") else f"• {bullet}"
                story.append(Paragraph(text_b, bullet_style))
            story.append(Spacer(1, 4))

        # ── Education & Training ─────────────────────────────────
        story.append(Paragraph("<b>EDUCATION & CERTIFICATIONS</b>", section_header))
        story.append(Paragraph("<b>Bachelor of Technology (B.Tech) in Computer Science & Engineering</b>", normal))
        story.append(Paragraph("Certified AWS Cloud Practitioner & Java Backend Specialization", normal))

        # Build PDF
        doc.build(story)
        logger.info(f"📄 Generated ATS Tailored PDF: {output_path}")
        return str(output_path)

    def create_tailored_resume(
        self,
        job_id: int,
        job_title: str,
        company: str,
        job_description: str,
    ) -> str:
        """
        Full pipeline: generate tailored resume data → create customized ATS PDF.
        Guarantees 100% unique tailored PDF per job application.
        """
        try:
            tailored_data = self.tailor_resume(job_id, job_title, company, job_description)
            if not tailored_data:
                tailored_data = self._generate_fallback_tailored_data(job_title, company, job_description)

            pdf_path = self.generate_pdf(job_id, job_title, company, tailored_data)
            return pdf_path

        except Exception as e:
            logger.warning(f"Tailoring failed for job {job_id} ({e}) — generating dynamic ATS PDF")
            fallback_data = self._generate_fallback_tailored_data(job_title, company, job_description)
            return self.generate_pdf(job_id, job_title, company, fallback_data)

