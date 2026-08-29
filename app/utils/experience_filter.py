"""
Experience Filter Utility.
Enforces strict 0-2 years experience targeting for job scoring and application.

Target Profile:
  - Candidate Experience Target: 0 to 2 years ONLY (Junior, Associate, Entry Level, Graduate, 0-2 yrs).
  - Blocked Roles: Any role requiring >=3 years experience or containing Senior/Staff/Lead/Manager titles.
"""
import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# Keywords in job title that immediately indicate >2 years seniority
SENIOR_TITLE_KEYWORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect",
    "director", "vp ", "vice president", "head of", "manager", "executive",
    "chief", "lead engineer", "team lead", "technical lead", "sr developer",
]

# Keywords in job title that explicitly indicate 0-2 years target
JUNIOR_TITLE_KEYWORDS = [
    "junior", "associate", "entry level", "fresher", "graduate",
    "trainee", "intern", "apprentice", "0-2", "early career",
]

# Regex patterns to detect required years of experience in job text
EXP_PATTERNS = [
    re.compile(r"(\d+)\+?\s*(?:-\s*(\d+)\+?)?\s*(?:years?|yrs?)(?:\s+of)?\s+experience", re.IGNORECASE),
    re.compile(r"experience\s*:\s*(\d+)\+?\s*(?:-\s*(\d+)\+?)?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"minimum\s*(?:of)?\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"at\s+least\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+required", re.IGNORECASE),
]


def validate_0_to_2_years_experience(job_title: str, job_description: str) -> Tuple[bool, str]:
    """
    Validate whether a job aligns with candidate's strict 0-2 years experience target.

    Returns:
        (is_valid: bool, reason: str)
        If is_valid is False, the job MUST NOT be scored >=65 or applied to.
    """
    title_lower = (job_title or "").lower().strip()
    text_lower = (job_title + " " + (job_description or "")).lower().strip()

    # 1. Check title for Senior / Executive keywords
    for kw in SENIOR_TITLE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
            return False, f"Title contains senior/lead keyword '{kw}' (exceeds 0-2 years target)"

    # 2. Check for explicit 0-2 years / Junior title bonus
    is_explicit_junior = any(re.search(r"\b" + re.escape(kw) + r"\b", title_lower) for kw in JUNIOR_TITLE_KEYWORDS)

    # 3. Parse required years of experience from description
    min_exp_found = []
    for pattern in EXP_PATTERNS:
        matches = pattern.findall(text_lower)
        for m in matches:
            val_str = m[0] if isinstance(m, tuple) else m
            if val_str and val_str.isdigit():
                min_exp_found.append(int(val_str))

    if min_exp_found:
        max_min_exp = max(min_exp_found)
        # If any experience requirement mentions >=3 years, hard block
        for exp in min_exp_found:
            if exp >= 3:
                return False, f"Requires {exp}+ years of experience (exceeds 0-2 years target)"

    # If title is explicitly Junior / Associate / Software Engineer without senior keywords, it's valid
    if is_explicit_junior:
        return True, "Aligned with 0-2 years junior/associate role"

    return True, "Within acceptable 0-2 years experience range"
