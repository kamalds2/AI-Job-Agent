from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id = Column(Integer, primary_key=True)

    job_id = Column(Integer, ForeignKey("jobs.id"))

    filename = Column(String(255))

    pdf_path = Column(String(500))

    docx_path = Column(String(500))

    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="resumes")

    applications = relationship("Application", back_populates="resume")

    resume_skills = relationship(
        "ResumeSkill",
        back_populates="resume",
        cascade="all, delete-orphan",
    )