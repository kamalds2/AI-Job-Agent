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
import time
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

    @property
    def master_resume_text(self) -> str:
        """Cached property for master resume text."""
        if not hasattr(self, "_cached_master_text") or not self._cached_master_text:
            self._cached_master_text = self.extract_resume_text()
        return self._cached_master_text

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
        exp_years: float = 1.5,
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

        return self._generate_fallback_tailored_data(job_title, company, job_description, exp_years=exp_years)

    def _generate_fallback_tailored_data(
        self,
        job_title: str,
        company: str,
        job_description: str,
        exp_years: float = 1.5,
    ) -> dict:
        """
        Extract required skills from JD and dynamically infuse them into the candidate's
        skills, summary, experience bullets, and project portfolio.
        """
        text_corpus = (job_title + " " + job_description).lower()

        # ── 1. Match Backend & Framework Skills ───────────────────
        backend_pool = [
            ("Java", "Java"), ("Spring Boot", "Spring Boot"), ("Spring Security", "Spring Security"),
            ("Spring Data", "Spring Data JPA"), ("REST", "REST APIs"), ("Hibernate", "Hibernate"),
            ("MVC", "MVC"), ("PHP", "PHP"), ("Python", "Python (FastAPI)"),
            ("Microservices", "Microservices Architecture"), ("Kafka", "Apache Kafka"),
        ]
        matched_backend = [label for key, label in backend_pool if key.lower() in text_corpus]
        if not matched_backend:
            matched_backend = ["Java", "Spring Boot", "Spring Security", "Spring Data JPA", "REST APIs", "Hibernate", "MVC", "PHP"]
        else:
            for base in ["Java", "Spring Boot", "Spring Security", "Spring Data JPA", "REST APIs", "Hibernate", "MVC", "PHP"]:
                if base not in matched_backend:
                    matched_backend.append(base)
        backend_skills_str = ", ".join(dict.fromkeys(matched_backend))

        # ── 2. Match Frontend & UI Skills ─────────────────────────
        frontend_pool = [
            ("React", "React.js"), ("Vue", "Vue.js"), ("JavaScript", "JavaScript (ES6+)"),
            ("HTML", "HTML5"), ("CSS", "CSS3"), ("Tailwind", "Tailwind CSS"), ("TypeScript", "TypeScript"),
        ]
        matched_frontend = [label for key, label in frontend_pool if key.lower() in text_corpus]
        if not matched_frontend:
            matched_frontend = ["React.js", "Vue.js", "JavaScript (ES6+)", "HTML5", "CSS3", "Tailwind CSS"]
        else:
            for base in ["React.js", "Vue.js", "JavaScript (ES6+)", "HTML5", "CSS3", "Tailwind CSS"]:
                if base not in matched_frontend:
                    matched_frontend.append(base)
        frontend_skills_str = ", ".join(dict.fromkeys(matched_frontend))

        # ── 3. Match AI & Automation Skills ───────────────────────
        ai_pool = [
            ("Claude", "Claude API"), ("LLM", "LLM Application Development"),
            ("Agent", "AI Agent Development"), ("Prompt", "Prompt Engineering"),
            ("Agentic", "Agentic AI"), ("LangChain", "LangChain"), ("LangGraph", "LangGraph"),
            ("Generative AI", "Generative AI"), ("RAG", "RAG"),
        ]
        matched_ai = [label for key, label in ai_pool if key.lower() in text_corpus]
        if not matched_ai:
            matched_ai = ["Claude API", "LLM Application Development", "AI Agent Development", "Prompt Engineering", "Agentic AI"]
        else:
            for base in ["Claude API", "LLM Application Development", "AI Agent Development", "Prompt Engineering", "Agentic AI"]:
                if base not in matched_ai:
                    matched_ai.append(base)
        ai_skills_str = ", ".join(dict.fromkeys(matched_ai))

        # ── 4. Cloud & Databases ──────────────────────────────────
        cloud_skills_str = "Amazon EC2, Amazon VPC, IAM, Security Groups, Route Tables, NAT Gateway, Cloud Networking"
        db_pool = [
            ("MySQL", "MySQL"), ("SQL", "SQL Optimization"), ("Git", "Git"),
            ("GitHub", "GitHub"), ("Postman", "Postman"), ("JWT", "JWT Authentication"),
            ("SDLC", "SDLC"), ("PostgreSQL", "PostgreSQL"), ("Docker", "Docker"),
        ]
        matched_db = [label for key, label in db_pool if key.lower() in text_corpus]
        if not matched_db:
            matched_db = ["MySQL", "SQL Optimization", "Git", "GitHub", "Postman", "JWT Authentication", "SDLC"]
        else:
            for base in ["MySQL", "SQL Optimization", "Git", "GitHub", "Postman", "JWT Authentication", "SDLC"]:
                if base not in matched_db:
                    matched_db.append(base)
        db_skills_str = ", ".join(dict.fromkeys(matched_db))

        # ── 5. Tailored Summary based on exp_years ────────────────
        exp_str = "2 years" if exp_years >= 2.0 else "1.5 years"
        summary = (
            f"Results-driven Java Full Stack Developer with {exp_str} of experience building scalable enterprise applications using Java, Spring Boot, "
            f"React.js, and MySQL. Currently expanding expertise in Generative AI, AI Agent development using Claude and LLM workflows, and AWS "
            f"Cloud fundamentals. Passionate about developing intelligent automation solutions, RESTful microservices, and cloud-native applications "
            f"while continuously learning modern AI and cloud technologies."
        )

        # ── 6. Experience Dates & Bullets ─────────────────────────
        exp_date = "Jan 2024 – June 2026" if exp_years >= 2.0 else "Jan 2025 – June 2026"
        exp_bullets = [
            "Engineered the McLean Integrated Facility Management System using a Microservices architecture built with Java Spring Boot, React.js, and MySQL, deploying robust features for multi-site enterprise operations.",
            "Architected scalable RESTful APIs leveraging Spring Data JPA and Hibernate for optimized database transactions, powering critical modules like asset tracking and PPM scheduling.",
            "Integrated React.js front-end components with real-time operational dashboards, successfully reducing data synchronization latency by 20%.",
            "Implemented secure Role-Based Access Control (RBAC) using Spring Security and JWT (JSON Web Tokens) for automated reporting modules.",
        ]

        # ── 7. Project Portfolio ──────────────────────────────────
        projects = [
            {
                "title": "AI Job Application Agent | GenAI & Automation",
                "bullets": [
                    "Built an AI-powered automation system that searches multiple job portals, matches resumes against job descriptions, customizes resumes, and automates job applications using LLMs and workflow orchestration.",
                ],
            },
            {
                "title": "24/7 AI Voice Assistant | Conversational AI",
                "bullets": [
                    "Developed a conversational AI voice assistant integrating speech-to-text, LLM reasoning, voice synthesis, and WhatsApp notifications for seamless user interaction.",
                ],
            },
            {
                "title": "McLean (Facility & Asset Management System) | Full Stack Java",
                "bullets": [
                    "Developed a specialized asset management system backend utilizing Java Spring Boot paired with MySQL for robust tracking and continuous maintenance scheduling.",
                    "Constructed highly scalable REST APIs with integrated real-time dashboard analytics and dynamic QR code generation functionality.",
                ],
            },
        ]

        return {
            "summary": summary,
            "exp_date": exp_date,
            "skills": {
                "ai": ai_skills_str,
                "backend": backend_skills_str,
                "frontend": frontend_skills_str,
                "cloud": cloud_skills_str,
                "databases": db_skills_str,
            },
            "experience_bullets": exp_bullets,
            "projects": projects,
        }

    def generate_pdf_1_5_years(
        self,
        job_id: int,
        job_title: str,
        company: str,
        tailored_data: dict,
        portal: str = "",
    ) -> str:
        """
        Template 1 (0-2 Yrs / 1.5 Yrs):
        - Headline: DODDI KAMAL KUMAR
        - Professional Summary: Java Full Stack Developer with 1.5 years of experience...
        - Sections: Professional Summary, Technical Skills (5 categories), Professional Development & Upskilling, Professional Experience, Project Portfolio, Education & Certifications.
        """
        from reportlab.platypus import Table, TableStyle

        target_dir = self.resumes_dir / portal if portal else self.resumes_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        job_tag = str(job_id).split("_")[-1][-5:] if job_id else str(int(time.time()))[-5:]
        output_filename = f"Resume_Kamal_Kumar_{job_tag}.pdf"
        output_path = target_dir / output_filename

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.0 * cm,
            leftMargin=1.0 * cm,
            topMargin=0.7 * cm,
            bottomMargin=0.7 * cm,
        )

        styles = getSampleStyleSheet()

        name_style = ParagraphStyle(
            "NameStyle1",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#111827"),
            alignment=1,  # Centered
            spaceAfter=2,
        )
        contact_style = ParagraphStyle(
            "ContactStyle1",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10,
            textColor=colors.HexColor("#374151"),
            alignment=1,
            spaceAfter=2,
        )
        section_header = ParagraphStyle(
            "SectionHeader1",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.8,
            leading=11.5,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=3.5,
            spaceAfter=1.5,
        )
        body_style = ParagraphStyle(
            "BodyTextCustom1",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=9.8,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=1.5,
        )
        bullet_style = ParagraphStyle(
            "BulletCustom1",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.3,
            leading=9.5,
            leftIndent=8,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=1.0,
        )
        item_title_left = ParagraphStyle(
            "ItemTitleLeft1",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=10.0,
            textColor=colors.HexColor("#0f172a"),
        )
        item_title_right = ParagraphStyle(
            "ItemTitleRight1",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=10.0,
            alignment=2,
            textColor=colors.HexColor("#475569"),
        )

        story = []

        # ── 1. Header ─────────────────────────────────────────────
        story.append(Paragraph("<b>DODDI KAMAL KUMAR</b>", name_style))
        story.append(Paragraph("Hyderabad, Telangana &nbsp;|&nbsp; +91-9398872099 &nbsp;|&nbsp; kamalkumar.doddi@gmail.com", contact_style))
        story.append(Paragraph("LinkedIn: linkedin.com/in/kamal-doddi-6422b7279 &nbsp;|&nbsp; GitHub: github.com/kamalds2", contact_style))
        story.append(Spacer(1, 1))
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#0f172a"), spaceAfter=2.5))

        # ── 2. Professional Summary ───────────────────────────────
        story.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", section_header))
        summary_text = tailored_data.get("summary") or (
            "Results-driven Java Full Stack Developer with 1.5 years of experience building scalable enterprise applications using Java, Spring Boot, "
            "React.js, and MySQL. Currently expanding expertise in Generative AI, AI Agent development using Claude and LLM workflows, and AWS "
            "Cloud fundamentals. Passionate about developing intelligent automation solutions, RESTful microservices, and cloud-native applications "
            "while continuously learning modern AI and cloud technologies."
        )
        story.append(Paragraph(summary_text, body_style))

        # ── 3. Technical Skills ───────────────────────────────────
        skills_data = tailored_data.get("skills") if isinstance(tailored_data.get("skills"), dict) else {}
        backend_skills = skills_data.get("backend") or "Java, Spring Boot, Spring Security, Spring Data JPA, REST APIs, Hibernate, MVC, PHP"
        frontend_skills = skills_data.get("frontend") or "React.js, Vue.js, JavaScript (ES6+), HTML5, CSS3, Tailwind CSS"
        ai_skills = skills_data.get("ai") or "Claude API, LLM Application Development, AI Agent Development, Prompt Engineering, Agentic AI"
        cloud_skills = skills_data.get("cloud") or "Amazon EC2, Amazon VPC, IAM, Security Groups, Route Tables, NAT Gateway, Cloud Networking"
        db_skills = skills_data.get("databases") or "MySQL, SQL Optimization, Git, GitHub, Postman, JWT Authentication, SDLC"

        story.append(Paragraph("<b>TECHNICAL SKILLS</b>", section_header))
        story.append(Paragraph(f"<b>Backend & Frameworks:</b> {backend_skills}", body_style))
        story.append(Paragraph(f"<b>Frontend & UI:</b> {frontend_skills}", body_style))
        story.append(Paragraph(f"<b>AI & Automation:</b> {ai_skills}", body_style))
        story.append(Paragraph(f"<b>Cloud (AWS Beginner):</b> {cloud_skills}", body_style))
        story.append(Paragraph(f"<b>Databases & Tools:</b> {db_skills}", body_style))

        # ── 4. Professional Development & Upskilling ──────────────
        story.append(Paragraph("<b>PROFESSIONAL DEVELOPMENT & UPSKILLING</b>", section_header))
        story.append(Paragraph("• <b>AWS Cloud Architecture:</b> Hands-on labs covering VPC, EC2, IAM, Security Groups, Route Tables, NAT Gateway, Load Balancers, Auto Scaling, and RDS.", bullet_style))
        story.append(Paragraph("• <b>AI & LLM Workflows:</b> Building AI Agents using Claude APIs, developing automation projects integrating AI with backend services, exploring Agentic AI architectures, and prompt orchestration.", bullet_style))

        # ── 5. Professional Experience ────────────────────────────
        story.append(Paragraph("<b>PROFESSIONAL EXPERIENCE</b>", section_header))
        exp_date_str = tailored_data.get("exp_date", "Jan 2025 – June 2026")
        exp_table = Table(
            [
                [
                    Paragraph("<b>Junior Software Engineer</b> | Siri IT Innovations, Hyderabad", item_title_left),
                    Paragraph(exp_date_str, item_title_right),
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
            "Engineered the McLean Integrated Facility Management System using a Microservices architecture built with Java Spring Boot, React.js, and MySQL, deploying robust features for multi-site enterprise operations.",
            "Architected scalable RESTful APIs leveraging Spring Data JPA and Hibernate for optimized database transactions, powering critical modules like asset tracking and PPM scheduling.",
            "Integrated React.js front-end components with real-time operational dashboards, successfully reducing data synchronization latency by 20%.",
            "Implemented secure Role-Based Access Control (RBAC) using Spring Security and JWT (JSON Web Tokens) for automated reporting modules.",
        ]
        for bullet in exp_bullets[:4]:
            b_text = bullet if bullet.startswith("•") else f"• {bullet}"
            story.append(Paragraph(b_text, bullet_style))

        # ── 6. Project Portfolio ──────────────────────────────────
        story.append(Paragraph("<b>PROJECT PORTFOLIO</b>", section_header))
        projects_list = tailored_data.get("projects") or [
            {
                "title": "AI Job Application Agent | GenAI & Automation",
                "bullets": [
                    "Built an AI-powered automation system that searches multiple job portals, matches resumes against job descriptions, customizes resumes, and automates job applications using LLMs and workflow orchestration.",
                ],
            },
            {
                "title": "24/7 AI Voice Assistant | Conversational AI",
                "bullets": [
                    "Developed a conversational AI voice assistant integrating speech-to-text, LLM reasoning algorithms, and voice synthesis to provide real-time user interaction.",
                ],
            },
            {
                "title": "McLean (Facility & Asset Management System) | Full Stack Java",
                "bullets": [
                    "Developed a specialized asset management system backend utilizing Java Spring Boot paired with MySQL for robust tracking and continuous maintenance scheduling.",
                    "Constructed highly scalable REST APIs with integrated real-time dashboard analytics and dynamic QR code generation functionality.",
                ],
            },
        ]

        for proj in projects_list[:3]:
            p_title = proj.get("title", "")
            story.append(Paragraph(f"<b>{p_title}</b>", item_title_left))
            for b in proj.get("bullets", []):
                b_text = b if b.startswith("•") else f"• {b}"
                story.append(Paragraph(b_text, bullet_style))

        # ── 7. Education & Certifications ─────────────────────────
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

        doc.build(story)
        logger.info(f"📄 Generated ATS Authentic 1.5Yrs PDF: {output_path}")
        return str(output_path)

    def generate_pdf_2_plus_years(
        self,
        job_id: int,
        job_title: str,
        company: str,
        tailored_data: dict,
        portal: str = "",
    ) -> str:
        """
        Template 2 (2+ Yrs requirement):
        - Headline: DODDI KAMAL KUMAR
        - Subtitle: Software Engineer | Java & Spring Boot | Microservices | AI Systems
        - Professional Summary: Results-driven Software Engineer with equivalent experience designing, coding, testing...
        - Sections: Professional Summary, Technical Skills (Backend, Databases & Cloud, Testing & Methodologies, AI & Innovation), Professional Experience, Project Portfolio, Education & Certifications.
        """
        from reportlab.platypus import Table, TableStyle

        target_dir = self.resumes_dir / portal if portal else self.resumes_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        job_tag = str(job_id).split("_")[-1][-5:] if job_id else str(int(time.time()))[-5:]
        output_filename = f"Resume_Kamal_Kumar_{job_tag}.pdf"
        output_path = target_dir / output_filename

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.0 * cm,
            leftMargin=1.0 * cm,
            topMargin=0.7 * cm,
            bottomMargin=0.7 * cm,
        )

        styles = getSampleStyleSheet()

        name_style = ParagraphStyle(
            "NameStyle2",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#111827"),
            alignment=1,  # Centered
            spaceAfter=2,
        )
        tagline_style = ParagraphStyle(
            "TaglineStyle2",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#1e293b"),
            alignment=1,
            spaceAfter=2,
        )
        contact_style = ParagraphStyle(
            "ContactStyle2",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10,
            textColor=colors.HexColor("#374151"),
            alignment=1,
            spaceAfter=2,
        )
        section_header = ParagraphStyle(
            "SectionHeader2",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.8,
            leading=11.5,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=3.5,
            spaceAfter=1.5,
        )
        body_style = ParagraphStyle(
            "BodyTextCustom2",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=9.8,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=1.5,
        )
        bullet_style = ParagraphStyle(
            "BulletCustom2",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.3,
            leading=9.5,
            leftIndent=8,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=1.0,
        )
        item_title_left = ParagraphStyle(
            "ItemTitleLeft2",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=10.0,
            textColor=colors.HexColor("#0f172a"),
        )
        item_title_right = ParagraphStyle(
            "ItemTitleRight2",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=10.0,
            alignment=2,
            textColor=colors.HexColor("#475569"),
        )

        story = []

        # ── 1. Header ─────────────────────────────────────────────
        story.append(Paragraph("<b>DODDI KAMAL KUMAR</b>", name_style))
        story.append(Paragraph("<b>Software Engineer | Java & Spring Boot | Microservices | AI Systems</b>", tagline_style))
        story.append(Paragraph("Hyderabad, Telangana &nbsp;|&nbsp; +91-9398872099 &nbsp;|&nbsp; kamalkumar.doddi@gmail.com", contact_style))
        story.append(Paragraph("LinkedIn: linkedin.com/in/kamal-doddi-6422b7279 &nbsp;|&nbsp; GitHub: github.com/kamalds2", contact_style))
        story.append(Spacer(1, 1))
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#0f172a"), spaceAfter=2.5))

        # ── 2. Professional Summary ───────────────────────────────
        story.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", section_header))
        summary_text = (
            "Results-driven Software Engineer with equivalent experience designing, coding, testing, and deploying scalable applications. Proficient in Java, "
            "Spring Boot, and cloud-native microservices architecture. Experienced in developing AI prototypes and production systems, alongside utilizing "
            "robust databases including Oracle SQL and MongoDB (NoSQL). Adept at working within Agile methodologies, implementing automated "
            "functional testing using BDD, and ensuring strict adherence to security and compliance requirements across technology initiatives."
        )
        story.append(Paragraph(summary_text, body_style))

        # ── 3. Technical Skills ───────────────────────────────────
        skills_data = tailored_data.get("skills") if isinstance(tailored_data.get("skills"), dict) else {}
        backend_skills = skills_data.get("backend") or "Java, Spring Boot, Hibernate, Cloud-Native Microservices, RESTful APIs"
        db_cloud = "Oracle SQL, MongoDB (NoSQL), AWS, OCP (OpenShift Container Platform) Exposure"
        testing_skills = "Agile Development, BDD (Automated Functional Testing), Debugging, System Design"
        ai_skills = "AI Prototypes, Production AI Systems, Generative AI, LLMs, Workflow Automation"

        story.append(Paragraph("<b>TECHNICAL SKILLS</b>", section_header))
        story.append(Paragraph(f"<b>Backend & Frameworks:</b> {backend_skills}", body_style))
        story.append(Paragraph(f"<b>Databases & Cloud:</b> {db_cloud}", body_style))
        story.append(Paragraph(f"<b>Testing & Methodologies:</b> {testing_skills}", body_style))
        story.append(Paragraph(f"<b>AI & Innovation:</b> {ai_skills}", body_style))

        # ── 4. Professional Experience ────────────────────────────
        story.append(Paragraph("<b>PROFESSIONAL EXPERIENCE</b>", section_header))
        exp_table = Table(
            [
                [
                    Paragraph("<b>Software Engineer</b> | Siri IT Innovations, Hyderabad", item_title_left),
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

        exp_bullets = [
            "Designed, coded, tested, and debugged low to moderately complex cloud-native microservice applications utilizing Java and Spring Boot.",
            "Participated in installation, upgrades, and deployment efforts, collaborating seamlessly with technology colleagues to meet established SLAs in an Agile environment.",
            "Developed automated functional tests utilizing BDD methodologies to ensure high-quality deliverables and identify opportunities for service quality improvements.",
            "Integrated Oracle SQL and NoSQL (MongoDB) databases using Hibernate to optimize enterprise data retrieval, resolving complex technical assignments requiring research.",
            "Exercised independent judgment to adhere to security and compliance requirements while deploying backend services and escalating issues as needed.",
        ]
        for bullet in exp_bullets:
            b_text = bullet if bullet.startswith("•") else f"• {bullet}"
            story.append(Paragraph(b_text, bullet_style))

        # ── 5. Project Portfolio ──────────────────────────────────
        story.append(Paragraph("<b>PROJECT PORTFOLIO</b>", section_header))
        projects_list = [
            {
                "title": "Agentic AI Job Application Bot (AI Prototype) | LLMs, Automation, Spring Boot",
                "bullets": [
                    "Built a production-ready AI prototype that utilizes Large Language Models to automate data extraction and simulate agentic workflows.",
                    "Presented recommendations for resolving AI integration bottlenecks, ensuring high availability and compliance with established technical patterns.",
                ],
            },
            {
                "title": "McLean (Enterprise Facility System) | Java, Hibernate, Oracle SQL",
                "bullets": [
                    "Constructed highly scalable REST APIs serving as the backend backbone for operational dashboards, utilizing secure JWT authentication and Hibernate for data mapping.",
                    "Documented technical assignments and executed testing phases to validate system reliability across distributed networks.",
                ],
            },
        ]

        for proj in projects_list:
            p_title = proj.get("title", "")
            story.append(Paragraph(f"<b>{p_title}</b>", item_title_left))
            for b in proj.get("bullets", []):
                b_text = b if b.startswith("•") else f"• {b}"
                story.append(Paragraph(b_text, bullet_style))

        # ── 6. Education & Certifications ─────────────────────────
        story.append(Paragraph("<b>EDUCATION & CERTIFICATIONS</b>", section_header))
        edu_table = Table(
            [
                [
                    Paragraph("<b>Certified Full Stack Developer</b> | KodNest Technologies", item_title_left),
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

        doc.build(story)
        logger.info(f"📄 Generated ATS Authentic 2+Yrs PDF: {output_path}")
        return str(output_path)

    def generate_tailored_resume(
        self,
        job: dict,
        candidate_profile: dict = None,
        exp_years: float = 1.5,
        portal: str = "",
    ) -> str:
        """
        Generate and save tailored ATS 1-page PDF resume.
        Chooses Template 1 (1.5Yrs) or Template 2 (2+Yrs) based on exp_years.
        Saves to resumes/<portal>/ (e.g. resumes/cutshort/, resumes/hirist/, etc.).
        """
        job_id = job.get("id", int(time.time()))
        job_title = job.get("title", "Software Engineer")
        company = job.get("company", "Company")
        job_desc = job.get("description", "")
        resolved_portal = portal or job.get("portal") or ""
        if not resolved_portal and isinstance(job_id, str) and "_" in job_id:
            resolved_portal = job_id.split("_")[0].lower()

        tailored_data = self._generate_fallback_tailored_data(job_title, company, job_desc, exp_years=exp_years)

        if exp_years >= 2.0:
            return self.generate_pdf_2_plus_years(job_id, job_title, company, tailored_data, portal=resolved_portal)
        else:
            return self.generate_pdf_1_5_years(job_id, job_title, company, tailored_data, portal=resolved_portal)

    def create_tailored_resume(
        self,
        job_id: int,
        job_title: str,
        company: str,
        job_description: str,
        exp_years: float = 1.5,
        portal: str = "",
    ) -> str:
        """
        Full pipeline: generate tailored resume data → create authentic 1-page PDF.
        """
        resolved_portal = portal or ""
        if not resolved_portal and isinstance(job_id, str) and "_" in job_id:
            resolved_portal = job_id.split("_")[0].lower()

        try:
            tailored_data = self.tailor_resume(job_id, job_title, company, job_description)
            if not tailored_data:
                tailored_data = self._generate_fallback_tailored_data(job_title, company, job_description, exp_years=exp_years)

            if exp_years >= 2.0:
                return self.generate_pdf_2_plus_years(job_id, job_title, company, tailored_data, portal=resolved_portal)
            else:
                return self.generate_pdf_1_5_years(job_id, job_title, company, tailored_data, portal=resolved_portal)

        except Exception as e:
            logger.warning(f"Tailoring failed for job {job_id} ({e}) — generating dynamic authentic PDF")
            fallback_data = self._generate_fallback_tailored_data(job_title, company, job_description, exp_years=exp_years)
            if exp_years >= 2.0:
                return self.generate_pdf_2_plus_years(job_id, job_title, company, fallback_data, portal=resolved_portal)
            else:
                return self.generate_pdf_1_5_years(job_id, job_title, company, fallback_data, portal=resolved_portal)

