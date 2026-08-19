"""
AI Job Agent — Main FastAPI Application

Startup:
  - Creates all DB tables
  - Starts APScheduler (every 6 hours)

Routes:
  GET  /              → health check
  GET  /jobs/         → all jobs
  GET  /jobs/stats    → job statistics
  POST /agent/run     → manual agent trigger
  GET  /agent/status  → agent + scheduler status
  GET  /applications/ → all applications
  GET  /docs          → Swagger UI
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.applications import router as applications_router
from app.api.jobs import router as jobs_router
from app.config.settings import LOG_LEVEL
from app.database.database import Base, engine
from app.services.scheduler_service import start_scheduler, stop_scheduler

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("🚀 AI Job Agent starting up...")

    # Create all DB tables
    import app.models  # noqa — ensures all models are registered
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created/verified")

    # Start APScheduler
    start_scheduler()
    logger.info("✅ Scheduler started (every 6 hours)")

    yield  # App is running

    # Shutdown
    logger.info("🛑 AI Job Agent shutting down...")
    stop_scheduler()


# ── FastAPI App ───────────────────────────────────────────
app = FastAPI(
    title="🤖 AI Job Agent",
    description=(
        "Autonomous AI-powered job search agent.\n\n"
        "**Pipeline:** Job Search → AI Scoring → Resume Generation → "
        "Cold Email → WhatsApp Notification → Excel Report\n\n"
        "**Sources:** RemoteOK, Wellfound, YCombinator, Greenhouse, Lever, "
        "Ashby, WeWorkRemotely, Remotive, Himalayas\n\n"
        "**LLM:** Claude (Anthropic)"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────
app.include_router(jobs_router)
app.include_router(agent_router)
app.include_router(applications_router)


# ── Health Check ──────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    from app.services.scheduler_service import get_scheduler_status
    return {
        "name": "AI Job Agent",
        "version": "2.0.0",
        "status": "running",
        "scheduler": get_scheduler_status(),
        "docs": "/docs",
        "endpoints": {
            "jobs": "/jobs/",
            "job_stats": "/jobs/stats",
            "qualified_jobs": "/jobs/qualified",
            "trigger_agent": "POST /agent/run",
            "agent_status": "/agent/status",
            "applications": "/applications/",
        },
    }