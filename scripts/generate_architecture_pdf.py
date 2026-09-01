"""
Generate Comprehensive Architecture, Workflow, and Directory Structure PDF for AI Job Agent.
Outputs a beautifully styled, multi-page professional PDF document.
"""
import os
import sys
from pathlib import Path
from datetime import datetime

# Configure Windows UTF-8 console output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

# Colors
PRIMARY = colors.HexColor("#1A365D")    # Deep Navy
SECONDARY = colors.HexColor("#2B6CB0")  # Slate Blue
ACCENT = colors.HexColor("#319795")     # Teal Accent
DARK_TEXT = colors.HexColor("#2D3748")  # Charcoal
LIGHT_BG = colors.HexColor("#F7FAFC")   # Off-white / light slate
BORDER_COLOR = colors.HexColor("#E2E8F0")
GREEN_COLOR = colors.HexColor("#2F855A")
YELLOW_COLOR = colors.HexColor("#D69E2E")
RED_COLOR = colors.HexColor("#C53030")


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and display total page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#718096"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 11 * inch - 36, "Autonomous AI Job Agent — Complete Architecture & Workflow Blueprint")
            self.setStrokeColor(BORDER_COLOR)
            self.setLineWidth(0.5)
            self.line(54, 11 * inch - 42, 8.5 * inch - 54, 11 * inch - 42)

        # Footer (all pages)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * inch - 54, 36, page_text)
        self.drawString(54, 36, f"Confidential & Proprietary — Generated for Kamal Kumar | {datetime.now().strftime('%B %d, %Y')}")
        self.setStrokeColor(BORDER_COLOR)
        self.setLineWidth(0.5)
        self.line(54, 46, 8.5 * inch - 54, 46)

        self.restoreState()


