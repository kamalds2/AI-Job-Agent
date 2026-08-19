from app.config.settings import CANDIDATE_SKILLS, CANDIDATE_TARGET_ROLES


JOB_SCORING_SYSTEM_PROMPT = """You are an expert technical recruiter and career coach.

Your task is to analyze a job description and score how well it matches a candidate's profile.

Return ONLY a valid JSON object in this exact format:
{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentence explanation>",
  "matching_skills": ["skill1", "skill2"],
  "missing_skills": ["skill3", "skill4"],
  "role_match": <true|false>,
  "experience_match": <true|false>,
  "recommended_action": "<APPLY|SKIP|REVIEW>"
}

Scoring guide:
- 90-100: Perfect match — candidate is exceptionally qualified
- 75-89: Strong match — candidate meets most requirements
- 65-74: Good match — candidate meets core requirements
- 50-64: Partial match — candidate is missing some key skills
- Below 50: Poor match — significant skill gaps
"""


def build_scoring_user_prompt(job_title: str, company: str, job_description: str, resume_text: str) -> str:
    return f"""
## Candidate Profile

**Name:** Kamal Kumar
**Target Roles:** {", ".join(CANDIDATE_TARGET_ROLES)}
**Core Skills:** {", ".join(CANDIDATE_SKILLS)}

**Resume Content:**
{resume_text[:3000]}

---

## Job to Score

**Title:** {job_title}
**Company:** {company}

**Job Description:**
{job_description[:3000]}

---

Score how well this job matches the candidate. Return JSON only.
"""
