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
import sys
import asyncio
import os
import logging
from contextlib import asynccontextmanager

# Enforce ProactorEventLoop on Windows so Playwright async subprocesses work under Uvicorn/FastAPI
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.agent import router as agent_router
from app.api.applications import router as applications_router
from app.api.jobs import router as jobs_router
from app.api.kknn import router as kknn_router
from app.config.settings import BASE_DIR, LOG_LEVEL, DRY_RUN, REPORTS_DIR, RESUMES_DIR
from app.database.database import Base, engine
from app.services.scheduler_service import get_scheduler_status, start_scheduler, stop_scheduler

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
    logger.info("🚀 KKNN Autonomous Job Agent Server starting up...")

    # Create all DB tables
    import app.models  # noqa — ensures all models are registered
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created/verified")

    # Start APScheduler
    start_scheduler()

    # Launch full Multi-Agent pipeline in background upon server start ONLY if explicitly enabled
    if os.getenv("RUN_ON_STARTUP", "false").lower() in ("true", "1", "yes"):
        logger.info("🤖 RUN_ON_STARTUP is enabled: Auto-launching Full Multi-Agent Workflow on server startup in background...")
        from app.agents.orchestrator import run_full_multi_agent_pipeline
        asyncio.create_task(run_full_multi_agent_pipeline(dry_run=DRY_RUN))
    else:
        logger.info("🕒 Server started. Multi-Agent pipeline will trigger strictly at scheduled times (06:00, 12:00, 18:00, 00:00 IST) or on manual trigger (POST /agent/run).")

    yield  # App is running

    # Shutdown
    logger.info("🛑 KKNN Autonomous Job Agent shutting down...")
    stop_scheduler()


# ── FastAPI App ───────────────────────────────────────────
app = FastAPI(
    title="🤖 KKNN Autonomous Job Assistant Hub",
    description=(
        "Autonomous AI-powered job application and performance monitoring platform.\n\n"
        "**Target:** Doddi Kamal Kumar (Java Developer / AI Engineer / Full Stack Developer)"
    ),
    version="3.0.0",
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

# ── Static & Download Mounts ──────────────────────────────
reports_path = Path(REPORTS_DIR)
resumes_path = Path(RESUMES_DIR)
screenshots_path = BASE_DIR / "screenshots"

reports_path.mkdir(parents=True, exist_ok=True)
resumes_path.mkdir(parents=True, exist_ok=True)
screenshots_path.mkdir(parents=True, exist_ok=True)

app.mount("/download/reports", StaticFiles(directory=str(reports_path)), name="reports")
app.mount("/download/resumes", StaticFiles(directory=str(resumes_path)), name="resumes")
app.mount("/download/screenshots", StaticFiles(directory=str(screenshots_path)), name="screenshots")

# ── Routers ───────────────────────────────────────────────
app.include_router(kknn_router)
app.include_router(jobs_router)
app.include_router(agent_router)
app.include_router(applications_router)


# ── KKNN Dashboard Web Interface ───────────────────────────
@app.get("/", response_class=HTMLResponse, tags=["KKNN Web Dashboard"])
@app.get("/dashboard", response_class=HTMLResponse, tags=["KKNN Web Dashboard"])
@app.get("/dashboard/", response_class=HTMLResponse, tags=["KKNN Web Dashboard"])
@app.get("/kknn", response_class=HTMLResponse, tags=["KKNN Web Dashboard"])
@app.get("/kknn/", response_class=HTMLResponse, tags=["KKNN Web Dashboard"])
def kknn_dashboard():
    """Serves the KKNN Autonomous Job Assistant Performance Hub."""
    template_path = BASE_DIR / "app" / "templates" / "index.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>KKNN Dashboard template not found</h1>", status_code=404)


# ── Health Check API ──────────────────────────────────────
@app.get("/api/health", tags=["Health"])
def health():
    return {
        "name": "KKNN Autonomous Job Agent",
        "version": "3.0.0",
        "status": "running",
        "scheduler": get_scheduler_status(),
        "dashboard": "/dashboard",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    # Force asyncio loop with WindowsProactorEventLoopPolicy
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False, loop="asyncio")