def build_pdf(filename: str):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=PRIMARY,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=SECONDARY,
        spaceAfter=15,
    )
    h1_style = ParagraphStyle(
        "SectionH1",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=PRIMARY,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        textColor=SECONDARY,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=DARK_TEXT,
        spaceAfter=6,
    )
    body_bold = ParagraphStyle(
        "DocBodyBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    bullet_style = ParagraphStyle(
        "DocBullet",
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3,
    )
    code_style = ParagraphStyle(
        "DocCode",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#2C5282"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=DARK_TEXT,
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.white,
    )

    story = []

    # =========================================================================
    # HEADER BANNER & TITLE
    # =========================================================================
    story.append(Paragraph("AI Job Agent: System Architecture & Workflow Blueprint", title_style))
    story.append(Paragraph("End-to-End Autonomous Job Discovery, AI Scoring, Dynamic ATS Tailoring & Multi-Mode Application System", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=2, spaceAfter=14))

    # Meta Overview Box
    meta_data = [
        [
            Paragraph("<b>Target Candidate:</b> Kamal Kumar", table_cell),
            Paragraph("<b>Primary Tech Stack:</b> Java, Spring Boot, Python, FastAPI, AWS, Docker, AI", table_cell),
        ],
        [
            Paragraph("<b>Experience Level:</b> 0 to 2 Years ONLY (Junior / Entry-Level)", table_cell),
            Paragraph("<b>Active Connectors:</b> 16 Sources across APIs, ATS, & Social Posts", table_cell),
        ],
        [
            Paragraph("<b>Execution Cycle:</b> 24/7 Fixed Runs (06:00, 12:00, 18:00, 00:00 IST)", table_cell),
            Paragraph("<b>Core Framework:</b> LangGraph + FastAPI + Playwright + Gemini AI", table_cell),
        ]
    ]
    meta_table = Table(meta_data, colWidths=[240, 264])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))

    # =========================================================================
    # 1. EXECUTIVE OVERVIEW & ARCHITECTURAL PHILOSOPHY
    # =========================================================================
    story.append(Paragraph("1. Executive Overview & Architecture", h1_style))
    story.append(Paragraph(
        "The <b>AI Job Agent</b> is an enterprise-grade, autonomous job application ecosystem designed to solve the challenges of modern technical hiring. "
        "Unlike generic scrapers or basic autofill bots, this system provides a <b>resilient, 6-stage LangGraph workflow</b> powered by Google Gemini AI, "
        "strict heuristic experience filters, dynamic 1-page ATS PDF generation, and a Source-Aware 3-Mode Application Engine.",
        body_style
    ))
    story.append(Paragraph(
        "<b>Core Architectural Pillars:</b>", body_style
    ))
    story.append(Paragraph("• <b>Multi-Channel Ingestion:</b> Concurrently queries 16 diverse job sources including enterprise ATS endpoints (Greenhouse, Lever, Ashby, Workday), public remote job APIs (Jobicy, Remotive, Himalayas, Adzuna), and social recruiter posts (LinkedIn, HackerNews).", bullet_style))
    story.append(Paragraph("• <b>Zero-Tolerance Experience Guard:</b> A multi-layer heuristic and semantic filter that automatically hard-blocks any role requiring &gt;2 years of experience or containing senior/lead keywords before expensive LLM processing.", bullet_style))
    story.append(Paragraph("• <b>100% Unique Dynamic ATS Resumes:</b> For every qualifying role, Gemini extracts required skills and dynamically compiles a bespoke single-page PDF resume using ReportLab Platypus.", bullet_style))
    story.append(Paragraph("• <b>Source-Aware 3-Mode Application Policy:</b> Distinguishes between programmatic ATS APIs, persistent browser automation, verified HR email outreach, and 1-click manual links.", bullet_style))
    story.append(Paragraph("• <b>Real-Time Multi-Channel Telemetry:</b> Delivers instant daily summaries and high-match alerts via WhatsApp (CallMeBot / Meta Cloud API) and styled multi-tab Excel workbooks.", bullet_style))

    story.append(Spacer(1, 10))

    # =========================================================================
    # 2. 6-STAGE LANGGRAPH PIPELINE WORKFLOW
    # =========================================================================
    story.append(Paragraph("2. 6-Stage LangGraph Pipeline Workflow", h1_style))
    story.append(Paragraph(
        "The pipeline is implemented as a deterministic <b>LangGraph StateGraph</b>. The agent state passes sequentially through 6 specialized nodes:",
        body_style
    ))

    pipeline_nodes = [
        [
            Paragraph("<b>Stage & Node</b>", table_header),
            Paragraph("<b>Primary Responsibilities</b>", table_header),
            Paragraph("<b>Outputs & Artifacts</b>", table_header),
        ],
        [
            Paragraph("<b>Node 1: Ingestion</b><br/><code>fetch_node</code>", table_cell),
            Paragraph("• Concurrently polls 16 job connectors.<br/>• Extracts title, company, location, JD, and URL.<br/>• SQLite SHA-256 deduplication against past runs.", table_cell),
            Paragraph("• <code>raw_jobs</code> list<br/>• <code>new_jobs_count</code><br/>• Saved in SQLite DB", table_cell),
        ],
        [
            Paragraph("<b>Node 2: AI Scoring</b><br/><code>score_node</code>", table_cell),
            Paragraph("• <b>Stage 1:</b> Heuristic pre-scoring & 0-2 yrs hard guard.<br/>• <b>Stage 2:</b> Gemini AI semantic scoring (0-100).<br/>• Evaluates skill overlap, experience fit, and role match.", table_cell),
            Paragraph("• <code>scored_jobs</code> list<br/>• <code>qualified_job_ids</code><br/>• Match score (0-100)", table_cell),
        ],
        [
            Paragraph("<b>Node 3: ATS Resume</b><br/><code>resume_node</code>", table_cell),
            Paragraph("• Extracts tech keywords from target job description.<br/>• Gemini tailors summary, skill badges, and bullet points.<br/>• Builds ATS single-page PDF via ReportLab Platypus.", table_cell),
            Paragraph("• <code>resume_paths</code> map<br/>• Tailored PDF in <code>resumes/</code>", table_cell),
        ],
        [
            Paragraph("<b>Node 4: Apply Engine</b><br/><code>apply_node</code>", table_cell),
            Paragraph("• Evaluates Source-Aware 3-Mode policy.<br/>• Executes Mode 1 API, Mode 2 Persistent Browser, or Mode 3 HR Email.<br/>• Prepares 1-click link for anti-bot aggregator portals.", table_cell),
            Paragraph("• <code>direct_applied</code> count<br/>• <code>emails_sent</code> count<br/>• DB status: <code>APPLIED</code>", table_cell),
        ],
        [
            Paragraph("<b>Node 5: WhatsApp</b><br/><code>notify_node</code>", table_cell),
            Paragraph("• Formats clean daily WhatsApp summary.<br/>• Sends top-3 job match alerts with scores & links.<br/>• Supports CallMeBot free instant API & Meta Cloud API.", table_cell),
            Paragraph("• WhatsApp message delivered<br/>• <code>whatsapp_sent=True</code>", table_cell),
        ],
        [
            Paragraph("<b>Node 6: Reporting</b><br/><code>report_node</code>", table_cell),
            Paragraph("• Compiles multi-tab Excel workbook via <code>openpyxl</code>.<br/>• Tabs: <i>All Discovered</i>, <i>Qualified Matches</i>, <i>Applications</i>.<br/>• Saves daily report with clickable direct URLs.", table_cell),
            Paragraph("• <code>JobReport_YYYY-MM-DD.xlsx</code><br/>• Stored in <code>reports/</code>", table_cell),
        ],
    ]

    pipeline_table = Table(pipeline_nodes, colWidths=[110, 244, 150])
    pipeline_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(pipeline_table)

    story.append(PageBreak())

    # =========================================================================
    # 3. 16 JOB CONNECTORS & INGESTION ARCHITECTURE
    # =========================================================================
    story.append(Paragraph("3. 16 Active Job Connectors & Ingestion Layer", h1_style))
    story.append(Paragraph(
        "The agent integrates with 16 distinct connectors managed by a centralized <code>ConnectorManager</code>. "
        "Connectors execute asynchronously with error isolation — if a single third-party endpoint fails or rate-limits, "
        "the remaining 15 connectors continue uninterrupted.",
        body_style
    ))

    connectors_data = [
        [
            Paragraph("<b>Connector Name</b>", table_header),
            Paragraph("<b>Source / Portal</b>", table_header),
            Paragraph("<b>Type & Protocol</b>", table_header),
            Paragraph("<b>Target Domain</b>", table_header),
        ],
        [
            Paragraph("<code>GreenhouseConnector</code>", table_cell),
            Paragraph("Greenhouse Enterprise ATS", table_cell),
            Paragraph("Public REST API (JSON)", table_cell),
            Paragraph("Airbnb, Stripe, Brex, Discord, Figma", table_cell),
        ],
        [
            Paragraph("<code>LeverConnector</code>", table_cell),
            Paragraph("Lever Enterprise ATS", table_cell),
            Paragraph("Public REST API (JSON)", table_cell),
            Paragraph("Netflix, Spotify, Wealthsimple", table_cell),
        ],
        [
            Paragraph("<code>AshbyConnector</code>", table_cell),
            Paragraph("Ashby Modern ATS", table_cell),
            Paragraph("Posting REST API", table_cell),
            Paragraph("Linear, Supabase, Retool, Vercel", table_cell),
        ],
        [
            Paragraph("<code>WorkdayConnector</code>", table_cell),
            Paragraph("Workday CXS Portal", table_cell),
            Paragraph("CXS Search API / HTTP", table_cell),
            Paragraph("Walmart, Target, Flipkart, Adobe", table_cell),
        ],
        [
            Paragraph("<code>SmartRecruitersConnector</code>", table_cell),
            Paragraph("SmartRecruiters ATS", table_cell),
            Paragraph("REST API", table_cell),
            Paragraph("Freshworks, Visa, Bosch", table_cell),
        ],
        [
            Paragraph("<code>JobicyConnector</code>", table_cell),
            Paragraph("Jobicy Remote Jobs", table_cell),
            Paragraph("Public Jobs API", table_cell),
            Paragraph("Global Remote Software & AI Roles", table_cell),
        ],
        [
            Paragraph("<code>RemotiveConnector</code>", table_cell),
            Paragraph("Remotive Software API", table_cell),
            Paragraph("Public Category API", table_cell),
            Paragraph("Backend, Cloud & AI Engineering", table_cell),
        ],
        [
            Paragraph("<code>HimalayasConnector</code>", table_cell),
            Paragraph("Himalayas Remote", table_cell),
            Paragraph("Public REST API", table_cell),
            Paragraph("Modern Tech Startups & Scaleups", table_cell),
        ],
        [
            Paragraph("<code>AdzunaConnector</code>", table_cell),
            Paragraph("Adzuna India & Global", table_cell),
            Paragraph("Developer REST API", table_cell),
            Paragraph("India Tech Market (Java/Python/AI)", table_cell),
        ],
        [
            Paragraph("<code>AgentReachConnector</code>", table_cell),
            Paragraph("Agent Reach LinkedIn", table_cell),
            Paragraph("CLI / Headless Protocol", table_cell),
            Paragraph("LinkedIn Posts & Direct Roles", table_cell),
        ],
        [
            Paragraph("<code>LinkedInPostsConnector</code>", table_cell),
            Paragraph("LinkedIn Hiring Posts", table_cell),
            Paragraph("Direct HR Post Scraper", table_cell),
            Paragraph("Recruiter Cold Hiring Posts", table_cell),
        ],
        [
            Paragraph("<code>YCombinatorConnector</code>", table_cell),
            Paragraph("WorkAtAStartup / YC", table_cell),
            Paragraph("HackerNews Algolia API", table_cell),
            Paragraph("YC Backed High-Growth Startups", table_cell),
        ],
        [
            Paragraph("<code>WellfoundConnector</code>", table_cell),
            Paragraph("Wellfound (AngelList)", table_cell),
            Paragraph("Public RSS / Discovery", table_cell),
            Paragraph("Early-Stage & Seed AI Startups", table_cell),
        ],
        [
            Paragraph("<code>ArbeitnowConnector</code>", table_cell),
            Paragraph("Arbeitnow Tech", table_cell),
            Paragraph("REST API", table_cell),
            Paragraph("European & Remote Tech Roles", table_cell),
        ],
        [
            Paragraph("<code>WeWorkRemotelyConnector</code>", table_cell),
            Paragraph("We Work Remotely", table_cell),
            Paragraph("RSS & JSON Feed", table_cell),
            Paragraph("Remote Backend & Systems Roles", table_cell),
        ],
        [
            Paragraph("<code>RemoteOKConnector</code>", table_cell),
            Paragraph("RemoteOK", table_cell),
            Paragraph("Public REST API", table_cell),
            Paragraph("Global Remote Tech & Fullstack", table_cell),
        ],
    ]

    conn_table = Table(connectors_data, colWidths=[130, 114, 110, 150])
    conn_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), SECONDARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(conn_table)

    story.append(Spacer(1, 10))

    # =========================================================================
    # 4. SOURCE-AWARE 3-MODE APPLICATION POLICY & EXPERIENCE GUARD
    # =========================================================================
    story.append(Paragraph("4. Source-Aware Application Policy & Experience Guard", h1_style))
    story.append(Paragraph(
        "The agent implements a <b>Source-Aware Multi-Mode Application Architecture</b> to interact appropriately with each portal type:",
        body_style
    ))

    modes_data = [
        [
            Paragraph("<b>Mode</b>", table_header),
            Paragraph("<b>Strategy & Channel</b>", table_header),
            Paragraph("<b>Supported Platforms</b>", table_header),
            Paragraph("<b>Behavior & Automation Logic</b>", table_header),
        ],
        [
            Paragraph("<b>🟢 Mode 1</b><br/>Direct API", table_cell),
            Paragraph("Programmatic ATS Form Submission", table_cell),
            Paragraph("Greenhouse, Lever, Ashby", table_cell),
            Paragraph("Submits multipart/form-data with candidate profile, questions, and tailored ATS resume PDF directly via official API.", table_cell),
        ],
        [
            Paragraph("<b>🟡 Mode 2</b><br/>Persistent Browser", table_cell),
            Paragraph("Playwright Persistent Context", table_cell),
            Paragraph("Wellfound, YCombinator, LinkedIn, Workday, Jobicy", table_cell),
            Paragraph("Reuses authenticated local browser profile (<code>data/browser_profile</code>). Auto-fills forms, uploads resume PDF, and auto-submits without password leakage.", table_cell),
        ],
        [
            Paragraph("<b>✉️ Mode 3</b><br/>Verified HR Email", table_cell),
            Paragraph("Direct Recruiter Outreach via Gmail API", table_cell),
            Paragraph("LinkedIn Posts, HackerNews hiring threads", table_cell),
            Paragraph("<b>Zero Bounce Policy:</b> Sends cold application ONLY when an explicit recruiter email is parsed from the post. Never guesses synthetic addresses.", table_cell),
        ],
        [
            Paragraph("<b>🔴 Mode 4</b><br/>1-Click Link Prep", table_cell),
            Paragraph("Custom Resume & Direct Link Preparation", table_cell),
            Paragraph("Adzuna, Hirist, Shine, Cutshort, Foundit", table_cell),
            Paragraph("Generates custom ATS resume PDF, drafts cover note, and formats 1-click direct application link in the daily Excel report.", table_cell),
        ],
    ]

    modes_table = Table(modes_data, colWidths=[70, 110, 120, 204])
    modes_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(modes_table)

    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Strict Match Score Policy:</b>", body_bold))
    story.append(Paragraph("• <b>Score ≥ 85:</b> <code>AUTO_APPLY</code> — Programmatic submission via Mode 1 (API) or Mode 2 (Persistent Browser).", bullet_style))
    story.append(Paragraph("• <b>Score 75–84:</b> <code>REVIEW_REQUIRED</code> — Custom ATS resume PDF generated + draft saved for 1-click submission.", bullet_style))
    story.append(Paragraph("• <b>Score 65–74:</b> <code>SAVE_LINK</code> — Job details, cover letter draft, and direct URL saved in Excel report.", bullet_style))
    story.append(Paragraph("• <b>Score &lt; 65:</b> <code>SKIP</code> — Discarded from scoring queue.", bullet_style))

    story.append(PageBreak())

    # =========================================================================
    # 5. COMPLETE DIRECTORY & CODEBASE STRUCTURE
    # =========================================================================
    story.append(Paragraph("5. Complete Project Directory & Codebase Structure", h1_style))
    story.append(Paragraph(
        "Below is the complete file tree and architectural module map of the <code>AI-Job-Agent</code> codebase:",
        body_style
    ))

    tree_text = """AI-Job-Agent/
├── app/
│   ├── agents/                   # LangGraph StateGraph & Node Orchestrators
│   │   ├── __init__.py           # Agent package exports
│   │   ├── nodes.py              # 6 Pipeline Nodes (fetch, score, resume, apply, notify, report)
│   │   ├── orchestrator.py       # LangGraph StateGraph compilation & execution graph
│   │   └── state.py              # AgentState TypedDict schema definition
│   ├── config/                   # Centralized Configuration & Environment Settings
│   │   ├── __init__.py           # Config exports
│   │   └── settings.py           # Environment variables, candidate profile, score thresholds
│   ├── connectors/               # 16 Job Search Ingestion Connectors
│   │   ├── __init__.py           # Connector package registry
│   │   ├── base.py               # BaseConnector abstract class interface
│   │   ├── manager.py            # ConnectorManager concurrent aggregator
│   │   ├── registry.py           # Connector auto-discovery decorator
│   │   ├── greenhouse_connector.py # Greenhouse ATS REST API connector
│   │   ├── lever_connector.py      # Lever ATS REST API connector
│   │   ├── ashby_connector.py      # Ashby ATS REST API connector
│   │   ├── workday_connector.py    # Workday CXS Search API connector
│   │   ├── smartrecruiters_connector.py # SmartRecruiters ATS connector
│   │   ├── jobicy_connector.py     # Jobicy Remote Jobs API connector
│   │   ├── remotive_connector.py   # Remotive Software Jobs API connector
│   │   ├── himalayas_connector.py  # Himalayas Remote API connector
│   │   ├── adzuna_connector.py     # Adzuna Developer Jobs API connector
│   │   ├── agent_reach_connector.py # Agent Reach LinkedIn scraper
│   │   ├── linkedin_posts_connector.py # LinkedIn Recruiter Hiring Posts parser
│   │   ├── ycombinator_connector.py # HackerNews / YC Who is Hiring Algolia API
│   │   ├── wellfound_connector.py  # Wellfound (AngelList Talent) connector
│   │   ├── arbeitnow_connector.py  # Arbeitnow Tech Jobs API connector
│   │   └── weworkremotely_connector.py # WeWorkRemotely RSS feed connector
│   ├── db/                       # Database Storage & Repository Layer
│   │   ├── __init__.py           # DB models & session exports
│   │   ├── models.py             # SQLAlchemy ORM models (Job, Application, Resume, RunLog)
│   │   └── session.py            # SQLite engine & scoped session factory (jobs.db)
│   ├── prompts/                  # LLM Prompt Templates & System Personas
│   │   ├── __init__.py           # Prompts package
│   │   ├── email_prompt.py       # Cold outreach email generation prompt
│   │   ├── resume_prompt.py      # Dynamic ATS resume tailoring prompt
│   │   └── scoring_prompt.py     # Strict 0-2 yrs technical job scoring prompt
│   ├── schemas/                  # Pydantic Schemas & Data Transfer Objects
│   │   ├── __init__.py           # Schemas package
│   │   ├── application.py        # Application status & tracking schema
│   │   └── job_data.py           # Unified JobData dataclass
│   ├── services/                 # Core Business Logic & AI Services
│   │   ├── __init__.py           # Services package exports
│   │   ├── application_policy.py # Source-Aware 3-Mode Application Strategy Manager
│   │   ├── apply_service.py      # Application submission cascade & routing service
│   │   ├── browser_apply_service.py # Playwright Chromium persistent browser auto-apply
│   │   ├── email_service.py      # Gmail API OAuth2 cold outreach sender
│   │   ├── mock_scoring_service.py # Heuristic pre-filter & keyword scoring engine
│   │   ├── report_service.py     # openpyxl multi-tab Excel report generator
│   │   ├── resume_service.py     # Dynamic ATS 1-page PDF builder (ReportLab Platypus)
│   │   ├── scheduler_service.py  # APScheduler 24/7 fixed 6-hour cron service
│   │   ├── scoring_service.py    # Google Gemini AI LLM semantic scoring service
│   │   └── whatsapp_service.py   # CallMeBot & Meta Cloud WhatsApp alert service
│   └── utils/                    # Shared Helper Functions & Validators
│       ├── __init__.py           # Utils package
│       ├── email_validator.py    # Explicit HR email regex parser & DNS validator
│       ├── experience_filter.py  # Strict 0-2 years experience & senior title hard-guard
│       └── gemini_client.py      # Resilient Gemini API client with auto-retry
├── data/                         # Persistent Storage & Browser Profiles
│   ├── browser_profile/          # Playwright persistent Chromium context & cookies
│   └── jobs.db                   # SQLite primary database
├── docs/                         # Architecture Documentation & PDF Blueprints
├── reports/                      # Daily Excel Workbooks (JobReport_YYYY-MM-DD.xlsx)
├── resumes/                      # Master Resume & Tailored ATS PDF Resumes
│   └── Kamal_Kumar_Java_AI_Developer_ATS.pdf # Candidate Master Resume
├── scripts/                      # Diagnostic, Testing, & Execution Tools
│   ├── run_agent.py              # CLI runner for single pipeline execution
│   ├── test_browser_apply.py     # Live visible browser auto-apply tester
│   ├── setup_gmail_token.py      # Gmail OAuth2 token generator
│   ├── setup_whatsapp.py         # WhatsApp CallMeBot diagnostic tool
│   └── generate_architecture_pdf.py # Architecture blueprint PDF generator
├── main.py                       # FastAPI 24/7 Web Server & Background Scheduler Entrypoint
├── requirements.txt              # Production Python dependencies
└── .env                          # Configuration & API Credentials
"""

    tree_table = Table([[Paragraph(f"<pre>{tree_text}</pre>", code_style)]], colWidths=[504])
    tree_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(tree_table)

    story.append(PageBreak())

    # =========================================================================
    # 6. SERVER LIFECYCLE & 24/7 OPERATION
    # =========================================================================
    story.append(Paragraph("6. Server Lifecycle, Scheduling, & API Endpoints", h1_style))
    story.append(Paragraph(
        "The application runs 24/7 as a <b>FastAPI service</b> with an embedded <b>APScheduler</b> background engine. "
        "It provides complete observability through REST API endpoints and automatic periodic executions.",
        body_style
    ))

    api_endpoints = [
        [
            Paragraph("<b>HTTP Method & Endpoint</b>", table_header),
            Paragraph("<b>Description & Functionality</b>", table_header),
            Paragraph("<b>Sample Response / Action</b>", table_header),
        ],
        [
            Paragraph("<code>GET /</code>", table_cell),
            Paragraph("System health check, version, and scheduler status.", table_cell),
            Paragraph("<code>{'status': 'running', 'scheduler': True}</code>", table_cell),
        ],
        [
            Paragraph("<code>POST /agent/run</code>", table_cell),
            Paragraph("Triggers an immediate background run across all 16 connectors.", table_cell),
            Paragraph("<code>{'status': 'started', 'run_id': '41fee100'}</code>", table_cell),
        ],
        [
            Paragraph("<code>GET /agent/status</code>", table_cell),
            Paragraph("Retrieves the execution status and statistics of the latest run.", table_cell),
            Paragraph("<code>{'last_run_time': '...', 'jobs_found': 3539}</code>", table_cell),
        ],
        [
            Paragraph("<code>GET /jobs/qualified</code>", table_cell),
            Paragraph("Lists all qualified matches (score ≥ 65) matching 0-2 yrs target.", table_cell),
            Paragraph("<code>[{'title': 'Java Dev', 'score': 85}, ...]</code>", table_cell),
        ],
        [
            Paragraph("<code>GET /jobs/stats</code>", table_cell),
            Paragraph("Summary statistics of discovered, scored, and applied jobs.", table_cell),
            Paragraph("<code>{'total_jobs': 3539, 'applied': 12}</code>", table_cell),
        ],
        [
            Paragraph("<code>GET /docs</code>", table_cell),
            Paragraph("Interactive Swagger UI for testing API endpoints.", table_cell),
            Paragraph("Interactive Web Interface", table_cell),
        ],
    ]

    api_table = Table(api_endpoints, colWidths=[130, 210, 164])
    api_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(api_table)

    story.append(Spacer(1, 14))

    # =========================================================================
    # 7. SUMMARY & VALUE DELIVERED
    # =========================================================================
    story.append(Paragraph("7. Architectural Summary & Production Readiness", h1_style))
    story.append(Paragraph(
        "With this architecture, the <b>AI Job Agent</b> functions as an autonomous career assistant that discovers thousands of opportunities daily, "
        "filters with strict 0–2 years precision, tailors ATS resumes on the fly, applies across multiple channels without password exposure, and keeps the candidate informed 24/7.",
        body_style
    ))

    # Highlight Summary Box
    summary_box_data = [
        [
            Paragraph("<b>✅ Multi-Source Discovery:</b> 16 integrated sources querying 3,500+ jobs per cycle.", table_cell),
            Paragraph("<b>✅ 0-2 Years Precision:</b> Hard guards eliminate all &gt;2 yrs & senior roles.", table_cell),
        ],
        [
            Paragraph("<b>✅ Zero Email Bounces:</b> Strictly emails explicit recruiter contacts from posts.", table_cell),
            Paragraph("<b>✅ 100% Unique Resumes:</b> Tailored ATS single-page PDFs per application.", table_cell),
        ],
        [
            Paragraph("<b>✅ Safe Browser Sessions:</b> Persistent cookies reuse without password leaks.", table_cell),
            Paragraph("<b>✅ Daily Multi-Channel Alerts:</b> Automated WhatsApp alerts & Excel reports.", table_cell),
        ]
    ]
    summary_table = Table(summary_box_data, colWidths=[252, 252])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, SECONDARY),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)

    # Build PDF with NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✅ Architecture PDF successfully generated: {filename}")


if __name__ == "__main__":
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    pdf_path = str(docs_dir / "AI_Job_Agent_Architecture_and_Workflow.pdf")
    build_pdf(pdf_path)
