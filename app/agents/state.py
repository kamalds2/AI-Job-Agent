from typing import Annotated, Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """
    LangGraph state shared across all agent nodes.
    """

    # ── Run metadata ───────────────────────────────────────────
    run_id: str
    run_timestamp: str
    dry_run: bool

    # ── Job search results ─────────────────────────────────────
    raw_jobs_count: int          # Total jobs fetched from all sources
    new_jobs_count: int          # After deduplication
    new_job_ids: list[int]       # DB IDs of newly saved jobs

    # ── AI Scoring results ─────────────────────────────────────
    scored_jobs: list[dict]      # [{job_id, title, company, score, reasoning}]
    qualified_job_ids: list[int] # Jobs above threshold

    # ── Resume generation ──────────────────────────────────────
    resume_paths: dict[int, str] # {job_id: pdf_path}

    # ── Email drafting & sending ───────────────────────────────
    email_drafts: list[dict]     # [{job_id, to, subject, body}]
    emails_sent: int

    # ── Report ─────────────────────────────────────────────────
    report_path: Optional[str]

    # ── Phase 3: Browser Auto-Apply stats ──────────────────────
    browser_stats: Optional[dict]

    # ── Phase 4: Global Career Sites stats ─────────────────────
    career_sites_stats: Optional[dict]

    # ── Errors & logs ─────────────────────────────────────────
    errors: list[str]
    logs: list[str]
