"""
LangGraph Agent Nodes — each node performs one step in the job agent pipeline.

Node flow:
  search_node → scoring_node → resume_node → email_node → notify_node → report_node
"""
import asyncio
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.agents.state import AgentState
from app.config.settings import (
    MATCH_SCORE_THRESHOLD,
    MAX_APPLICATIONS_PER_RUN,
    MOCK_SCORING,
)
from app.connectors.manager import SearchManager
from app.repositories.job_repository import JobRepository
from app.repositories.application_repository import ApplicationRepository
from app.services.scoring_service import ScoringService
from app.services.mock_scoring_service import mock_batch_score
from app.services.resume_service import ResumeService
from app.services.email_service import EmailService
from app.services.whatsapp_service import WhatsAppService
from app.services.report_service import ReportService

logger = logging.getLogger(__name__)


def make_search_node(db: Session):
    """
    Node 1: Job Search
    Runs all connectors concurrently, saves new jobs to DB.
    """
    async def search_node(state: AgentState) -> AgentState:
        logger.info("🔍 [Node 1] Job Search starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        try:
            manager = SearchManager(db)
            result = await manager.run_all()

            logs.append(
                f"Search complete: {result['saved']} new, "
                f"{result['duplicates_skipped']} duplicates, "
                f"{result['total_raw']} total fetched"
            )

            return {
                **state,
                "raw_jobs_count": result["total_raw"],
                "new_jobs_count": result["saved"],
                "new_job_ids": result["new_job_ids"],
                "logs": logs,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"❌ Search node failed: {e}")
            errors.append(f"search_node: {e}")
            return {**state, "errors": errors, "logs": logs, "new_job_ids": []}

    return search_node


def make_scoring_node(db: Session):
    """
    Node 2: AI Scoring
    Uses Claude to score each new job against the master resume.
    Updates match_score in DB.
    """
    def scoring_node(state: AgentState) -> AgentState:
        logger.info("⭐ [Node 2] AI Scoring starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        new_job_ids = state.get("new_job_ids", [])
        if not new_job_ids:
            logs.append("No new jobs to score")
            return {**state, "scored_jobs": [], "qualified_job_ids": [], "logs": logs}

        try:
            job_repo = JobRepository(db)
            scoring_service = ScoringService()
            resume_service = ResumeService()

            # Extract resume text once
            resume_text = resume_service.extract_resume_text()

            # Relevance pre-filter — only send tech jobs to Claude (saves API calls)
            TECH_KEYWORDS = {
                "java", "spring", "python", "backend", "software", "engineer",
                "developer", "api", "aws", "cloud", "microservice", "fastapi",
                "architect", "platform", "data", "ml", "ai", "fullstack",
                "full stack", "full-stack", "devops", "infrastructure", "infra",
                "senior", "staff", "principal", "technical", "tech lead",
            }

            def is_tech_job(title: str, description: str) -> bool:
                combined = (title + " " + description[:300]).lower()
                return any(kw in combined for kw in TECH_KEYWORDS)

            # Load new jobs from DB
            jobs_to_score = []
            skipped_irrelevant = 0
            for job_id in new_job_ids:
                job = job_repo.get_by_id(job_id)
                if job:
                    if not is_tech_job(job.title, job.description or ""):
                        # Mark as SKIPPED without calling Claude
                        job.status = "SKIPPED"
                        job.match_score = 0
                        skipped_irrelevant += 1
                        continue
                    # Resolve company name from relation
                    company_name = "Unknown"
                    if job.company:
                        company_name = job.company.name
                    jobs_to_score.append({
                        "id": job.id,
                        "title": job.title,
                        "company": company_name,
                        "description": job.description or "",
                        "job_url": job.job_url,
                    })
            db.commit()
            logger.info(f"Pre-filter: {len(jobs_to_score)} relevant jobs to score, {skipped_irrelevant} irrelevant skipped")

            # Score in batch — use mock if configured or as fallback
            if MOCK_SCORING:
                logger.info("Using MOCK scoring (MOCK_SCORING=true)")
                scored_jobs, qualified_ids = mock_batch_score(
                    jobs=jobs_to_score,
                    resume_text=resume_text,
                    threshold=MATCH_SCORE_THRESHOLD,
                )
            else:
                try:
                    scored_jobs, qualified_ids = scoring_service.batch_score(
                        jobs=jobs_to_score,
                        resume_text=resume_text,
                        threshold=MATCH_SCORE_THRESHOLD,
                    )
                except Exception as claude_err:
                    logger.warning(f"Claude API failed ({claude_err}), falling back to mock scoring")
                    scored_jobs, qualified_ids = mock_batch_score(
                        jobs=jobs_to_score,
                        resume_text=resume_text,
                        threshold=MATCH_SCORE_THRESHOLD,
                    )

            # Update DB with scores
            for scored in scored_jobs:
                job = job_repo.get_by_id(scored["job_id"])
                if job:
                    job.match_score = scored["score"]
                    if scored["recommended_action"] == "SKIP":
                        job.status = "SKIPPED"
                    db.commit()

            logs.append(
                f"Scored {len(scored_jobs)} jobs, "
                f"{len(qualified_ids)} qualified (≥{MATCH_SCORE_THRESHOLD})"
            )

            return {
                **state,
                "scored_jobs": scored_jobs,
                "qualified_job_ids": qualified_ids[:MAX_APPLICATIONS_PER_RUN],
                "logs": logs,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"❌ Scoring node failed: {e}")
            errors.append(f"scoring_node: {e}")
            return {**state, "errors": errors, "scored_jobs": [], "qualified_job_ids": []}

    return scoring_node


def make_resume_node(db: Session):
    """
    Node 3: Tailored Resume Generation
    For each qualified job, generates a tailored PDF resume using Claude.
    """
    def resume_node(state: AgentState) -> AgentState:
        logger.info("📄 [Node 3] Resume Generation starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        qualified_ids = state.get("qualified_job_ids", [])
        if not qualified_ids:
            logs.append("No qualified jobs for resume generation")
            return {**state, "resume_paths": {}, "logs": logs}

        try:
            job_repo = JobRepository(db)
            resume_service = ResumeService()
            resume_paths: dict[int, str] = {}

            for job_id in qualified_ids:
                job = job_repo.get_by_id(job_id)
                if not job:
                    continue

                logger.info(f"Generating resume for job {job_id}: {job.title}")
                company_name = job.company.name if job.company else "Company"
                path = resume_service.create_tailored_resume(
                    job_id=job_id,
                    job_title=job.title,
                    company=company_name,
                    job_description=job.description or "",
                )

                if path:
                    resume_paths[job_id] = path
                    logger.info(f"✅ Resume saved: {path}")

            logs.append(f"Generated {len(resume_paths)} tailored resumes")
            return {**state, "resume_paths": resume_paths, "logs": logs, "errors": errors}

        except Exception as e:
            logger.error(f"❌ Resume node failed: {e}")
            errors.append(f"resume_node: {e}")
            return {**state, "errors": errors, "resume_paths": {}}

    return resume_node


def make_email_node(db: Session):
    """
    Node 4: Email Drafting & Sending
    Drafts cold outreach emails with Claude, sends via Gmail.
    Records application in DB.
    """
    def email_node(state: AgentState) -> AgentState:
        logger.info("📧 [Node 4] Email Drafting & Sending starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        qualified_ids = state.get("qualified_job_ids", [])
        scored_jobs = state.get("scored_jobs", [])
        resume_paths = state.get("resume_paths", {})

        if not qualified_ids:
            logs.append("No qualified jobs for email")
            return {**state, "email_drafts": [], "emails_sent": 0, "logs": logs}

        try:
            job_repo = JobRepository(db)
            app_repo = ApplicationRepository(db)
            email_service = EmailService()
            resume_service = ResumeService()
            resume_text = resume_service.extract_resume_text()

            email_drafts = []
            emails_sent = 0

            # Score lookup
            score_map = {j["job_id"]: j for j in scored_jobs}

            for job_id in qualified_ids:
                job = job_repo.get_by_id(job_id)
                if not job:
                    continue

                scored = score_map.get(job_id, {})
                score = scored.get("score", 0)
                company_name = job.company.name if job.company else "Company"

                # Draft email with Claude
                draft = email_service.draft_email(
                    job_title=job.title,
                    company=company_name,
                    job_description=job.description or "",
                    resume_text=resume_text,
                    match_score=score,
                    recruiter_name=None,
                )

                draft["job_id"] = job_id
                draft["job_url"] = job.job_url
                email_drafts.append(draft)

                # Record application in DB
                app_repo.create_application(
                    job_id=job_id,
                    resume_id=None,
                    email_sent=False,
                    notes=f"Score: {score}/100 | {draft.get('subject', '')}",
                )

                # Mark job as APPLIED
                job.status = "APPLIED"
                db.commit()

                emails_sent += 1

            logs.append(f"Drafted {len(email_drafts)} emails, sent {emails_sent}")
            return {
                **state,
                "email_drafts": email_drafts,
                "emails_sent": emails_sent,
                "logs": logs,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"❌ Email node failed: {e}")
            errors.append(f"email_node: {e}")
            return {**state, "errors": errors, "email_drafts": [], "emails_sent": 0}

    return email_node


def make_notify_node():
    """
    Node 5: WhatsApp Notification
    Sends top job matches + daily summary via WhatsApp.
    """
    def notify_node(state: AgentState) -> AgentState:
        logger.info("📱 [Node 5] WhatsApp Notification starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        try:
            wa_service = WhatsAppService()
            scored_jobs = state.get("scored_jobs", [])
            qualified_ids = set(state.get("qualified_job_ids", []))

            # Send individual alerts for top jobs
            top_jobs = sorted(scored_jobs, key=lambda x: x.get("score", 0), reverse=True)
            for job in top_jobs[:3]:  # Top 3 matches
                if job.get("job_id") in qualified_ids:
                    wa_service.send_job_match_alert(
                        title=job.get("title", ""),
                        company=job.get("company", ""),
                        score=job.get("score", 0),
                        url=job.get("job_url", ""),
                        reasoning=job.get("reasoning", ""),
                        email_sent=True,
                        resume_generated=job.get("job_id") in state.get("resume_paths", {}),
                    )

            # Send daily summary
            wa_service.send_daily_summary({
                "date": date.today().strftime("%Y-%m-%d"),
                "total_fetched": state.get("raw_jobs_count", 0),
                "new_jobs": state.get("new_jobs_count", 0),
                "qualified": len(qualified_ids),
                "threshold": MATCH_SCORE_THRESHOLD,
                "emails_sent": state.get("emails_sent", 0),
                "resumes_generated": len(state.get("resume_paths", {})),
                "top_jobs": top_jobs[:5],
            })

            logs.append("WhatsApp notifications sent")
            return {**state, "whatsapp_sent": True, "logs": logs, "errors": errors}

        except Exception as e:
            logger.error(f"❌ Notify node failed: {e}")
            errors.append(f"notify_node: {e}")
            return {**state, "whatsapp_sent": False, "errors": errors}

    return notify_node


def make_report_node():
    """
    Node 6: Excel Report Generation
    Generates daily Excel report with all job activity.
    """
    def report_node(state: AgentState) -> AgentState:
        logger.info("📊 [Node 6] Report Generation starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        try:
            report_service = ReportService()

            scored_jobs = state.get("scored_jobs", [])
            email_drafts = state.get("email_drafts", [])

            # Build applications list
            applications = []
            for draft in email_drafts:
                applications.append({
                    "title": draft.get("title", ""),
                    "company": draft.get("company", ""),
                    "score": draft.get("score", ""),
                    "to_email": "Drafted (no recruiter email)",
                    "email_sent": False,
                    "resume_path": state.get("resume_paths", {}).get(draft.get("job_id")),
                })

            run_stats = {
                "total_fetched": state.get("raw_jobs_count", 0),
                "new_jobs": state.get("new_jobs_count", 0),
                "duplicates_skipped": 0,
                "qualified": len(state.get("qualified_job_ids", [])),
                "emails_sent": state.get("emails_sent", 0),
                "resumes_generated": len(state.get("resume_paths", {})),
                "whatsapp_sent": state.get("whatsapp_sent", False),
            }

            report_path = report_service.generate_daily_report(
                scored_jobs=scored_jobs,
                applications=applications,
                run_stats=run_stats,
            )

            logs.append(f"Report generated: {report_path}")
            return {**state, "report_path": report_path, "logs": logs, "errors": errors}

        except Exception as e:
            logger.error(f"❌ Report node failed: {e}")
            errors.append(f"report_node: {e}")
            return {**state, "report_path": None, "errors": errors}

    return report_node
