"""
Generate Comprehensive Architecture, Workflow, and Directory Structure PDF for AI Job Agent.
Incorporates the complete architectural blueprint, pipeline diagrams, YAML source configuration,
ExperienceAnalyzer, and weighted scoring formulas from the master system design.
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

# Theme Palette
PRIMARY = colors.HexColor("#0F294A")    # Deep Navy
SECONDARY = colors.HexColor("#1E4E8C")  # Indigo Blue
ACCENT = colors.HexColor("#0D9488")     # Emerald Teal
DARK_TEXT = colors.HexColor("#1F2937")  # Slate Gray
LIGHT_BG = colors.HexColor("#F8FAFC")   # Clean Canvas Off-white
BORDER_COLOR = colors.HexColor("#E2E8F0")
CARD_BG = colors.HexColor("#EDF2F7")


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
        self.setFillColor(colors.HexColor("#64748B"))

        # Header on pages > 1
        if self._pageNumber > 1:
            self.drawString(54, 11 * inch - 36, "AI Job Agent — Master Workflow, Architecture & Directory Blueprint")
            self.setStrokeColor(BORDER_COLOR)
            self.setLineWidth(0.5)
            self.line(54, 11 * inch - 42, 8.5 * inch - 54, 11 * inch - 42)

        # Footer on all pages
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * inch - 54, 36, page_text)
        self.drawString(54, 36, f"Master System Architecture — Prepared for Kamal Kumar | {datetime.now().strftime('%B %d, %Y')}")
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

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=PRIMARY,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=SECONDARY,
        spaceAfter=12,
    )
    h1_style = ParagraphStyle(
        "SectionH1",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=PRIMARY,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=SECONDARY,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=DARK_TEXT,
        spaceAfter=5,
    )
    body_bold = ParagraphStyle(
        "DocBodyBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    bullet_style = ParagraphStyle(
        "DocBullet",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=2.5,
    )
    code_style = ParagraphStyle(
        "DocCode",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#1E3A8A"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=DARK_TEXT,
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white,
    )

    story = []

    # =========================================================================
    # HEADER BANNER & TITLE
    # =========================================================================
    story.append(Paragraph("AI Job Agent: Master Architecture & Workflow Blueprint", title_style))
    story.append(Paragraph("End-to-End Autonomous Job Discovery, Multi-Tier Scoring, Dynamic ATS Tailoring & Multi-Mode Applications", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=2, spaceAfter=10))

    # Meta Overview Box
    meta_data = [
        [
            Paragraph("<b>Target Candidate:</b> Kamal Kumar", table_cell),
            Paragraph("<b>Core Stack:</b> Java, Spring Boot, Python, FastAPI, AWS, Docker, AI Agents", table_cell),
        ],
        [
            Paragraph("<b>Target Experience:</b> 0 to 2 Years ONLY (Strict Entry-Level)", table_cell),
            Paragraph("<b>Source Registry:</b> 16 Active Connectors (APIs, ATS, Social Posts)", table_cell),
        ],
        [
            Paragraph("<b>Scheduler Cycle:</b> 24/7 Runs Every 6 Hours (06:00, 12:00, 18:00, 00:00 IST)", table_cell),
            Paragraph("<b>Frameworks:</b> LangGraph + FastAPI + Playwright + Gemini AI + openpyxl", table_cell),
        ]
    ]
    meta_table = Table(meta_data, colWidths=[240, 264])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # =========================================================================
    # 1. MASTER WORKFLOW & PIPELINE ARCHITECTURE
    # =========================================================================
    story.append(Paragraph("1. Master Workflow & Pipeline Architecture", h1_style))
    story.append(Paragraph(
        "The system follows a strict, non-bypassable sequential pipeline from multi-channel discovery to telemetry dispatch. "
        "Every job must pass through each validation gate before reaching the application stage:",
        body_style
    ))

    flow_diagram = """
                       ┌────────────────────────────────────────────────┐
                       │                  AI JOB AGENT                  │
                       └───────────────────────┬────────────────────────┘
                                               │
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │                 SEARCH MANAGER                 │
                       │    (Reads config/job_sources.yml Registry)     │
                       └───────┬───────────────┬────────────────┬───────┘
                               │               │                │
            ┌──────────────────┴──┐   ┌────────┴────────┐  ┌────┴─────────────────┐
            │ GLOBAL REMOTE JOBS  │   │   INDIAN JOBS   │  │ RECRUITER POSTS (HR) │
            │ (Jobicy, Remotive,  │   │ (Adzuna, Naukri,│  │ (LinkedIn Posts,     │
            │  YC, Wellfound, ATS)│   │  Foundit, Shine)│  │  HackerNews Threads) │
            └──────────────────┬──┘   └────────┬────────┘  └────┬─────────────────┘
                               └───────────────┼────────────────┘
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │          JOB NORMALIZER & DEDUPLICATOR         │
                       │ (Builds Unified JobData & SQLite SHA-256 Check)│
                       └───────────────────────┬────────────────────────┘
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │       TODAY & FRESHNESS FILTER (0-24 Hrs)      │
                       └───────────────────────┬────────────────────────┘
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │  EXPERIENCE ANALYZER (Strict 0-2 Years ONLY)   │
                       │ (Hard-Blocks >=3 Yrs & Senior/Lead/Mgr Titles) │
                       └───────────────────────┬────────────────────────┘
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │     2-TIER SCORER: ROLE & SKILL AI MATCHER     │
                       │   (30% Role + 25% Exp + 25% Skill + 20% Fit)   │
                       └───────────────────────┬────────────────────────┘
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │           QUALIFIED MATCHES (Score >= 65)      │
                       └───────┬────────────────────────────────┬───────┘
                               │                                │
            ┌──────────────────┴──┐                   ┌─────────┴─────────────┐
            │   NORMAL JOB POST   │                   │ RECRUITER POST (EMAIL)│
            └──────────┬──────────┘                   └─────────┬─────────────┘
                       │                                        │
                       │ ┌────────────────────────────────────┐ │
                       └─► DYNAMIC ATS RESUME PDF TAILORING   ◄─┘
                         └─────────────────┬──────────────────┘
                                           │
                         ┌─────────────────┴──────────────────┐
                         │   SOURCE-AWARE APPLICATION ENGINE  │
                         └─┬───────────────┬────────────────┬─┘
                           │               │                │
            ┌──────────────┴───┐ ┌─────────┴────────┐ ┌─────┴───────────────┐
            │ 🟢 MODE 1:       │ │ 🟡 MODE 2:       │ │ ✉️ MODE 3:          │
            │ DIRECT ATS API   │ │ PLAYWRIGHT       │ │ VERIFIED RECRUITER  │
            │ (Greenhouse/Lever│ │ PERSISTENT       │ │ EMAIL OUTREACH      │
            │  /Ashby Submit)  │ │ BROWSER AUTO-FILL│ │ (Gmail API OAuth)   │
            └──────────────────┘ └──────────────────┘ └─────────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────────────┐
                       │            MULTI-CHANNEL TELEMETRY             │
                       │  • WhatsApp Daily Report & Top Match Alerts    │
                       │  • Multi-Tab Excel Workbook (openpyxl)         │
                       │  • Email Application Tracking Log              │
                       └────────────────────────────────────────────────┘
    """

    flow_table = Table([[Paragraph(f"<pre>{flow_diagram}</pre>", code_style)]], colWidths=[504])
    flow_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(flow_table)

    story.append(PageBreak())

    # =========================================================================
    # 2. SOURCE CONFIGURATION YAML & CONNECTOR REGISTRY
    # =========================================================================
    story.append(Paragraph("2. Dynamic Source Configuration (job_sources.yml)", h1_style))
    story.append(Paragraph(
        "Instead of hardcoding source logic in Python, the agent loads <code>app/config/job_sources.yml</code> at runtime. "
        "Sources can be toggled on/off and prioritized dynamically without code modifications:",
        body_style
    ))

    yml_sample = """# app/config/job_sources.yml
