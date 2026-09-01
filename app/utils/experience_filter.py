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


from app.utils.experience_analyzer import ExperienceAnalyzer

def validate_0_to_2_years_experience(job_title: str, job_description: str) -> Tuple[bool, str]:
    """
    Validate whether a job aligns with candidate's strict 0-2 years experience target.
    """
    return ExperienceAnalyzer.validate_for_candidate(job_title, job_description)
