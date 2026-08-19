"""
Mock Scoring Service — for testing the full pipeline without Claude API credits.

Uses keyword-matching heuristics to simulate Claude's scoring.
Activate by setting MOCK_SCORING=true in .env
"""
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# Skills Kamal has — matched against job description for scoring
KAMAL_SKILLS = {
    # High-weight (Java/Backend core)
    "java": 15, "spring": 12, "spring boot": 12, "microservices": 10,
    "rest api": 8, "restful": 8, "jpa": 6, "hibernate": 6,
    "maven": 5, "gradle": 5, "junit": 5,

    # Medium-weight (Cloud/Platform)
    "aws": 10, "cloud": 8, "docker": 8, "kubernetes": 7, "k8s": 7,
    "terraform": 6, "ci/cd": 6, "jenkins": 5, "git": 4,

    # AI/ML upskilling
    "ai": 6, "machine learning": 6, "llm": 8, "langchain": 8,
    "openai": 6, "python": 7, "fastapi": 7, "pytorch": 5,
    "agent": 6, "rag": 6, "vector": 5,

    # Database
    "postgresql": 5, "mysql": 5, "redis": 5, "mongodb": 4,
    "sql": 5, "nosql": 4,

    # Bonus
    "backend": 5, "api": 4, "distributed": 5, "scalable": 3,
    "agile": 3, "senior": 2, "lead": 2,
}

# Keywords that REDUCE score (clearly wrong role)
PENALTY_KEYWORDS = {
    "mobile": -10, "ios": -15, "android": -15, "react native": -10,
    "frontend": -10, "react": -5, "angular": -5, "vue": -5,
    "ui/ux": -15, "design": -8, "qa": -8, "test engineer": -8,
    "sales": -20, "marketing": -20, "finance": -20, "hr": -20,
    "legal": -20, "paralegal": -20, "accounting": -15,
    "firefighter": -30, "nurse": -30, "driver": -25,
    "golang": -5, "ruby": -5, "php": -5, ".net": -3,
}


def mock_score_job(
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str,
) -> dict:
    """
    Heuristic scoring without Claude API.
    Returns same format as ScoringService.score_job().
    """
    text = (job_title + " " + job_description).lower()
    score = 30  # Base score

    matching_skills = []
    missing_skills = []

    # Add points for matching skills
    for skill, points in KAMAL_SKILLS.items():
        if skill in text:
            score += points
            matching_skills.append(skill)

    # Apply penalties
    for kw, penalty in PENALTY_KEYWORDS.items():
        if kw in text:
            score += penalty

    # Senior role bonus
    title_lower = job_title.lower()
    if any(t in title_lower for t in ["senior", "staff", "principal", "lead", "architect"]):
        score += 5
    if "junior" in title_lower or "intern" in title_lower:
        score -= 15

    # Remote/India bonus
    if "remote" in text or "india" in text or "bangalore" in text or "hyderabad" in text:
        score += 5

    # Clamp
    score = max(0, min(100, score))

    # Find missing critical skills
    critical = ["java", "spring", "aws", "python", "docker"]
    for skill in critical:
        if skill not in matching_skills:
            missing_skills.append(skill)

    # Determine action
    if score >= 70:
        action = "APPLY"
        reasoning = f"Strong match ({score}/100). Found: {', '.join(matching_skills[:5])}."
    elif score >= 55:
        action = "REVIEW"
        reasoning = f"Moderate match ({score}/100). Some overlap with Java/backend profile."
    else:
        action = "SKIP"
        reasoning = f"Low relevance ({score}/100). Limited match with Java/Spring/AWS skills."

    logger.info(f"[MOCK] '{job_title}' @ {company}: {score}/100 [{action}]")

    return {
        "score": score,
        "reasoning": reasoning,
        "matching_skills": matching_skills[:8],
        "missing_skills": missing_skills[:5],
        "role_match": score >= 55,
        "experience_match": score >= 60,
        "recommended_action": action,
        "mock": True,  # Flag so we know it's not a real Claude score
    }


def mock_batch_score(
    jobs: list[dict],
    resume_text: str,
    threshold: int = 65,
) -> tuple[list[dict], list[int]]:
    """Batch mock scoring — mirrors ScoringService.batch_score()."""
    scored_jobs = []
    qualified_ids = []

    for job in jobs:
        result = mock_score_job(
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", ""),
            resume_text=resume_text,
        )
        scored_entry = {
            "job_id": job["id"],
            "title": job.get("title"),
            "company": job.get("company"),
            "job_url": job.get("job_url"),
            **result,
        }
        scored_jobs.append(scored_entry)
        if result["score"] >= threshold:
            qualified_ids.append(job["id"])

    qualified_ids.sort(key=lambda jid: next(
        (j["score"] for j in scored_jobs if j["job_id"] == jid), 0
    ), reverse=True)

    logger.info(
        f"[MOCK] Batch scored {len(scored_jobs)} jobs, "
        f"{len(qualified_ids)} qualified (>={threshold})"
    )
    return scored_jobs, qualified_ids
