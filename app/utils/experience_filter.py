"""
Experience Filter Utility.
Enforces strict 0-2 years experience targeting for job scoring and application.

Target Profile:
  - Candidate Experience Target: 0 to 2 years ONLY (Junior, Associate, Entry Level, Graduate, 0-2 yrs).
  - Hard Blocked: Any role requiring >2 years of experience (e.g. 3+, 3-5, 4+, 5+ years)
    or containing Senior/Staff/Lead/Manager/Architect titles.
"""
import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# Keywords in job title that immediately indicate >2 years seniority
SENIOR_TITLE_KEYWORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect",
    "director", "vp ", "vice president", "head of", "manager", "executive",
    "chief", "lead engineer", "team lead", "technical lead", "tech lead",
    "sr developer", "sr software", "sr backend", "senior backend", "expert",
    "specialist iii", "specialist iv", "specialist v",
    "engineer iii", "engineer iv", "engineer v", "level 3", "level 4", "level 5",
    "l5", "l6", "l7", "mid-senior", "senior-level",
]

# Keywords in job title that explicitly indicate 0-2 years target
JUNIOR_TITLE_KEYWORDS = [
    "junior", "associate", "entry level", "entry-level", "fresher", "graduate",
    "trainee", "intern", "internship", "apprentice", "0-2", "early career",
    "new grad", "new graduate",
]

# Comprehensive regex patterns to detect required years of experience in job text
EXP_RANGE_PATTERN = re.compile(r"(\d+)\+?\s*(?:-|to)\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE)
EXP_MIN_PATTERNS = [
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience", re.IGNORECASE),
    re.compile(r"experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"minimum\s*(?:of)?\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"at\s+least\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+required", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:in|of)\s+[a-z0-9\s,/-]{2,30}(?:development|engineering|programming|software|java|python|backend)", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:relevant|hands-on|proven|commercial)\s+experience", re.IGNORECASE),
]


def validate_0_to_2_years_experience(job_title: str, job_description: str) -> Tuple[bool, str]:
    """
    Validate whether a job aligns with candidate's strict 0-2 years experience target.

    Returns:
        (is_valid: bool, reason: str)
        If is_valid is False, the job MUST NOT be scored >=65 or applied to.
    """
    title_lower = (job_title or "").lower().strip()
    desc_clean = (job_description or "").lower().strip()
    combined_text = f"{title_lower} {desc_clean}"

    # 1. Check title for Senior / Executive / Lead keywords
    for kw in SENIOR_TITLE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
            return False, f"Title contains senior/lead keyword '{kw}' (exceeds 0-2 years target)"

    # 2. Check for experience ranges (e.g. 3-5 years, 2-4 years, 4-6 years)
    for match in EXP_RANGE_PATTERN.finditer(combined_text):
        low_str, high_str = match.group(1), match.group(2)
        if low_str.isdigit() and high_str.isdigit():
            low, high = int(low_str), int(high_str)
            # If the minimum requirement is 3 or more (e.g. 3-5 years) -> reject
            if low >= 3:
                return False, f"Job requires {low}-{high} years of experience (exceeds 0-2 years target)"
            # If the range is 2-4, 2-5, or 2-6 years -> reject (target is strictly 0-2 years)
            if low >= 2 and high >= 4:
                return False, f"Job requires {low}-{high} years of experience (exceeds 0-2 years target)"

    # 3. Check for single/minimum experience requirements (e.g. 3+ years, 4+ years, minimum 5 years)
    for pattern in EXP_MIN_PATTERNS:
        for match in pattern.finditer(combined_text):
            exp_str = match.group(1)
            if exp_str and exp_str.isdigit():
                exp = int(exp_str)
                if exp >= 3:
                    return False, f"Job description requires {exp}+ years of experience (exceeds 0-2 years target)"

    # 4. Check for explicit 0-2 years / Junior title match
    is_explicit_junior = any(re.search(r"\b" + re.escape(kw) + r"\b", title_lower) for kw in JUNIOR_TITLE_KEYWORDS)
    if is_explicit_junior:
        return True, "Aligned with 0-2 years junior/associate role"

    return True, "Within acceptable 0-2 years experience range"