sources:
  greenhouse:      { enabled: true, type: career_page,    priority: high }
  lever:           { enabled: true, type: career_page,    priority: high }
  ashby:           { enabled: true, type: career_page,    priority: high }
  workday:         { enabled: true, type: career_page,    priority: high }
  smartrecruiters: { enabled: true, type: career_page,    priority: high }
  jobicy:          { enabled: true, type: remote,         priority: high }
  remotive:        { enabled: true, type: remote,         priority: high }
  himalayas:       { enabled: true, type: remote,         priority: high }
  adzuna:          { enabled: true, type: job_board,      priority: high }
  agent_reach:     { enabled: true, type: recruiter_post, priority: high }
  linkedin_posts:  { enabled: true, type: recruiter_post, priority: high }
  ycombinator:     { enabled: true, type: remote,         priority: high }
  wellfound:       { enabled: true, type: remote,         priority: high }
  arbeitnow:       { enabled: true, type: remote,         priority: medium }
  weworkremotely:  { enabled: true, type: remote,         priority: medium }
  remoteok:        { enabled: true, type: remote,         priority: medium }
"""

    yml_table = Table([[Paragraph(f"<pre>{yml_sample}</pre>", code_style)]], colWidths=[504])
    yml_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(yml_table)
    story.append(Spacer(1, 8))

    # =========================================================================
    # 3. EXPERIENCE ANALYZER & WEIGHTED SCORING ENGINE
    # =========================================================================
    story.append(Paragraph("3. ExperienceAnalyzer & Weighted Multi-Dimensional Scoring", h1_style))
    story.append(Paragraph(
        "<b>Dedicated ExperienceAnalyzer (Strict 0-2 Years Target):</b><br/>"
        "The <code>ExperienceAnalyzer</code> inspects both the job title and full description. Any role requiring 3+ years, 4+ years, "
        "or ranges like 3–5 yrs / 2–4 yrs is rejected immediately before resume tailoring or application.",
        body_style
    ))

    exp_matrix = [
        [
            Paragraph("<b>Requirement Pattern</b>", table_header),
            Paragraph("<b>Extracted Min / Max</b>", table_header),
            Paragraph("<b>Pipeline Action</b>", table_header),
            Paragraph("<b>Rationale & Behavior</b>", table_header),
        ],
        [
            Paragraph("<code>Fresher / Entry / 0-2 yrs</code>", table_cell),
            Paragraph("Min: 0.0, Max: 2.0", table_cell),
            Paragraph("<font color='#2F855A'><b>PASS (Eligible)</b></font>", table_cell),
            Paragraph("Perfect target match. Advances to AI semantic scoring.", table_cell),
        ],
        [
            Paragraph("<code>1-2 years / 2 years</code>", table_cell),
            Paragraph("Min: 1.0, Max: 2.0", table_cell),
            Paragraph("<font color='#2F855A'><b>PASS (Eligible)</b></font>", table_cell),
            Paragraph("Within candidate's 0-2 years background.", table_cell),
        ],
        [
            Paragraph("<code>2-4 years / 2-5 years</code>", table_cell),
            Paragraph("Min: 2.0, Max: 4.0+", table_cell),
            Paragraph("<font color='#C53030'><b>HARD REJECT</b></font>", table_cell),
            Paragraph("Exceeds 2-year upper threshold.", table_cell),
        ],
        [
            Paragraph("<code>3+ years / 3-5 years</code>", table_cell),
            Paragraph("Min: 3.0, Max: 5.0", table_cell),
            Paragraph("<font color='#C53030'><b>HARD REJECT</b></font>", table_cell),
            Paragraph("Experienced tier. Hard-blocked before LLM.", table_cell),
        ],
        [
            Paragraph("<code>Senior / Staff / Lead / Mgr</code>", table_cell),
            Paragraph("Seniority Keyword", table_cell),
            Paragraph("<font color='#C53030'><b>HARD REJECT</b></font>", table_cell),
            Paragraph("Senior title guard triggered. Score set to 0.", table_cell),
        ],
    ]

    exp_table = Table(exp_matrix, colWidths=[120, 100, 100, 184])
    exp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), SECONDARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(exp_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Multi-Dimensional Scoring Formula:</b>", body_bold))
    story.append(Paragraph("$$\\text{Overall Score} = (30\\% \\times \\text{Role Match}) + (25\\% \\times \\text{Experience Match}) + (25\\% \\times \\text{Skill Match}) + (10\\% \\times \\text{Location Match}) + (10\\% \\times \\text{Freshness Quality})$$", code_style))

    story.append(PageBreak())

    # =========================================================================
    # 4. SOURCE-AWARE 3-MODE APPLICATION & RESUME TAILORING
    # =========================================================================
    story.append(Paragraph("4. Source-Aware Application Engine & Dynamic ATS Resumes", h1_style))
    story.append(Paragraph(
        "<b>100% Unique Dynamic ATS Resumes:</b><br/>"
        "For every qualifying job (Score ≥ 65), Gemini extracts key technologies and tailors the summary, skill badges, and "
        "work accomplishments. ReportLab Platypus builds a pixel-perfect, 1-page ATS compliant PDF saved to <code>resumes/</code>.",
        body_style
    ))

    modes_data = [
        [
            Paragraph("<b>Application Mode</b>", table_header),
            Paragraph("<b>Target Portals</b>", table_header),
            Paragraph("<b>Execution Strategy & Safety Rules</b>", table_header),
        ],
        [
            Paragraph("<b>🟢 Mode 1: Direct API</b>", table_cell),
            Paragraph("Greenhouse, Lever, Ashby", table_cell),
            Paragraph("Programmatic multipart form submission via official job board APIs with tailored ATS resume attached.", table_cell),
        ],
        [
            Paragraph("<b>🟡 Mode 2: Persistent Browser</b>", table_cell),
            Paragraph("Wellfound, YC, LinkedIn, Workday, Jobicy", table_cell),
            Paragraph("Playwright Chromium reuses authenticated session profile (<code>data/browser_profile</code>). Auto-fills forms and uploads tailored resume without password leakage.", table_cell),
        ],
        [
            Paragraph("<b>✉️ Mode 3: Verified HR Email</b>", table_cell),
            Paragraph("LinkedIn Posts, HackerNews Hiring", table_cell),
            Paragraph("<b>Zero Bounce Policy:</b> Sends cold email outreach ONLY to explicit recruiter emails extracted from post text. Never guesses synthetic addresses.", table_cell),
        ],
        [
            Paragraph("<b>🔴 Mode 4: 1-Click Link Prep</b>", table_cell),
            Paragraph("Adzuna, Hirist, Shine, Cutshort, Foundit", table_cell),
            Paragraph("Prepares custom ATS PDF resume + cover note and formats 1-click direct link in Excel report for anti-bot portals.", table_cell),
        ],
    ]

    modes_table = Table(modes_data, colWidths=[120, 130, 254])
    modes_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(modes_table)

    story.append(Spacer(1, 10))

    # =========================================================================
    # 5. COMPLETE DIRECTORY STRUCTURE
    # =========================================================================
    story.append(Paragraph("5. Production Codebase Directory Structure", h1_style))
    story.append(Paragraph(
        "Complete clean directory layout of the repository:",
        body_style
    ))

    clean_tree = """AI-Job-Agent/
