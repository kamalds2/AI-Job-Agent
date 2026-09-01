"""
Scoring Service — Gemini / Claude / OpenAI / Mock cascade.

Priority configurable via LLM_PROVIDER in settings / .env:
  Default: Gemini → Claude → OpenAI → Mock
  (or Claude → Gemini → OpenAI → Mock if LLM_PROVIDER=claude)

All providers return the same dict schema:
  {score, reasoning, matching_skills, missing_skills,
   role_match, experience_match, recommended_action}
"""
import json
import logging
import sys
from typing import Optional

import httpx

from app.config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    CLAUDE_MODEL,
    LLM_PROVIDER,
    MOCK_SCORING,
)
from app.prompts.scoring_prompt import JOB_SCORING_SYSTEM_PROMPT, build_scoring_user_prompt
from app.utils.gemini_client import GeminiClient, get_gemini_client

logger = logging.getLogger(__name__)


# ── LLM client factories ────────────────────────────────────────────────────

def _make_anthropic_client():
    """Anthropic client."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize Anthropic client: {e}")
        return None


def _make_openai_client():
    """OpenAI client with SSL fix for Windows."""
    try:
        import openai
        if sys.platform == "win32":
            return openai.OpenAI(
                api_key=OPENAI_API_KEY,
                http_client=httpx.Client(verify=False),
            )
        return openai.OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        return None


# ── Score helpers ────────────────────────────────────────────────────────────

def _parse_llm_response(content: str, source: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown fences."""
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        result = json.loads(content.strip())
        result["score"] = max(0, min(100, int(result.get("score", 0))))
        result["_source"] = source
        return result
    except Exception as e:
        logger.warning(f"Failed to parse {source} response: {e}")
        return None


def _default_score(title: str, company: str, error: str, source: str = "error") -> dict:
    return {
        "score": 0,
        "reasoning": f"Scoring failed ({source}): {error}",
        "matching_skills": [],
        "missing_skills": [],
        "role_match": False,
        "experience_match": False,
        "recommended_action": "SKIP",
        "_source": source,
    }


# ── Per-LLM scoring functions ────────────────────────────────────────────────

def _score_with_gemini(
    client: GeminiClient,
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str,
) -> Optional[dict]:
    """Score using Google Gemini API."""
    try:
        user_prompt = build_scoring_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            resume_text=resume_text,
        )
        response_text = client.generate_content(
            prompt=user_prompt,
            system_instruction=JOB_SCORING_SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.1,
            max_output_tokens=1024,
        )
        if not response_text:
            return None

        result = _parse_llm_response(response_text, f"gemini ({client.model})")
        if result:
            logger.info(
                f"[Gemini-{client.model}] '{job_title}' @ {company}: "
                f"{result['score']}/100 [{result.get('recommended_action')}]"
            )
        return result
    except Exception as e:
        logger.warning(f"[Gemini] Failed for '{job_title}': {e}")
        return None


def _score_with_claude(
    client,
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str,
) -> Optional[dict]:
    """Score using Claude. Returns None on any error."""
    try:
        user_prompt = build_scoring_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            resume_text=resume_text,
        )
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=JOB_SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = _parse_llm_response(message.content[0].text, "claude")
        if result:
            logger.info(
                f"[Claude] '{job_title}' @ {company}: "
                f"{result['score']}/100 [{result.get('recommended_action')}]"
            )
        return result
    except Exception as e:
        logger.warning(f"[Claude] Failed for '{job_title}': {e}")
        return None


