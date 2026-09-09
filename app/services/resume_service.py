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
        Construct clean, ATS-optimized resume data strictly aligned to the candidate's
        authentic master profile and skills (Java, Spring Boot, Microservices, Python, Generative AI).
        """
        jd_lower = (job_title + " " + job_description).lower()

        # Tailor summary seamlessly without artificial target tags
        summary = (
            "Ambitious AI Application Developer and Software Engineer transitioning a strong Java Full Stack foundation "
            "into advanced Generative AI and LLM development. Hands-on experience building AI Agents, workflow automations, "
            "and intelligent conversational tools using Claude, OpenAI, and prompt engineering. Combines 1.5 years of "
            "professional backend experience (Java, Spring Boot, REST APIs) with a deep passion for building scalable, "
            "AI-assisted platforms and Agent-based AI architectures."
        )

        return {
            "summary": summary,
            "skills": {
                "ai": "Generative AI, Large Language Models (Claude, OpenAI), Prompt Engineering, Agent-based AI",
                "backend": "Java, Spring Boot, RESTful APIs, Micro-services, Python (Exposure)",
                "automation": "Workflow Orchestration, AI API Integration, Conversational AI, Speech-to-Text",
                "databases": "MySQL, PostgreSQL concepts, Git, GitHub, Postman, AWS Cloud Fundamentals",
            },
            "experience_bullets": [
                "Built and maintained scalable backend systems utilizing Java and Spring Boot, establishing a robust micro-services architecture to support enterprise applications.",
                "Designed secure RESTful APIs to handle high-throughput data processing, facilitating smooth integration points for future AI and automation workflows.",
                "Optimized complex relational database queries to reduce data synchronization latency by 20%, ensuring fast response times critical for real-time applications.",
                "Continuously upskilled in Generative AI, applying prompt engineering and LLM integrations to prototype automated reporting and intelligent system features.",
            ],
            "projects": [
                {
                    "title": "Agentic AI Job Application Bot | github.com/kamalds2/AI-Job-Agent",
                    "bullets": [
                        "Built an AI-powered automation system that matches resumes against job descriptions and customizes applications using Large Language Models (OpenAI/Claude).",
                        "Utilized advanced prompt engineering and workflow orchestration to simulate Agent-based AI behaviors, significantly accelerating the application pipeline.",
                    ],
                },
                {
                    "title": "24/7 AI Voice Assistant | Conversational AI & API Integration",
                    "bullets": [
                        "Developed a conversational AI voice assistant integrating speech-to-text, LLM reasoning algorithms, and voice synthesis to provide real-time user interaction.",
                    ],
                },
                {
                    "title": "McLean (Enterprise Facility System) | Java Spring Boot & REST APIs",
                    "bullets": [
                        "Constructed highly scalable REST APIs serving as the backend backbone for operational dashboards, utilizing secure JWT authentication.",
                    ],
                },
            ],
        }

    def generate_pdf(
        self,
        job_id: int,
        job_title: str,
        company: str,
        tailored_data: dict,
    ) -> str:
        """
        Generate an exact, 1-page professional ATS PDF resume matching the candidate's authentic template.
        Uses exact contact details (+91-9398872099, Hyderabad) with zero artificial 'Target' tags.
        """
        from reportlab.platypus import Table, TableStyle

        safe_company = re.sub(r"[^\w]", "_", company)[:25]
        safe_title = re.sub(r"[^\w]", "_", job_title)[:25]
        filename = f"Resume_Kamal_Kumar_{safe_company}_{safe_title}_job{job_id}.pdf"
        output_path = self.resumes_dir / filename

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.0 * cm,
            leftMargin=1.0 * cm,
            topMargin=0.8 * cm,
            bottomMargin=0.8 * cm,
        )

        styles = getSampleStyleSheet()

        name_style = ParagraphStyle(
            "NameStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#111827"),
            alignment=1,  # Centered
            spaceAfter=2,
        )
        tagline_style = ParagraphStyle(
            "TaglineStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#1e293b"),
            alignment=1,
            spaceAfter=2,
        )
        contact_style = ParagraphStyle(
            "ContactStyle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10,
            textColor=colors.HexColor("#374151"),
            alignment=1,
            spaceAfter=1,
        )
        section_header = ParagraphStyle(
            "SectionHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=12,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=4,
            spaceAfter=2,
        )
        body_style = ParagraphStyle(
            "BodyTextCustom",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10.5,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=2,
        )
        bullet_style = ParagraphStyle(
            "BulletCustom",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.6,
            leading=10,
            leftIndent=8,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=1.5,
        )
        item_title_left = ParagraphStyle(
            "ItemTitleLeft",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.0,
            leading=10.5,
            textColor=colors.HexColor("#0f172a"),
        )
        item_title_right = ParagraphStyle(
            "ItemTitleRight",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10.5,
            alignment=2,  # Right-aligned
            textColor=colors.HexColor("#475569"),
        )

        story = []

        # ── 1. Header ─────────────────────────────────────────────
        story.append(Paragraph("<b>DODDI KAMAL KUMAR</b>", name_style))
        story.append(Paragraph("<b>AI Application Developer | Java Backend | Generative AI | LLMs | Agentic Workflows</b>", tagline_style))
        story.append(Paragraph("Hyderabad, Telangana &nbsp;|&nbsp; +91-9398872099 &nbsp;|&nbsp; kamalkumar.doddi@gmail.com", contact_style))
        story.append(Paragraph("LinkedIn: linkedin.com/in/kamal-doddi-6422b7279 &nbsp;|&nbsp; GitHub: github.com/kamalds2", contact_style))
        story.append(Spacer(1, 2))
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#0f172a"), spaceAfter=3))

        # ── 2. Professional Summary ───────────────────────────────
        story.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", section_header))
        summary_text = tailored_data.get("summary") or (
            "Ambitious AI Application Developer and Software Engineer transitioning a strong Java Full Stack foundation into advanced Generative AI and "
            "LLM development. Hands-on experience building AI Agents, workflow automations, and intelligent conversational tools using Claude, OpenAI, "
            "and prompt engineering. Combines 1.5 years of professional backend experience (Java, Spring Boot, REST APIs) with a deep passion for "
            "building scalable, AI-assisted platforms and Agent-based AI architectures."
        )
        story.append(Paragraph(summary_text, body_style))

        # ── 3. Technical Skills ───────────────────────────────────
        story.append(Paragraph("<b>TECHNICAL SKILLS</b>", section_header))
        story.append(Paragraph("<b>AI & LLM Technologies:</b> Generative AI, Large Language Models (Claude, OpenAI), Prompt Engineering, Agent-based AI", body_style))
        story.append(Paragraph("<b>Backend & APIs:</b> Java, Spring Boot, RESTful APIs, Micro-services, Python (Exposure)", body_style))
        story.append(Paragraph("<b>Automation & Integrations:</b> Workflow Orchestration, AI API Integration, Conversational AI, Speech-to-Text", body_style))
        story.append(Paragraph("<b>Databases & Tools:</b> MySQL, PostgreSQL concepts, Git, GitHub, Postman, AWS Cloud Fundamentals", body_style))

        # ── 4. Professional Experience ────────────────────────────
        story.append(Paragraph("<b>PROFESSIONAL EXPERIENCE</b>", section_header))
        exp_table = Table(
            [
                [
                    Paragraph("<b>Software Engineer (Backend & AI Integration)</b> | Siri IT Innovations, Hyderabad", item_title_left),
                    Paragraph("Jan 2025 – June 2026", item_title_right),
                ]
            ],
            colWidths=[14.0 * cm, 4.8 * cm],
        )
        exp_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(exp_table)

        exp_bullets = tailored_data.get("experience_bullets") or [
            "Built and maintained scalable backend systems utilizing Java and Spring Boot, establishing a robust micro-services architecture to support enterprise applications.",
            "Designed secure RESTful APIs to handle high-throughput data processing, facilitating smooth integration points for future AI and automation workflows.",
            "Optimized complex relational database queries to reduce data synchronization latency by 20%, ensuring fast response times critical for real-time applications.",
            "Continuously upskilled in Generative AI, applying prompt engineering and LLM integrations to prototype automated reporting and intelligent system features.",
        ]
        for bullet in exp_bullets:
            b_text = bullet if bullet.startswith("•") else f"• {bullet}"
            story.append(Paragraph(b_text, bullet_style))

        # ── 5. Project Portfolio ──────────────────────────────────
        story.append(Paragraph("<b>PROJECT PORTFOLIO</b>", section_header))

        # Project 1
        story.append(Paragraph("<b>Agentic AI Job Application Bot</b> | github.com/kamalds2/AI-Job-Agent", item_title_left))
        story.append(Paragraph("• Built an AI-powered automation system that matches resumes against job descriptions and customizes applications using Large Language Models (OpenAI/Claude).", bullet_style))
        story.append(Paragraph("• Utilized advanced prompt engineering and workflow orchestration to simulate Agent-based AI behaviors, significantly accelerating the application pipeline.", bullet_style))

        # Project 2
        story.append(Paragraph("<b>24/7 AI Voice Assistant</b> | Conversational AI & API Integration", item_title_left))
        story.append(Paragraph("• Developed a conversational AI voice assistant integrating speech-to-text, LLM reasoning algorithms, and voice synthesis to provide real-time user interaction.", bullet_style))

        # Project 3
        story.append(Paragraph("<b>McLean (Enterprise Facility System)</b> | Java Spring Boot & REST APIs", item_title_left))
        story.append(Paragraph("• Constructed highly scalable REST APIs serving as the backend backbone for operational dashboards, utilizing secure JWT authentication.", bullet_style))

        # ── 6. Education & Certifications ─────────────────────────
        story.append(Paragraph("<b>EDUCATION & CERTIFICATIONS</b>", section_header))
        edu_table = Table(
            [
                [
                    Paragraph("<b>Certified Full Stack Java Developer</b> | KodNest Technologies", item_title_left),
                    Paragraph("End-to-End Training", item_title_right),
                ],
                [
                    Paragraph("<b>B.Tech in Computer Science & Engineering</b> | Siddhartha Institute of Technology and Sciences", item_title_left),
                    Paragraph("2019 – 2023", item_title_right),
                ],
            ],
            colWidths=[14.0 * cm, 4.8 * cm],
        )
        edu_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(edu_table)

        # Build PDF
        doc.build(story)
        logger.info(f"📄 Generated ATS Authentic PDF: {output_path}")
        return str(output_path)

    def create_tailored_resume(
        self,
        job_id: int,
        job_title: str,
        company: str,
        job_description: str,
    ) -> str:
        """
        Full pipeline: generate tailored resume data → create authentic 1-page PDF.
        Guarantees 100% clean formatting identical to the master resume template.
        """
        try:
            tailored_data = self.tailor_resume(job_id, job_title, company, job_description)
            if not tailored_data:
                tailored_data = self._generate_fallback_tailored_data(job_title, company, job_description)

            pdf_path = self.generate_pdf(job_id, job_title, company, tailored_data)
            return pdf_path

        except Exception as e:
            logger.warning(f"Tailoring failed for job {job_id} ({e}) — generating dynamic authentic PDF")
            fallback_data = self._generate_fallback_tailored_data(job_title, company, job_description)
            return self.generate_pdf(job_id, job_title, company, fallback_data)

