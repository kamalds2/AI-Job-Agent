from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class JobSource(Base):
    __tablename__ = "job_sources"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), unique=True, nullable=False)

    source_type = Column(String(50))

    base_url = Column(String(500))

    enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="source")