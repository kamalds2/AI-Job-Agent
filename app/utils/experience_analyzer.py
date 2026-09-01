"""
Experience Analyzer Utility.
Extracts minimum and maximum years of experience from job titles and descriptions
and validates alignment with candidate's 0-2 years target profile.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Senior / Lead keywords in title that immediately disqualify for 0-2 yrs candidate
SENIOR_TITLE_KEYWORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect",
    "director", "vp ", "vice president", "head of", "manager", "executive",
    "chief", "lead engineer", "team lead", "technical lead", "tech lead",
    "sr developer", "sr software", "sr backend", "senior backend", "expert",
    "specialist iii", "specialist iv", "specialist v",
    "engineer iii", "engineer iv", "engineer v", "level 3", "level 4", "level 5",
    "l5", "l6", "l7", "mid-senior", "senior-level",
]

# Junior / Entry keywords in title that confirm 0-2 yrs candidate target
JUNIOR_TITLE_KEYWORDS = [
    "junior", "associate", "entry level", "entry-level", "fresher", "graduate",
    "trainee", "intern", "internship", "apprentice", "0-2", "early career",
    "new grad", "new graduate",
]

EXP_RANGE_REGEX = re.compile(r"(\d+)\+?\s*(?:-|to)\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE)
EXP_MIN_REGEXES = [
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience", re.IGNORECASE),
    re.compile(r"experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"minimum\s*(?:of)?\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"at\s+least\s*(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+required", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:in|of)\s+[a-z0-9\s,/-]{2,30}(?:development|engineering|programming|software|java|python|backend)", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:relevant|hands-on|proven|commercial)\s+experience", re.IGNORECASE),
]


@dataclass
class ExperienceRequirement:
    min_years: float
    max_years: Optional[float]
    is_fresher_eligible: bool
    is_senior_title: bool
    is_junior_title: bool
    raw_match: str


class ExperienceAnalyzer:
    """Analyzes and extracts experience requirements from job text."""

    MAX_CANDIDATE_EXPERIENCE = 2.0  # Kamal Kumar: strictly 0-2 years target

    @classmethod
    def analyze(cls, job_title: str, job_description: str) -> ExperienceRequirement:
        title_lower = (job_title or "").lower().strip()
        desc_lower = (job_description or "").lower().strip()
        combined = f"{title_lower} {desc_lower}"

        is_senior = any(re.search(r"\b" + re.escape(kw) + r"\b", title_lower) for kw in SENIOR_TITLE_KEYWORDS)
        is_junior = any(re.search(r"\b" + re.escape(kw) + r"\b", title_lower) for kw in JUNIOR_TITLE_KEYWORDS)

        # Check explicit fresher / internship
        is_fresher = is_junior or any(k in combined for k in ["fresher", "freshers", "entry level", "graduate trainee", "0 years"])

        min_years = 0.0
        max_years = None
        raw_match = ""

        # 1. Check for range (e.g. 0-2, 1-3, 3-5 years)
        range_match = EXP_RANGE_REGEX.search(combined)
        if range_match:
            min_years = float(range_match.group(1))
            max_years = float(range_match.group(2))
            raw_match = range_match.group(0)

        # 2. Check for single minimum (e.g. 3+ years, min 5 years)
        if not range_match:
            for pat in EXP_MIN_REGEXES:
                m = pat.search(combined)
                if m:
                    min_years = float(m.group(1))
                    raw_match = m.group(0)
                    break

        return ExperienceRequirement(
            min_years=min_years,
            max_years=max_years,
            is_fresher_eligible=is_fresher,
            is_senior_title=is_senior,
            is_junior_title=is_junior,
            raw_match=raw_match,
        )

    @classmethod
    def validate_for_candidate(cls, job_title: str, job_description: str) -> Tuple[bool, str]:
        """
        Validate if the job is strictly acceptable for a 0-2 years candidate.
        Returns: (is_valid: bool, reason: str)
        """
        req = cls.analyze(job_title, job_description)

        if req.is_senior_title:
            return False, "Title contains senior/lead keyword (exceeds 0-2 years target)"

        # If min years required is >= 3 -> reject
        if req.min_years >= 3.0:
            return False, f"Requires {int(req.min_years)}+ years experience (exceeds 0-2 years target)"

        # If range like 2-4 or 2-5 -> reject
        if req.min_years >= 2.0 and req.max_years and req.max_years >= 4.0:
            return False, f"Requires {int(req.min_years)}-{int(req.max_years)} years experience (exceeds 0-2 years target)"

        if req.is_junior_title or req.is_fresher_eligible:
            return True, "Aligned with 0-2 years junior/associate role"

        return True, "Within acceptable 0-2 years experience range"
