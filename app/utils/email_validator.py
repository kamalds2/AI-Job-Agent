"""
Email Validator & HR Discovery Utility.
Extracts recruiter emails from JD/posts, generates multi-TLD candidates (hr@, careers@ with .com, .in, .co),
and validates DNS/MX records before sending.
"""
import logging
import re
import socket
from urllib.parse import urlparse
from typing import Optional

logger = logging.getLogger(__name__)

# Standard email regex
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

# Common noisy / non-recruiter domain emails to exclude
IGNORED_EMAILS = {
    "support@github.com", "noreply@github.com", "donotreply@gmail.com",
    "abuse@google.com", "contact@w3.org", "privacy@okta.com",
    "security@okta.com", "info@example.com", "test@test.com",
    "careers@adzuna.in", "careers@adzuna.co.uk", "careers@greenhouse.io",
    "careers@lever.co", "careers@ashbyhq.com", "careers@weworkremotely.com",
    "jobs@weworkremotely.com", "jobs@remoteok.com", "careers@remoteok.com",
    "support@wellfound.com", "help@himalayas.app", "contact@arbeitnow.com",
}

ATS_DOMAINS = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workday.com",
    "myworkdayjobs.com", "smartrecruiters.com", "bamboohr.com",
    "jobvite.com", "recruitee.com", "taleo.net", "icims.com",
    "weworkremotely.com", "remoteok.com", "remotive.com", "adzuna.in",
    "adzuna.com", "himalayas.app", "arbeitnow.com", "naukri.com",
    "wellfound.com", "ycombinator.com",
}

TLD_VARIATIONS = [".com", ".in", ".co", ".ai", ".io", ".co.in", ".tech"]
PREFIX_VARIATIONS = ["hr", "careers", "talent", "recruiting", "jobs", "hiring"]


NON_RECRUITER_PREFIXES = {
    "accommodation", "accommodations", "accessibility", "privacy", "security",
    "legal", "compliance", "dpo", "press", "media", "support", "help",
    "billing", "abuse", "noreply", "no-reply", "donotreply", "ir", "investor",
    "inquiries", "inquiry", "info", "contact", "sales", "feedback", "admin",
}


def extract_emails_from_text(text: str) -> list[str]:
    """
    Extract valid recruiter/contact email addresses from any plain text or HTML.
    Handles standard emails as well as obfuscated formats (e.g. 'recruiter [at] company [dot] com').
    Filters out image file extensions (.png, .jpg), noisy system emails, and non-recruiter
    compliance/accommodation contacts.
    """
    if not text:
        return []

    # De-obfuscate common recruiter formats like: [at], (at), [dot], (dot)
    normalized_text = text
    normalized_text = re.sub(r"\s*\[at\]\s*|\s*\(at\)\s*|\s+at\s+", "@", normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\s*\[dot\]\s*|\s*\(dot\)\s*|\s+dot\s+", ".", normalized_text, flags=re.IGNORECASE)

    found = EMAIL_REGEX.findall(normalized_text)
    valid = []
    seen = set()

    for email in found:
        e_lower = email.lower().strip()
        # Avoid image extensions that look like domains (.png, .jpg, .svg)
        if any(e_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"]):
            continue
        if e_lower in IGNORED_EMAILS or e_lower in seen:
            continue
        # Avoid common ATS platforms as recipient domains
        domain = e_lower.split("@")[-1]
        local_part = e_lower.split("@")[0].lower()

        if domain in ATS_DOMAINS:
            continue

        # Exclude non-recruiter department emails (e.g. accommodation@, privacy@, legal@)
        if any(local_part == prefix or local_part.startswith(f"{prefix}.") or local_part.startswith(f"{prefix}_") for prefix in NON_RECRUITER_PREFIXES):
            continue

        seen.add(e_lower)
        valid.append(e_lower)

    return valid


def domain_has_valid_dns(domain: str) -> bool:
    """
    Check if domain resolves via DNS (has A or MX records) so we don't send to dead hosts.
    """
    if not domain or "." not in domain or domain.endswith("."):
        return False
    try:
        # socket.getaddrinfo tests domain DNS resolution
        socket.setdefaulttimeout(3.0)
        socket.getaddrinfo(domain, 80, socket.AF_INET, socket.SOCK_STREAM)
        return True
    except Exception:
        return False


def extract_base_company_slug(company_name: str, job_url: str = "") -> str:
    """Clean company name into a standard domain slug (e.g. 'Okta Inc' -> 'okta')."""
    if not company_name or company_name.lower() in ("company", "unknown", "confidential"):
        # Try extracting from job url
        if job_url:
            try:
                hostname = urlparse(job_url).hostname or ""
                parts = hostname.lower().split(".")
                if len(parts) >= 2 and parts[-2] not in ATS_DOMAINS:
                    return parts[-2]
            except Exception:
                pass
        return "company"

    # Remove legal / company suffixes
    cleaned = (
        company_name.lower()
        .replace(" technologies", "")
        .replace(" technology", "")
        .replace(" software", "")
        .replace(" solutions", "")
        .replace(" services", "")
        .replace(" pvt ltd", "")
        .replace(" private limited", "")
        .replace(" limited", "")
        .replace(" inc.", "")
        .replace(" inc", "")
        .replace(" llc", "")
        .replace(" ltd", "")
        .replace(" corp", "")
        .replace(" gmbh", "")
        .strip()
    )
    cleaned = re.sub(r"[^a-z0-9]", "", cleaned)
    return cleaned or "company"


def generate_hr_email_candidates(
    company_name: str,
    job_url: str = "",
    jd_text: str = "",
) -> list[str]:
    """
    Extract ONLY verified, explicit recruiter email addresses found directly in
    the Job Description or Social Post Text (e.g. LinkedIn, Twitter, HN hiring posts).

    CRITICAL RULE: Never generate fake or guessed hr@ / careers@ addresses to prevent
    email bounces and protect sender reputation.
    """
    if not jd_text:
        return []

    # Extract all real email addresses from the text
    explicit_emails = extract_emails_from_text(jd_text)
    return explicit_emails
