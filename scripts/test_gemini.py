"""
Test Google Gemini API Integration.
Verifies Gemini scoring, resume tailoring, and email drafting.
"""
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
    CANDIDATE_NAME,
    CANDIDATE_SKILLS,
)
from app.utils.gemini_client import get_gemini_client
from app.services.scoring_service import ScoringService
from app.services.email_service import EmailService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    print("\n" + "=" * 60)
    print("🤖 TESTING GEMINI API INTEGRATION")
    print("=" * 60)
    print(f"LLM_PROVIDER : {LLM_PROVIDER}")
    print(f"GEMINI_MODEL : {GEMINI_MODEL}")
    print(f"API Key Set  : {'YES (' + GEMINI_API_KEY[:8] + '...)' if GEMINI_API_KEY else 'NO (Please set GEMINI_API_KEY in .env)'}")
    print("=" * 60 + "\n")

    client = get_gemini_client()
    if not client:
        print("❌ Gemini client not configured. Please add GEMINI_API_KEY to your .env file.")
        print("   Get a free key at: https://aistudio.google.com/app/apikey\n")
        return

    # 1. Direct generation test
    print("1️⃣ Testing direct Gemini API generation...")
    test_resp = client.generate_content(
        prompt="Reply with a short 1-line JSON object: {\"status\": \"ok\", \"message\": \"Gemini is ready!\"}",
        json_mode=True,
    )
    print(f"   Response: {test_resp}\n")

    # 2. Test Scoring Service
    print("2️⃣ Testing Job Scoring Service with Gemini...")
    scoring_service = ScoringService()
    sample_title = "Senior Java Backend Engineer"
    sample_company = "TechCorp"
    sample_jd = """
    We are looking for a Senior Java Developer with 4+ years experience in:
    - Java 17+, Spring Boot, Microservices
    - AWS Cloud, Docker, Kubernetes
    - PostgreSQL, REST APIs
    """
    sample_resume = f"""
    Name: {CANDIDATE_NAME}
    Skills: {', '.join(CANDIDATE_SKILLS)}
    Experience: 5+ years Java Backend Developer building Spring Boot microservices on AWS.
    """

    score_result = scoring_service.score_job(
        job_title=sample_title,
        company=sample_company,
        job_description=sample_jd,
        resume_text=sample_resume,
    )
    print(f"   Scoring Result (Source: {score_result.get('_source')}):")
    print(f"   - Match Score : {score_result.get('score')}/100")
    print(f"   - Action      : {score_result.get('recommended_action')}")
    print(f"   - Reasoning   : {score_result.get('reasoning')[:120]}...\n")

    # 3. Test Email Service
    print("3️⃣ Testing Email Drafting Service with Gemini...")
    email_service = EmailService()
    email_draft = email_service.draft_email(
        job_title=sample_title,
        company=sample_company,
        job_description=sample_jd,
        resume_text=sample_resume,
        match_score=score_result.get("score", 85),
    )
    print(f"   Email Draft Result (Source: {email_draft.get('_source')}):")
    print(f"   - Subject : {email_draft.get('subject')}")
    print(f"   - Body Snippet:\n{email_draft.get('body')[:250]}...\n")

    print("=" * 60)
    print("✅ GEMINI INTEGRATION TEST COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
