import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)

# ── Database ──────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///job_agent.db")

# ── LLM ──────────────────────────────────────────────────
ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

# ── Gmail ─────────────────────────────────────────────────
GMAIL_CLIENT_ID: Optional[str] = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET: Optional[str] = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN: Optional[str] = os.getenv("GMAIL_REFRESH_TOKEN")
EMAIL_ADDRESS: Optional[str] = os.getenv("EMAIL_ADDRESS")

# ── WhatsApp ──────────────────────────────────────────────
WHATSAPP_TOKEN: Optional[str] = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID: Optional[str] = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_TO_NUMBER: Optional[str] = os.getenv("WHATSAPP_TO_NUMBER")

# ── Agent Config ──────────────────────────────────────────
MATCH_SCORE_THRESHOLD: int = int(os.getenv("MATCH_SCORE_THRESHOLD", "65"))
MAX_APPLICATIONS_PER_RUN: int = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "10"))
SCHEDULER_INTERVAL_HOURS: int = int(os.getenv("SCHEDULER_INTERVAL_HOURS", "6"))
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"
MOCK_SCORING: bool = os.getenv("MOCK_SCORING", "false").lower() == "true"

# ── Resume ────────────────────────────────────────────────
MASTER_RESUME_PATH: Path = BASE_DIR / "resumes" / "Kamal_Kumar_Java_AI_Developer_ATS.pdf"
RESUMES_DIR: Path = BASE_DIR / "resumes"
REPORTS_DIR: Path = BASE_DIR / "reports"

# ── Logging ───────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── Candidate Profile (for AI scoring context) ────────────
CANDIDATE_NAME: str = os.getenv("CANDIDATE_NAME", "Kamal Kumar")
CANDIDATE_TARGET_ROLES: list[str] = [
    "Java Developer",
    "Backend Developer",
    "Spring Boot Developer",
    "Software Engineer",
    "Full Stack Developer",
    "AI Engineer",
    "ML Engineer",
    "Cloud Engineer",
    "API Developer",
    "Python Developer",
]
CANDIDATE_TARGET_LOCATIONS: list[str] = ["Remote", "India", "Hyderabad", "Bangalore", "Chennai"]
CANDIDATE_SKILLS: list[str] = [
    "Java", "Spring Boot", "Spring Framework", "Microservices",
    "Python", "FastAPI", "REST API",
    "AWS", "Docker", "Kubernetes",
    "SQL", "PostgreSQL", "MySQL",
    "LangChain", "LangGraph", "AI Agents",
    "Git", "CI/CD",
]
