"""
Smart Experience Analyzer for Finance Roles (Fresher / 0-1 Years Target).
Accurately detects 0-1 years, internships, and fresher roles while eliminating
false positives caused by reporting hierarchy ('reports to Senior Manager')
or company history ('10+ years in finance').
"""
import re
from typing import Dict


class FinanceExperienceAnalyzer:
    """
    Experience analyzer for Finance & Accounting jobs (Fresher / 0-1 years target).
    """

    # Strictly senior titles that a 0-1 year fresher cannot hold
    STRICT_SENIOR_TITLE_KEYWORDS = [
        r"\bsenior\b", r"\bsr\.?\b", r"\blead\b", r"\bprincipal\b",
        r"\bdirector\b", r"\bvp\b", r"\bvice\s+president\b",
        r"\bhead\s+of\b", r"\bchief\b", r"\bcxo\b", r"\bcfo\b",
        r"\bavp\b", r"\bdgm\b", r"\bgm\b"
    ]

    # Explicit fresher signals in Title or JD
    EXPLICIT_FRESHER_SIGNALS = [
        r"\b0\s*(?:to|-|–|—)\s*1\s*(?:years?|yrs?)\b",
        r"\b0\s*(?:to|-|–|—)\s*2\s*(?:years?|yrs?)\b",
        r"\b0\s*\+\s*(?:years?|yrs?)\b",
        r"\b1\s*(?:year|yr)\b",
        r"\bfreshers?\b",
        r"\bintern(?:ship)?\b",
        r"\bentry\s*level\b",
        r"\bjunior\b",
        r"\btrainee\b",
        r"\bgraduate\b",
        r"\bmba\s*fresher\b",
        r"\bfresher\s*mba\b",
        r"\bno\s*experience\s*(?:required|needed)\b",
        r"\bassociate\b",
    ]

    # Strict mid/senior experience requirements specifically tied to work experience
    STRICT_EXPERIENCE_REQUIREMENT_PATTERNS = [
        r"\b(?:minimum|min|at\s+least|requires?|required|requiring)\s+(?:of\s+)?([2-9]|\d{2,})\s*(?:\+|(?:to|-|–|—)\s*\d+)?\s*(?:years?|yrs?|yr)\s+(?:of\s+)?(?:relevant\s+|work\s+|professional\s+|industry\s+)?(?:experience|exp)\b",
        r"\b(?:experience|exp)\s*(?:required)?\s*[:\-–]\s*([2-9]|\d{2,})\s*(?:\+|(?:to|-|–|—)\s*\d+)?\s*(?:years?|yrs?|yr)\b",
        r"\b([2-9]|\d{2,})\s*\+\s*(?:years?|yrs?|yr)\s+(?:of\s+)?(?:relevant\s+|work\s+|corporate\s+)?(?:experience|exp)\b",
        r"\b([2-9]|\d{2,})\s*(?:to|-|–|—)\s*\d+\s*(?:years?|yrs?|yr)\s+(?:of\s+)?(?:relevant\s+|work\s+|corporate\s+)?(?:experience|exp)\b",
    ]

    @classmethod
    def analyze_title(cls, job_title: str) -> Dict:
        title_lower = (job_title or "").lower()

        # If title explicitly indicates fresher/junior/trainee/intern/associate, it is ELIGIBLE!
        for f_pat in [r"\btrainee\b", r"\bintern\b", r"\binternship\b", r"\bfresher\b", r"\bjunior\b", r"\bassociate\b", r"\bentry\s*level\b", r"\b0\s*-\s*1\b"]:
            if re.search(f_pat, title_lower):
                return {"eligible": True, "reason": "Title explicitly indicates Fresher / Junior / Associate level", "exp_years": 0.5}

        # Check for strict senior title keywords (e.g. Senior Analyst, VP, Lead, Director)
        for pat in cls.STRICT_SENIOR_TITLE_KEYWORDS:
            m = re.search(pat, title_lower)
            if m:
                return {
                    "eligible": False,
                    "reason": f"Job Title contains senior keyword '{m.group(0)}'",
                    "exp_years": 0.0,
                }

        # Check for explicit 2+ years in title (e.g. "Financial Analyst (3+ years)")
        m_num = re.search(r"\b([2-9]|\d{2,})\s*\+\s*(?:years?|yrs?)\b", title_lower)
        if m_num:
            return {
                "eligible": False,
                "reason": f"Title requires '{m_num.group(0)}' experience",
                "exp_years": 0.0,
            }

        return {"eligible": True, "reason": "Title eligible (Fresher / 0-1 yrs)", "exp_years": 1.0}

    @classmethod
    def analyze(cls, job_title: str, job_description: str) -> Dict:
        # 1. Check title first
        title_res = cls.analyze_title(job_title)
        if not title_res["eligible"]:
            return title_res

        desc_lower = (job_description or "").lower()

        # 2. Check if JD has explicit Fresher / 0-1 years indicators
        for f_pat in cls.EXPLICIT_FRESHER_SIGNALS:
            if re.search(f_pat, desc_lower):
                return {
                    "eligible": True,
                    "reason": f"Job matches fresher criteria (found '{f_pat}')",
                    "exp_years": 0.5,
                }

        # 3. Check if JD strictly requires >= 2 years of work experience
        for req_pat in cls.STRICT_EXPERIENCE_REQUIREMENT_PATTERNS:
            m = re.search(req_pat, desc_lower)
            if m:
                matched_str = m.group(0)
                return {
                    "eligible": False,
                    "reason": f"Job requires '{matched_str}' (Exceeds 0-1 yrs bracket)",
                    "exp_years": 0.0,
                }

        # 4. Default: If not disqualified by strict >= 2 yrs requirement, allow application
        return {"eligible": True, "reason": "Eligible for 0-1 yrs Finance profile", "exp_years": 1.0}
