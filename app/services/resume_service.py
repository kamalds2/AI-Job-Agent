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
import fitz  # PyMuPDF
import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

from app.config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MASTER_RESUME_PATH,
    RESUMES_DIR,
    CANDIDATE_NAME,
)
from app.prompts.resume_prompt import (
    RESUME_TAILORING_SYSTEM_PROMPT,
    build_resume_user_prompt,
)

logger = logging.getLogger(__name__)


def _make_anthropic_client():
    """SSL-patched Anthropic client for Windows environments."""
    if sys.platform == "win32":
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client(verify=False))
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class ResumeService:
    """
    Reads master PDF resume and generates ATS-tailored versions per job.
    """

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        self.client = _make_anthropic_client()
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
        Generate a tailored resume for a specific job using Claude.

        Returns: Claude's tailored resume data as dict
        """
        resume_text = self.extract_resume_text()

        user_prompt = build_resume_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            resume_text=resume_text,
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=RESUME_TAILORING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            content = message.content[0].text.strip()

            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            tailored_data = json.loads(content)
            logger.info(f"✅ Tailored resume generated for '{job_title}' @ {company}")
            return tailored_data

        except Exception as e:
            logger.error(f"❌ Resume tailoring failed: {e}")
            return {}

    def generate_pdf(
        self,
        job_id: int,
        job_title: str,
        company: str,
        tailored_data: dict,
    ) -> str:
        """
        Generate an ATS-friendly tailored PDF resume.
        Returns the path to the generated PDF.
        """
        # Safe filename
        safe_company = re.sub(r"[^\w]", "_", company)[:30]
        safe_title = re.sub(r"[^\w]", "_", job_title)[:30]
        filename = f"Resume_{CANDIDATE_NAME.replace(' ', '_')}_{safe_company}_{safe_title}_job{job_id}.pdf"
        output_path = self.resumes_dir / filename

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.5 * cm,
            leftMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()

        # Custom styles
        name_style = ParagraphStyle(
            "Name",
            parent=styles["Title"],
            fontSize=18,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=4,
        )
        section_header = ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=11,
            textColor=colors.HexColor("#16213e"),
            spaceBefore=10,
            spaceAfter=4,
            borderPad=(0, 0, 2, 0),
        )
        normal = ParagraphStyle(
            "CustomNormal",
            parent=styles["Normal"],
            fontSize=9,
            leading=14,
            spaceAfter=3,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            leftIndent=12,
            spaceAfter=2,
        )

        story = []

        # ── Header ────────────────────────────────────────────────
        story.append(Paragraph(CANDIDATE_NAME, name_style))
        story.append(Paragraph(f"<i>Tailored for: {job_title} @ {company}</i>", normal))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16213e")))
        story.append(Spacer(1, 8))

        # ── Professional Summary ──────────────────────────────────
        if summary := tailored_data.get("summary"):
            story.append(Paragraph("PROFESSIONAL SUMMARY", section_header))
            story.append(Paragraph(summary, normal))
            story.append(Spacer(1, 6))

        # ── Key Skills ────────────────────────────────────────────
        if skills := tailored_data.get("key_skills"):
            story.append(Paragraph("CORE SKILLS", section_header))
            skills_text = " • ".join(skills)
            story.append(Paragraph(skills_text, normal))
            story.append(Spacer(1, 6))

        # ── Original Resume Content ───────────────────────────────
        try:
            resume_text = self.extract_resume_text()
            story.append(Paragraph("EXPERIENCE", section_header))

            # Add tailored bullets first
            if bullets := tailored_data.get("tailored_bullets"):
                story.append(Paragraph("<b>Key Highlights (Tailored for This Role):</b>", normal))
                for bullet in bullets[:8]:  # Max 8 bullets
                    story.append(Paragraph(bullet, bullet_style))
                story.append(Spacer(1, 6))

            # Add remaining resume content
            story.append(Paragraph("<b>Full Experience:</b>", normal))
            # Truncate long resume text
            for line in resume_text.split("\n")[:60]:
                line = line.strip()
                if line:
                    story.append(Paragraph(line, normal if not line.startswith("•") else bullet_style))

        except Exception as e:
            logger.warning(f"Could not embed resume content: {e}")

        # ── Cover Letter Intro ────────────────────────────────────
        if cover := tailored_data.get("cover_letter_intro"):
            story.append(Spacer(1, 10))
            story.append(HRFlowable(width="100%", thickness=0.5))
            story.append(Spacer(1, 4))
            story.append(Paragraph("COVER LETTER INTRO", section_header))
            story.append(Paragraph(cover, normal))

        # Build PDF
        doc.build(story)
        logger.info(f"📄 Generated PDF: {output_path}")
        return str(output_path)

    def create_tailored_resume(
        self,
        job_id: int,
        job_title: str,
        company: str,
        job_description: str,
    ) -> str | None:
        """
        Full pipeline: tailor via Claude → generate PDF.
        Returns path to generated PDF, or None on failure.
        """
        try:
            tailored_data = self.tailor_resume(job_id, job_title, company, job_description)
            if not tailored_data:
                logger.warning(f"No tailored data for job {job_id}")
                return None

            pdf_path = self.generate_pdf(job_id, job_title, company, tailored_data)
            return pdf_path

        except Exception as e:
            logger.error(f"❌ create_tailored_resume failed for job {job_id}: {e}")
            return None
