"""Quick test: score 3 real jobs with Claude to verify full pipeline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database.database import SessionLocal
from app.models.job import Job
from app.services.scoring_service import ScoringService
from app.services.resume_service import ResumeService

db = SessionLocal()

# Find relevant tech jobs
jobs = db.query(Job).filter(
    Job.status == "NEW"
).filter(
    Job.title.ilike("%backend%") |
    Job.title.ilike("%java%") |
    Job.title.ilike("%python%") |
    Job.title.ilike("%software engineer%") |
    Job.title.ilike("%senior engineer%") |
    Job.title.ilike("%full stack%") |
    Job.title.ilike("%fullstack%")
).limit(3).all()

print(f"Found {len(jobs)} relevant jobs for test")
for j in jobs:
    company = j.company.name if j.company else "Unknown"
    print(f"  [{j.id}] {j.title} @ {company}")

if not jobs:
    print("No matching jobs — using any new jobs")
    jobs = db.query(Job).filter(Job.status == "NEW").limit(3).all()

# Score them
resume_svc = ResumeService()
resume_text = resume_svc.extract_resume_text()
print(f"\nResume extracted: {len(resume_text)} chars")

scoring_svc = ScoringService()
print("\nScoring with Claude (claude-sonnet-4-5)...")
print("=" * 60)

for j in jobs:
    company = j.company.name if j.company else "Unknown"
    result = scoring_svc.score_job(
        job_title=j.title,
        company=company,
        job_description=(j.description or "")[:2000],
        resume_text=resume_text,
    )
    print(f"\nJob:    {j.title} @ {company}")
    print(f"Score:  {result['score']}/100")
    print(f"Action: {result['recommended_action']}")
    print(f"Match:  {result.get('matching_skills', [])}")
    print(f"Reason: {result['reasoning'][:150]}")
    print("-" * 60)

db.close()
print("\nTest complete!")
