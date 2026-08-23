import sys; sys.path.insert(0,'.')

print("=== 1. Connector Import Test ===")
from app.connectors import (remoteok_connector, wellfound_connector, yc_connector,
    greenhouse_connector, lever_connector, ashby_connector, weworkremotely_connector,
    remotive_connector, himalayas_connector, naukri_connector, hirist_connector,
    tier5_connector, adzuna_connector)
from app.connectors.registry import CONNECTORS
print(f"Registered connectors: {len(CONNECTORS)}")
for name in CONNECTORS:
    print(f"  [OK] {name}")

print()
print("=== 2. Scoring Service ===")
from app.services.scoring_service import ScoringService
s = ScoringService()
print(f"Claude available: {s._claude is not None}")
print(f"OpenAI available: {s._openai is not None}")

print()
print("=== 3. Gmail Auth Test ===")
from app.services.email_service import EmailService
es = EmailService()
token = es._get_access_token()
if token:
    print("Gmail token: OK (" + token[:20] + "...)")
else:
    print("Gmail token: FAILED - check refresh token in .env")

print()
print("=== 4. DB Stats ===")
from app.database.database import SessionLocal
from app.models.job import Job
db = SessionLocal()
total = db.query(Job).count()
new = db.query(Job).filter(Job.status == "NEW").count()
applied = db.query(Job).filter(Job.status == "APPLIED").count()
scored = db.query(Job).filter(Job.match_score != None).count()
qualified = db.query(Job).filter(Job.match_score >= 65).count()
db.close()
print(f"Total jobs in DB: {total}")
print(f"NEW (unscored): {new}")
print(f"Scored: {scored}")
print(f"Qualified (>=65): {qualified}")
print(f"Applied: {applied}")
print()
print("=== ALL CHECKS DONE ===")
