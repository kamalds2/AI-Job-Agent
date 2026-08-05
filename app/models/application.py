from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from sqlalchemy.orm import relationship

from app.database.database import Base


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)

    job_id = Column(Integer, ForeignKey("jobs.id"))

    recruiter_id = Column(Integer, ForeignKey("recruiters.id"), nullable=True)

    resume_id = Column(Integer, ForeignKey("resume_versions.id"))

    email_sent = Column(Boolean, default=False)

    email_time = Column(DateTime)

    application_method = Column(String(100))

    status = Column(String(100), default="PENDING")

    notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="applications")

    recruiter = relationship("Recruiter", back_populates="applications")

    resume = relationship("ResumeVersion", back_populates="applications")