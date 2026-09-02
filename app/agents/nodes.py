"""
LangGraph Agent Nodes — each node performs one step in the job agent pipeline.

Node flow:
  search_node → scoring_node → resume_node → email_node → notify_node → report_node
"""
import asyncio
import logging
import os
import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.agents.state import AgentState
from app.config.settings import (
    CANDIDATE_NAME,
    MATCH_SCORE_THRESHOLD,
    MAX_APPLICATIONS_PER_RUN,
    MOCK_SCORING,
    EMAIL_ADDRESS,
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


def company_from_url(url: str) -> str:
    """
    Extract company name from job board or company career URLs.
    Examples:
      job-boards.greenhouse.io/anthropic/...  → Anthropic
      jobs.lever.co/bazaarvoice/...           → Bazaarvoice
      jobs.ashbyhq.com/perplexity-ai/...      → Perplexity AI
      stripe.com/jobs/...                     → Stripe
      careers.airbnb.com/positions/...        → Airbnb
    """
    if not url:
        return "Company"
    url_lower = url.lower()

    # Greenhouse: greenhouse.io/{company}/...
    m = re.search(r"greenhouse\.io/([a-z0-9_-]+)/", url_lower)
    if m:
        return m.group(1).replace("-", " ").title()

    # Lever: lever.co/{company}/...
    m = re.search(r"lever\.co/([a-z0-9_-]+)/", url_lower)
    if m:
        return m.group(1).replace("-", " ").title()

    # Ashby: ashbyhq.com/{company}/...
    m = re.search(r"ashbyhq\.com/([a-z0-9_-]+)/", url_lower)
    if m:
        return m.group(1).replace("-", " ").title()

    # Workday: {company}.wdN.myworkdayjobs.com/...
    m = re.search(r"https?://([a-z0-9_-]+)\.wd\d+\.myworkdayjobs\.com", url_lower)
    if m:
        return m.group(1).replace("-", " ").title()

    # General domain parsing (e.g. careers.airbnb.com, stripe.com)
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url_lower).hostname or ""
        parts = hostname.split(".")
        if len(parts) >= 2:
            # Handle careers.airbnb.com -> airbnb, or stripe.com -> stripe
            domain_part = parts[-2]
            if domain_part in {"greenhouse", "lever", "ashby", "workday", "indeed", "linkedin", "jobvite", "remoteok", "weworkremotely", "arbeitnow", "himalayas", "naukri", "adzuna"}:
                return "Company"
            return domain_part.replace("-", " ").title()
    except Exception:
        pass

    return "Company"



