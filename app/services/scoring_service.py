"""
Scoring Service — Claude → OpenAI → Mock cascade.

Priority:
  1. Claude (claude-sonnet-4-5) — best quality
  2. OpenAI (gpt-4o-mini) — fallback if Claude fails or low credit
  3. Mock heuristic — final fallback, no API needed

All three return the same dict schema:
  {score, reasoning, matching_skills, missing_skills,
   role_match, experience_match, recommended_action}
"""
import json
import logging
import sys
from typing import Optional

import httpx

from app.config.settings import (
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    CLAUDE_MODEL,
    MOCK_SCORING,
)
from app.prompts.scoring_prompt import JOB_SCORING_SYSTEM_PROMPT, build_scoring_user_prompt

logger = logging.getLogger(__name__)


# ── LLM client factories ────────────────────────────────────────────────────

def _make_anthropic_client():
    """Anthropic client with SSL fix for Windows."""
    try:
        import anthropic
        if sys.platform == "win32":
            return anthropic.Anthropic(
                api_key=ANTHROPIC_API_KEY,
                http_client=httpx.Client(verify=False),
            )
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
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
    AI scoring cascade: Claude → OpenAI → Mock.

    Automatically falls back to the next provider if the current one
    fails due to connection errors, credit exhaustion, or rate limits.
    """

    def __init__(self):
        self._claude = None
        self._openai = None

        if ANTHROPIC_API_KEY:
            self._claude = _make_anthropic_client()

        if OPENAI_API_KEY:
            self._openai = _make_openai_client()

        if not self._claude and not self._openai:
            logger.warning(
                "No LLM API keys configured — will use mock scoring. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env"
            )

    def score_job(
        self,
        job_title: str,
        company: str,
        job_description: str,
        resume_text: str,
    ) -> dict:
        """
        Score a job. Cascades: Claude → OpenAI → Mock.
        Always returns a valid score dict.
        """
        # 1. Try Claude
        if self._claude and not MOCK_SCORING:
            result = _score_with_claude(
                self._claude, job_title, company,
                job_description[:3000], resume_text,
            )
            if result:
                return result

        # 2. Try OpenAI
        if self._openai and not MOCK_SCORING:
            result = _score_with_openai(
                self._openai, job_title, company,
                job_description[:3000], resume_text,
            )
            if result:
                return result

        # 3. Mock heuristic fallback
        if MOCK_SCORING:
            logger.debug(f"[Mock] Scoring '{job_title}' (MOCK_SCORING=true)")
        else:
            logger.warning(f"Both LLMs failed for '{job_title}' — using mock scoring")

        from app.services.mock_scoring_service import mock_score_job
        return mock_score_job(job_title, company, job_description, resume_text)

    def batch_score(
        self,
        jobs: list[dict],
        resume_text: str,
        threshold: int = 65,
    ) -> tuple[list[dict], list[int]]:
        """Score a batch of jobs. Returns (scored_jobs, qualified_ids)."""
        scored_jobs: list[dict] = []
        qualified_ids: list[int] = []

        for job in jobs:
            result = self.score_job(
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                job_description=job.get("description", ""),
                resume_text=resume_text,
            )
            entry = {
                "job_id": job["id"],
                "title": job.get("title"),
                "company": job.get("company"),
                "job_url": job.get("job_url"),
                **result,
            }
            scored_jobs.append(entry)
            if result["score"] >= threshold:
                qualified_ids.append(job["id"])

        source_counts: dict[str, int] = {}
        for j in scored_jobs:
            s = j.get("_source", "unknown")
            source_counts[s] = source_counts.get(s, 0) + 1

        logger.info(
            f"Batch scoring: {len(qualified_ids)}/{len(jobs)} qualified "
            f"(>={threshold}) | sources: {source_counts}"
        )
        return scored_jobs, qualified_ids