def _score_with_openai(
    client,
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str,
) -> Optional[dict]:
    """Score using OpenAI gpt-4o-mini. Returns None on any error."""
    try:
        user_prompt = build_scoring_user_prompt(
            job_title=job_title,
            company=company,
            job_description=job_description,
            resume_text=resume_text,
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[
                {"role": "system", "content": JOB_SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        result = _parse_llm_response(response.choices[0].message.content, "openai")
        if result:
            logger.info(
                f"[OpenAI] '{job_title}' @ {company}: "
                f"{result['score']}/100 [{result.get('recommended_action')}]"
            )
        return result
    except Exception as e:
        logger.warning(f"[OpenAI] Failed for '{job_title}': {e}")
        return None


# ── Main ScoringService ──────────────────────────────────────────────────────

class ScoringService:
    """
    AI scoring cascade: Gemini / Claude / OpenAI → Mock heuristic.

    Automatically falls back to the next provider if the current one
    fails due to connection errors, credit exhaustion, or rate limits.
    """

    def __init__(self):
        self._gemini = get_gemini_client()
        self._claude = None
        self._openai = None

        if ANTHROPIC_API_KEY:
            self._claude = _make_anthropic_client()

        if OPENAI_API_KEY:
            self._openai = _make_openai_client()

        if not self._gemini and not self._claude and not self._openai:
            logger.warning(
                "No LLM API keys configured — will use mock scoring. "
                "Set GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY in .env"
            )

    def _get_providers_order(self) -> list[str]:
        """Determine order of providers based on settings & availability."""
        pref = LLM_PROVIDER.lower()
        if pref == "gemini":
            return ["gemini"]
        elif pref == "claude":
            return ["claude"]
        elif pref == "openai":
            return ["openai"]
        else:
            return ["gemini", "claude", "openai"]

    def score_job(
        self,
        job_title: str,
        company: str,
        job_description: str,
        resume_text: str,
    ) -> dict:
        """
        Score a job. Cascades across available LLMs → Mock.
        Strictly enforces 0-2 years experience guard before LLM scoring.
        """
        from app.utils.experience_filter import validate_0_to_2_years_experience

        # 0. Strict 0-2 Years Experience Guard Check
        is_exp_valid, exp_reason = validate_0_to_2_years_experience(job_title, job_description)
        if not is_exp_valid:
            logger.info(f"🚫 [Exp Guard] Skipped '{job_title}' @ {company}: {exp_reason}")
            return {
                "score": 0,
                "reasoning": f"FILTERED (0-2 Yrs Target Guard): {exp_reason}",
                "matching_skills": [],
                "missing_skills": [],
                "role_match": False,
                "experience_match": False,
                "recommended_action": "SKIP",
                "_source": "experience_filter",
            }

        result = None
        if not MOCK_SCORING:
            providers = self._get_providers_order()
            for provider in providers:
                if provider == "gemini" and self._gemini:
                    result = _score_with_gemini(
                        self._gemini, job_title, company,
                        job_description[:3500], resume_text,
                    )
                    if result:
                        break
                elif provider == "claude" and self._claude:
                    result = _score_with_claude(
                        self._claude, job_title, company,
                        job_description[:3000], resume_text,
                    )
                    if result:
                        break
                elif provider == "openai" and self._openai:
                    result = _score_with_openai(
                        self._openai, job_title, company,
                        job_description[:3000], resume_text,
                    )
                    if result:
                        break

        # Fallback to mock scoring if no LLM returned result
        if not result:
            from app.services.mock_scoring_service import mock_score_job
            result = mock_score_job(job_title, company, job_description, resume_text)

        # Final post-check: if LLM mistakenly returned high score for senior/3+ yrs role, override
        if not result.get("experience_match", True):
            result["score"] = min(result.get("score", 0), 40)
            result["recommended_action"] = "SKIP"

        return result

    def batch_score(
        self,
        jobs: list[dict],
        resume_text: str,
        threshold: int = 65,
    ) -> tuple[list[dict], list[int]]:
        """Score a batch of jobs in parallel using ThreadPoolExecutor."""
        import concurrent.futures

        scored_jobs: list[dict] = []
        qualified_ids: list[int] = []

        def _score_single(job: dict) -> dict:
            res = self.score_job(
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                job_description=job.get("description", ""),
                resume_text=resume_text,
            )
            return {
                "job_id": job["id"],
                "title": job.get("title"),
                "company": job.get("company"),
                "job_url": job.get("job_url"),
                **res,
            }

        # Run with max_workers=2 to stay within Gemini API rate limits smoothly
        max_workers = min(2, len(jobs)) if jobs else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_job = {}
            for j in jobs:
                future_to_job[executor.submit(_score_single, j)] = j

            for future in concurrent.futures.as_completed(future_to_job):
                try:
                    entry = future.result()
                    scored_jobs.append(entry)
                    if (
                        entry.get("score", 0) >= threshold
                        and entry.get("experience_match") is True
                        and entry.get("recommended_action") in ("APPLY", "REVIEW")
                    ):
                        qualified_ids.append(entry["job_id"])
                except Exception as e:
                    logger.warning(f"Error scoring job: {e}")

        source_counts: dict[str, int] = {}
        for j in scored_jobs:
            s = j.get("_source", "unknown")
            source_counts[s] = source_counts.get(s, 0) + 1

        logger.info(
            f"Batch scoring complete: {len(qualified_ids)}/{len(jobs)} qualified "
            f"(>={threshold}) | sources: {source_counts}"
        )
        return scored_jobs, qualified_ids
