from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database.database import Base


class SearchLog(Base):
    __tablename__ = "search_logs"

    id = Column(Integer, primary_key=True, index=True)

    source = Column(String(100))

    jobs_found = Column(Integer, default=0)

    jobs_saved = Column(Integer, default=0)

    status = Column(String(50))

    created_at = Column(DateTime, default=datetime.utcnow)