def resolve_company(job) -> str:
    """Get company name from FK relationship or fall back to URL parsing."""
    if job.company and job.company.name and job.company.name != "Unknown":
        return job.company.name
    return company_from_url(job.job_url)


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
        logger.info("[Node 2] AI Scoring starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        try:
            job_repo = JobRepository(db)
            scoring_service = ScoringService()
            resume_service = ResumeService()

            resume_text = resume_service.extract_resume_text()

            # ── Collect job IDs to score ─────────────────────────
            # 1. New jobs from this run
            new_job_ids = set(state.get("new_job_ids", []))

            # 2. ALSO pick up any unscored NEW jobs from previous runs (backlog)
            backlog_limit = 100  # Score up to 100 backlog jobs per run
            backlog_jobs = (
                db.query(job_repo.model)
                .filter(
                    job_repo.model.status == "NEW",
                    job_repo.model.match_score.is_(None),
                )
                .order_by(job_repo.model.id.desc())
                .limit(backlog_limit)
                .all()
            )
            backlog_ids = {j.id for j in backlog_jobs}
            all_ids = new_job_ids | backlog_ids

            if not all_ids:
                logs.append("No jobs to score (no new, no backlog)")
                return {**state, "scored_jobs": [], "qualified_job_ids": [], "logs": logs}

            logger.info(
                f"Jobs to score: {len(new_job_ids)} new this run "
                f"+ {len(backlog_ids)} backlog = {len(all_ids)} total"
            )

            # ── Tech relevance pre-filter ────────────────────────
            TECH_KEYWORDS = {
                "java", "spring", "python", "backend", "software", "engineer",
                "developer", "api", "aws", "cloud", "microservice", "fastapi",
                "architect", "platform", "data", "ml", "ai", "fullstack",
                "full stack", "full-stack", "devops", "infrastructure", "infra",
                "kotlin", "scala", "golang", "typescript", "node", "react",
                "kubernetes", "docker", "terraform", "distributed", "streaming",
            }

            def is_tech_job(title: str, description: str) -> bool:
                combined = (title + " " + description[:300]).lower()
                return any(kw in combined for kw in TECH_KEYWORDS)

            jobs_to_score = []
            skipped_irrelevant = 0
            for job_id in all_ids:
                job = job_repo.get_by_id(job_id)
                if not job:
                    continue
                if not is_tech_job(job.title, job.description or ""):
                    job.status = "SKIPPED"
                    job.match_score = 0
                    skipped_irrelevant += 1
                    continue
                company_name = resolve_company(job)
                jobs_to_score.append({
                    "id": job.id,
                    "title": job.title,
                    "company": company_name,
                    "description": job.description or "",
                    "job_url": job.job_url,
                })
            db.commit()
            logger.info(
                f"Pre-filter: {len(jobs_to_score)} tech jobs to score, "
                f"{skipped_irrelevant} non-tech skipped"
            )

            # ── Stage 1: Mock-score ALL filtered jobs (fast, free) ──
            logger.info(f"Stage 1: Mock-scoring {len(jobs_to_score)} filtered jobs...")
            mock_scored, _ = mock_batch_score(
                jobs=jobs_to_score,
                resume_text=resume_text,
                threshold=MATCH_SCORE_THRESHOLD,
            )

            if MOCK_SCORING:
                # Pure mock mode — use mock scores directly
                logger.info("MOCK_SCORING=true — using mock scores as final")
                scored_jobs = mock_scored
                qualified_ids = [
                    j["job_id"] for j in mock_scored
                    if j.get("score", 0) >= MATCH_SCORE_THRESHOLD
                ]
            else:
                # ── Stage 2: Parallel LLM-score top 10 candidates ──
                top_candidates = sorted(
                    mock_scored, key=lambda x: x.get("score", 0), reverse=True
                )[:10]
                top_ids = {j["job_id"] for j in top_candidates}

                logger.info(
                    f"Stage 2: Parallel LLM-scoring top {len(top_candidates)} high-potential candidates..."
                )

                # Only send top candidates for expensive LLM scoring
                llm_jobs = [j for j in jobs_to_score if j["id"] in top_ids]

                try:
                    llm_scored, llm_qualified = scoring_service.batch_score(
                        jobs=llm_jobs,
                        resume_text=resume_text,
                        threshold=MATCH_SCORE_THRESHOLD,
                    )
                    # Build a map of LLM results
                    llm_map = {j["job_id"]: j for j in llm_scored}

                    # Merge: LLM scores override mock for top candidates
                    scored_jobs = []
                    qualified_ids = []
                    for ms in mock_scored:
                        jid = ms["job_id"]
                        if jid in llm_map:
                            scored_jobs.append(llm_map[jid])
                            if llm_map[jid].get("score", 0) >= MATCH_SCORE_THRESHOLD:
                                qualified_ids.append(jid)
                        else:
                            # Keep mock score for the rest (below LLM threshold)
                            scored_jobs.append(ms)

                    logger.info(
                        f"LLM scored {len(llm_scored)} top candidates, "
                        f"{len(qualified_ids)} qualified"
                    )

                except Exception as llm_err:
                    logger.warning(
                        f"LLM scoring failed ({llm_err}) — using mock scores"
                    )
                    scored_jobs = mock_scored
                    qualified_ids = [
                        j["job_id"] for j in mock_scored
                        if j.get("score", 0) >= MATCH_SCORE_THRESHOLD
                    ]

            # ── Update DB with final scores ──────────────────────
            for scored in scored_jobs:
                job = job_repo.get_by_id(scored["job_id"])
                if job:
                    job.match_score = scored["score"]
                    if scored.get("recommended_action") == "SKIP":
                        job.status = "SKIPPED"
                    db.commit()

            logs.append(
                f"Scored {len(scored_jobs)} jobs — "
                f"{len(qualified_ids)} qualified (>={MATCH_SCORE_THRESHOLD})"
            )

            return {
                **state,
                "scored_jobs": scored_jobs,
                "qualified_job_ids": qualified_ids[:MAX_APPLICATIONS_PER_RUN],
                "logs": logs,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Scoring node failed: {e}")
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
                company_name = resolve_company(job)
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
            logs.append("No qualified jobs to apply to")
            return {**state, "email_drafts": [], "emails_sent": 0, "direct_applied": 0, "logs": logs}

        try:
            import asyncio as _asyncio
            from app.services.apply_service import ApplyService, guess_hr_email

            job_repo = JobRepository(db)
            app_repo = ApplicationRepository(db)
            email_service = EmailService()
            apply_service = ApplyService()
            resume_service = ResumeService()
            resume_text = resume_service.extract_resume_text()

            email_drafts = []
            emails_sent = 0
            direct_applied = 0

            score_map = {j["job_id"]: j for j in scored_jobs}

            applications = []
            recruiter_emails_found = 0

            for job_id in qualified_ids:
                job = job_repo.get_by_id(job_id)
                if not job:
                    continue

                scored = score_map.get(job_id, {})
                score = scored.get("score", 0)
                company_name = resolve_company(job)
                resume_pdf = resume_paths.get(job_id)

                # ── Step 1: Draft personalized cover letter / email ───────
                draft = email_service.draft_email(
                    job_title=job.title,
                    company=company_name,
                    job_description=job.description or "",
                    resume_text=resume_text,
                    match_score=score,
                    recruiter_name=None,
                )
                cover_letter = draft.get("body", "")
                subject = draft.get("subject", f"Application: {job.title} at {company_name}")
                draft["job_id"] = job_id
                draft["job_url"] = job.job_url
                email_drafts.append(draft)

                # Check for explicit recruiter email in JD / post
                hr_emails = guess_hr_email(company_name, job.job_url, jd_text=job.description or "")
                primary_hr_email = hr_emails[0] if hr_emails else None
                if primary_hr_email:
                    recruiter_emails_found += 1

                sent_to_hr = False
                apply_method = "direct_application_link"
                app_route = "Stream B (1-Click Apply Link)"

                # ── Stream A: Recruiter Email Outreach (When explicit HR email found) ──
                if primary_hr_email:
                    sent_to_hr = email_service.send_email(
                        to_email=primary_hr_email,
                        subject=subject,
                        body=cover_letter,
                        pdf_attachment_path=resume_pdf,
                    )
                    if sent_to_hr:
                        emails_sent += 1
                        apply_method = "recruiter_email"
                        app_route = "Stream A (Recruiter Outreach)"
                        logger.info(
                            f"[EMAIL -> HR] [{score}/100] {job.title} @ {company_name} "
                            f"-> {primary_hr_email}"
                        )

                # ── Stream B: Direct Application Link Prep (Job boards & portals) ──
                else:
                    direct_applied += 1
                    apply_method = "direct_application_link"
                    app_route = "Stream B (1-Click Apply Link)"
                    logger.info(
                        f"[APPLY LINK PREPARED] [{score}/100] {job.title} @ {company_name} "
                        f"-> {job.job_url}"
                    )

                # Record application item for Excel report
                applications.append({
                    "title": job.title,
                    "company": company_name,
                    "score": f"{score}/100",
                    "route": app_route,
                    "to_email": primary_hr_email or "None (Direct Link)",
                    "email_sent": sent_to_hr,
                    "resume_path": resume_pdf,
                    "job_url": job.job_url,
                })

                # ── Record in DB ──
                app_repo.create_application(
                    job_id=job_id,
                    resume_id=None,
                    email_sent=sent_to_hr,
                    notes=(
                        f"Score: {score}/100 | "
                        f"Method: {apply_method.upper()} | "
                        f"HR email: {primary_hr_email or 'None (Link in Excel)'} | "
                        f"Resume: {'attached' if resume_pdf else 'none'}"
                    ),
                )
                job.status = "APPLIED"
                db.commit()

            logs.append(
                f"Processed {len(qualified_ids)} qualified jobs: "
                f"{emails_sent} HR emails sent, {direct_applied} 1-click apply links prepared"
            )
            return {
                **state,
                "email_drafts": email_drafts,
                "applications": applications,
                "posts_scanned_for_hr": len(qualified_ids),
                "recruiter_emails_found": recruiter_emails_found,
                "emails_sent": emails_sent,
                "direct_applied": direct_applied,
                "logs": logs,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Apply node failed: {e}")
            errors.append(f"apply_node: {e}")
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
    Node 6: Excel Report Generation & Emailing
    Generates daily multi-tab Excel report and emails it to the candidate.
    """
    def report_node(state: AgentState) -> AgentState:
        logger.info("📊 [Node 6] Report Generation starting...")
        logs = list(state.get("logs", []))
        errors = list(state.get("errors", []))

        try:
            report_service = ReportService()

            scored_jobs = state.get("scored_jobs", [])
            applications = state.get("applications", [])

            run_stats = {
                "total_fetched": state.get("raw_jobs_count", 0),
                "new_jobs": state.get("new_jobs_count", 0),
                "duplicates_skipped": 0,
                "qualified": len(state.get("qualified_job_ids", [])),
                "posts_scanned_for_hr": state.get("posts_scanned_for_hr", len(state.get("qualified_job_ids", []))),
                "recruiter_emails_found": state.get("recruiter_emails_found", 0),
                "emails_sent": state.get("emails_sent", 0),
                "direct_applied": state.get("direct_applied", 0),
                "resumes_generated": len(state.get("resume_paths", {})),
                "whatsapp_sent": state.get("whatsapp_sent", False),
            }

            report_path = report_service.generate_daily_report(
                scored_jobs=scored_jobs,
                applications=applications,
                run_stats=run_stats,
            )

            # ── Generate Dedicated Recruiter & HR Outreach Report ──
            recruiter_report_path = report_service.generate_recruiter_report(
                recruiter_entries=applications,
                stats=run_stats,
            )

            email_svc = EmailService()
            today_str = date.today().strftime("%Y-%m-%d")

            # ── 1. Send Dedicated Recruiter & HR Email Report ──
            if EMAIL_ADDRESS and os.path.exists(recruiter_report_path):
                try:
                    hr_subject = f"📬 [AI Job Agent] Recruiter & HR Outreach Report — {today_str}"
                    hr_body = f"""Hi {CANDIDATE_NAME},

Here is your dedicated Recruiter & HR Outreach and Email Discovery Report for {today_str}.

📊 Recruiter Discovery & Cold Outreach Metrics:
• Total Qualified Posts & JDs Scanned: {run_stats['posts_scanned_for_hr']}
• Verified Recruiter / HR Emails Discovered: {run_stats['recruiter_emails_found']}
• Cold Outreach Dispatched (Stream A): {run_stats['emails_sent']}
• Direct Application Links Prepared (Stream B): {run_stats['direct_applied']}

📎 Attached Excel Workbook:
The dedicated spreadsheet ({os.path.basename(recruiter_report_path)}) is attached containing:
- Original Job/Social Post Links
- Discovered Recruiter/HR Contacts
- Cold Outreach Email Delivery Status
- Tailored ATS Resume Attachment Confirmation
- Outreach Email Subject Lines

Best regards,
AI Job Agent Orchestrator
"""
                    email_svc.send_email(
                        to_email=EMAIL_ADDRESS,
                        subject=hr_subject,
                        body=hr_body,
                        attachment_path=recruiter_report_path,
                    )
                    logger.info(f"✅ Recruiter & HR Excel report emailed to {EMAIL_ADDRESS} with attachment {recruiter_report_path}")
                except Exception as hr_err:
                    logger.warning(f"Failed to email Recruiter HR report: {hr_err}")

            # ── 2. Send General Daily Job Intelligence Report ──
            if EMAIL_ADDRESS and os.path.exists(report_path):
                try:
                    report_subject = f"📊 AI Job Agent Report — {today_str} ({run_stats['qualified']} Eligible Matches)"
                    report_body = f"""Hi {CANDIDATE_NAME},

Please find attached your AI Job Agent daily report for {today_str}.

📊 Execution Summary:
• Total Jobs Ingested: {run_stats['total_fetched']}
• New Jobs Identified: {run_stats['new_jobs']}
• Qualified Matches (0-2 Yrs): {run_stats['qualified']} (Score >= {MATCH_SCORE_THRESHOLD})
• Tailored ATS Resumes Generated: {run_stats['resumes_generated']}
• Recruiter Emails Discovered: {run_stats['recruiter_emails_found']}
• Cold Outreach Dispatched (Stream A): {run_stats['emails_sent']}
• Direct 1-Click Apply Links Prepared (Stream B): {run_stats['direct_applied']}

All job listings, matching skills, direct portal application links, and outreach logs are attached in the Excel file ({os.path.basename(report_path)}).

Best regards,
AI Job Agent Orchestrator
"""
                    email_svc.send_email(
                        to_email=EMAIL_ADDRESS,
                        subject=report_subject,
                        body=report_body,
                        attachment_path=report_path,
                    )
                    logger.info(f"✅ Daily Excel report emailed to {EMAIL_ADDRESS} with attachment {report_path}")
                except Exception as mail_err:
                    logger.warning(f"Failed to email daily Excel report to candidate: {mail_err}")

            logs.append(f"Reports generated: {report_path} | {recruiter_report_path}")
            return {
                **state,
                "report_path": report_path,
                "recruiter_report_path": recruiter_report_path,
                "logs": logs,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"❌ Report node failed: {e}")
            errors.append(f"report_node: {e}")
            return {**state, "report_path": None, "errors": errors}

    return report_node
