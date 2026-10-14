"""
Browser Agent Orchestrator — Coordinates Agent 3 Autonomous Execution:
Harvester (Agent 1) -> Gemini Evaluator & Tailor (Agent 2) -> Easy Apply Submitter (Agent 3)
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agents.browser_agent.chrome_cdp_client import ChromeCDPClient
from app.agents.browser_agent.form_submitter import FormSubmitter
from app.agents.browser_agent.linkedin_harvester import LinkedInHarvester
from app.config.browser_settings import (
    BROWSER_DRY_RUN,
    BROWSER_MATCH_THRESHOLD,
    LINKEDIN_SEARCH_KEYWORDS,
    MAX_APPLICATIONS_PER_BROWSER_RUN,
)
from app.database.database import SessionLocal
from app.models.application import Application
from app.models.job import Job
from app.repositories.application_repository import ApplicationRepository
from app.repositories.job_repository import JobRepository
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService

logger = logging.getLogger(__name__)


class BrowserAgentOrchestrator:
    """
    Coordinates real Chrome browser navigation, Gemini scoring,
    ATS tailoring, and automated Easy Apply submission.
    """

    def __init__(self, dry_run: bool = BROWSER_DRY_RUN):
        self.dry_run = dry_run
        self.cdp_client = ChromeCDPClient()
        self.scoring_service = ScoringService()
        self.resume_service = ResumeService()

    async def run(
        self,
        keywords: Optional[List[str]] = None,
        max_applications: int = MAX_APPLICATIONS_PER_BROWSER_RUN,
    ) -> Dict[str, Any]:
        """
        Executes complete autonomous browser job application pipeline.
        """
        target_keywords = keywords or LINKEDIN_SEARCH_KEYWORDS
        logger.info(f"🚀 [Agent 3 Orchestrator] Starting browser run (Keywords: {target_keywords}, Threshold: {BROWSER_MATCH_THRESHOLD}, Dry-Run: {self.dry_run})")

        stats = {
            "jobs_scanned": 0,
            "jobs_scored": 0,
            "qualified_matches": 0,
            "resumes_tailored": 0,
            "applications_submitted": 0,
            "applied_jobs": [],
            "skipped_jobs": [],
            "errors": [],
        }

        db = SessionLocal()
        page = None

        try:
            # 1. Connect to Real User Chrome
            page = await self.cdp_client.connect()
            harvester = LinkedInHarvester(page)
            submitter = FormSubmitter(page)
            job_repo = JobRepository(db)
            app_repo = ApplicationRepository(db)

            for keyword in target_keywords:
                if stats["applications_submitted"] >= max_applications:
                    break

                logger.info(f"\n🔍 [Agent 3] Processing search keyword: '{keyword}'")

                async for job_data in harvester.search_and_harvest(keyword=keyword, max_jobs=12):
                    if stats["applications_submitted"] >= max_applications:
                        logger.info(f"Reached maximum application limit ({max_applications}) for this run.")
                        break

                    stats["jobs_scanned"] += 1
                    title = job_data["job_title"]
                    company = job_data["company"]
                    desc = job_data["description"]
                    job_url = job_data["job_url"]

                    # 2. Check / Save Job Record in DB
                    existing_job = job_repo.find_by_url(job_url)
                    if not existing_job:
                        db_job = Job(
                            title=title,
                            company=company,
                            location=job_data["location"],
                            description=desc,
                            apply_url=job_url,
                            source="linkedin_browser_agent",
                            status="NEW",
                        )
                        db.add(db_job)
                        db.commit()
                        db.refresh(db_job)
                    else:
                        db_job = existing_job

                    # 3. Gemini Match Scoring (Agent 2)
                    logger.info(f"🧠 [Agent 2] Evaluating '{title}' @ {company}...")
                    score_res = self.scoring_service.score_job(
                        job_id=db_job.id,
                        job_title=title,
                        company=company,
                        job_description=desc,
                    )
                    score = score_res.get("score", 0)
                    stats["jobs_scored"] += 1

                    db_job.match_score = score
                    db_job.scoring_reasoning = score_res.get("reasoning", "")
                    db.commit()

                    if score < BROWSER_MATCH_THRESHOLD:
                        logger.info(f"⏭️ [Agent 2] Score {score}/100 < {BROWSER_MATCH_THRESHOLD} — Skipping '{title}'")
                        stats["skipped_jobs"].append({"title": title, "company": company, "score": score})
                        continue

                    stats["qualified_matches"] += 1
                    logger.info(f"🌟 [Agent 2] High Match ({score}/100) for '{title}' @ {company}!")

                    # 4. Tailor ATS Resume PDF (Agent 2)
                    logger.info(f"📄 [Agent 2] Generating tailored ATS resume for '{title}' @ {company}...")
                    tailored_pdf = self.resume_service.create_tailored_resume(
                        job_id=db_job.id,
                        job_title=title,
                        company=company,
                        job_description=desc,
                    )
                    stats["resumes_tailored"] += 1

                    # 5. Execute Easy Apply Submission (Agent 3)
                    if job_data.get("is_easy_apply"):
                        apply_res = await submitter.apply_to_job(
                            job_title=title,
                            company=company,
                            resume_pdf_path=tailored_pdf,
                            job_url=job_url,
                            dry_run=self.dry_run,
                        )

                        if apply_res["status"] in ["APPLIED_EASY_APPLY", "DRY_RUN_REVIEW_READY"]:
                            stats["applications_submitted"] += 1
                            stats["applied_jobs"].append({
                                "title": title,
                                "company": company,
                                "status": apply_res["status"],
                                "score": score,
                                "resume": tailored_pdf,
                            })

                            # Record in DB
                            app_record = Application(
                                job_id=db_job.id,
                                candidate_name="Meesala Srinivas Rao",
                                candidate_email="srinivasrao6162@gmail.com",
                                status="APPLIED" if not self.dry_run else "DRY_RUN_REVIEW",
                                resume_version=tailored_pdf,
                                applied_at=datetime.utcnow(),
                                notes=f"LinkedIn Easy Apply Browser Agent (Score: {score}/100)",
                            )
                            db.add(app_record)
                            db_job.status = "APPLIED"
                            db.commit()

                            # Delay between applications for human-like behavior
                            await self.cdp_client.human_delay(3.0, 6.0)

                    else:
                        logger.info(f"🔗 [Agent 3] Job is external apply — URL recorded in DB: {job_url}")

        except Exception as e:
            logger.error(f"❌ [Browser Agent Orchestrator] Critical error: {e}")
            stats["errors"].append(str(e))
        finally:
            db.close()
            await self.cdp_client.close()

        return stats