├── app/
│   ├── agents/                   # LangGraph Workflow Orchestrators
│   │   ├── nodes.py              # 6 Pipeline Nodes (fetch, score, resume, apply, notify, report)
│   │   ├── orchestrator.py       # LangGraph StateGraph compilation
│   │   └── state.py              # AgentState TypedDict schema
│   ├── config/                   # Central Configuration & Source Settings
│   │   ├── job_sources.yml       # YAML source enable/disable & priority config
│   │   └── settings.py           # Environment variables & candidate profile
│   ├── connectors/               # 16 Active Job Ingestion Connectors
│   │   ├── base.py               # BaseConnector abstract interface
│   │   ├── manager.py            # SearchManager concurrent executor
│   │   ├── registry.py           # Connector discovery decorator
│   │   ├── greenhouse_connector.py # Greenhouse ATS API
│   │   ├── lever_connector.py      # Lever ATS API
│   │   ├── ashby_connector.py      # Ashby ATS API
│   │   ├── workday_connector.py    # Workday CXS Portal
│   │   ├── smartrecruiters_connector.py # SmartRecruiters API
│   │   ├── jobicy_connector.py     # Jobicy Remote API
│   │   ├── remotive_connector.py   # Remotive Software API
│   │   ├── himalayas_connector.py  # Himalayas Remote API
│   │   ├── adzuna_connector.py     # Adzuna Jobs API
│   │   ├── agent_reach_connector.py # Agent Reach LinkedIn scraper
│   │   ├── linkedin_posts_connector.py # LinkedIn Hiring Posts parser
│   │   ├── ycombinator_connector.py # HackerNews / YC Algolia API
│   │   ├── wellfound_connector.py  # Wellfound AI Startups
│   │   ├── arbeitnow_connector.py  # Arbeitnow Tech API
│   │   └── weworkremotely_connector.py # WeWorkRemotely RSS
│   ├── db/                       # Database Storage Layer
│   │   ├── models.py             # SQLAlchemy ORM models (Job, Application, Resume)
│   │   └── session.py            # SQLite engine (jobs.db)
│   ├── prompts/                  # LLM System Personas & Prompts
│   │   ├── email_prompt.py       # Cold outreach email prompt
│   │   ├── resume_prompt.py      # Dynamic ATS resume tailoring prompt
│   │   └── scoring_prompt.py     # Strict 0-2 yrs technical scoring prompt
│   ├── schemas/                  # Data Transfer Objects
│   │   ├── application.py        # Application status schema
│   │   └── job_data.py           # Unified JobData dataclass
│   ├── services/                 # Core Business Logic
│   │   ├── application_policy.py # Source-Aware 3-Mode Policy Manager
│   │   ├── apply_service.py      # Application routing & submission
│   │   ├── browser_apply_service.py # Playwright Chromium persistent browser engine
│   │   ├── email_service.py      # Gmail API OAuth2 sender
│   │   ├── mock_scoring_service.py # Heuristic pre-filter engine
│   │   ├── report_service.py     # openpyxl multi-tab Excel generator
│   │   ├── resume_service.py     # Dynamic ATS 1-page PDF builder
│   │   ├── scheduler_service.py  # APScheduler 24/7 6-hour cron service
│   │   ├── scoring_service.py    # Gemini AI semantic scoring
│   │   └── whatsapp_service.py   # CallMeBot & Meta WhatsApp alerts
│   └── utils/                    # Validators & Helper Utilities
│       ├── email_validator.py    # Explicit HR email parser & DNS validator
│       ├── experience_analyzer.py # Dedicated 0-2 yrs ExperienceAnalyzer
│       ├── experience_filter.py  # Senior title & experience hard guard
│       └── gemini_client.py      # Resilient Gemini client with retry
├── data/                         # Persistent Storage & Browser Profiles
│   ├── browser_profile/          # Playwright persistent Chromium session & cookies
│   └── jobs.db                   # SQLite primary database
├── docs/                         # Architecture Documentation & PDF Blueprints
│   └── AI_Job_Agent_Architecture_and_Workflow.pdf
├── reports/                      # Daily Multi-Tab Excel Reports
├── resumes/                      # Master & Tailored ATS PDF Resumes
├── scripts/                      # Operational Scripts & Tools
│   ├── run_agent.py              # CLI runner for single pipeline execution
│   ├── test_browser_apply.py     # Live visible browser auto-apply tester
│   ├── setup_gmail_token.py      # Gmail OAuth2 token generator
│   ├── setup_whatsapp.py         # WhatsApp CallMeBot diagnostic tool
│   └── generate_architecture_pdf.py # Architecture PDF builder
├── main.py                       # FastAPI 24/7 Server & Background Scheduler Entrypoint
├── requirements.txt              # Production Python dependencies
└── .env                          # Configuration & API Credentials
"""

    tree_table = Table([[Paragraph(f"<pre>{clean_tree}</pre>", code_style)]], colWidths=[504])
    tree_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(tree_table)

    # Build PDF with NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✅ Master Architecture PDF successfully generated: {filename}")


if __name__ == "__main__":
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    pdf_path = str(docs_dir / "AI_Job_Agent_Architecture_and_Workflow.pdf")
    build_pdf(pdf_path)
