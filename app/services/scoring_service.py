"""
Scoring Service — uses Claude to score job-resume match.

Returns a structured score with reasoning, matching/missing skills,
and a recommended action (APPLY / SKIP / REVIEW).
"""
import json
import logging
import sys

import anthropic
import httpx

from app.config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from app.prompts.scoring_prompt import JOB_SCORING_SYSTEM_PROMPT, build_scoring_user_prompt

logger = logging.getLogger(__name__)


def _make_anthropic_client() -> anthropic.Anthropic:
    """
    Create Anthropic client with SSL fix for Windows.
    Windows often cannot verify SSL for api.anthropic.com due to missing CA chains.
    We use verify=False via custom httpx transport — safe for read-only API calls.
    """
    if sys.platform == "win32":
        http_client = httpx.Client(verify=False)
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=http_client)
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class ScoringService:
    """
    Uses Claude to evaluate job-resume fit.
    Returns a JSON score object.
    """

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        self.client = _make_anthropic_client()
        self.model = CLAUDE_MODEL

    def score_job(
        self,
        job_title: str,
        company: str,
        job_description: str,
        resume_text: str,
    ) -> dict:
        """
        Score a job against the candidate's resume.

        Returns:
            {
                "score": int (0-100),
                "reasoning": str,
                "matching_skills": list[str],
                "missing_skills": list[str],
                "role_match": bool,
                "experience_match": bool,
                "recommended_action": "APPLY" | "SKIP" | "REVIEW"
            }
        """
        try:
            user_prompt = build_scoring_user_prompt(
                job_title=job_title,
                company=company,
                job_description=job_description,
                resume_text=resume_text,
            )

            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=JOB_SCORING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            content = message.content[0].text.strip()

            # Extract JSON — handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)

            # Validate and clamp score
            score = int(result.get("score", 0))
            result["score"] = max(0, min(100, score))

            logger.info(
                f"✅ Scored '{job_title}' @ {company}: {result['score']}/100 "
                f"[{result.get('recommended_action', 'N/A')}]"
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse Claude JSON response: {e}")
            return self._default_score(job_title, company, f"JSON parse error: {e}")

        except Exception as e:
            logger.error(f"❌ Scoring error for '{job_title}': {e}")
            return self._default_score(job_title, company, str(e))

    def _default_score(self, title: str, company: str, error: str) -> dict:
        return {
            "score": 0,
            "reasoning": f"Scoring failed: {error}",
            "matching_skills": [],
            "missing_skills": [],
            "role_match": False,
            "experience_match": False,
            "recommended_action": "SKIP",
        }

    def batch_score(
        self,
        jobs: list[dict],  # [{"id": int, "title": str, "company": str, "description": str}]
        resume_text: str,
        threshold: int = 65,
    ) -> tuple[list[dict], list[int]]:
        """
        Score a batch of jobs.

        Returns:
            scored_jobs: list of scored job dicts
            qualified_ids: job IDs that meet the threshold
        """
        scored_jobs: list[dict] = []
        qualified_ids: list[int] = []

        for job in jobs:
            job_id = job["id"]
            result = self.score_job(
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                job_description=job.get("description", ""),
                resume_text=resume_text,
            )

            scored_entry = {
                "job_id": job_id,
                "title": job.get("title"),
                "company": job.get("company"),
                "job_url": job.get("job_url"),
                **result,
            }
            scored_jobs.append(scored_entry)

            if result["score"] >= threshold:
                qualified_ids.append(job_id)

        logger.info(
            f"📊 Batch scoring complete: {len(qualified_ids)}/{len(jobs)} "
            f"jobs above threshold ({threshold})"
        )

        return scored_jobs, qualified_ids
