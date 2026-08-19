"""
Database setup script — creates all tables.

Usage: python scripts/setup_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.database import Base, engine
import app.models  # noqa — register all models

print("[DB] Creating database tables...")
Base.metadata.create_all(bind=engine)
print("[OK] All tables created successfully!")

# Print table names
from sqlalchemy import inspect
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f"\n[Tables] Count: {len(tables)}")
for t in sorted(tables):
    print(f"   - {t}")
