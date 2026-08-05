from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from sqlalchemy.orm import relationship

from app.database.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(Integer, ForeignKey("companies.id"))

    title = Column(String(255), nullable=False)
    location = Column(String(255))

    remote = Column(Boolean, default=False)

    experience = Column(String(100))

    employment_type = Column(String(100))

    salary = Column(String(100))

    description = Column(Text)

    source_id = Column(Integer, ForeignKey("job_sources.id"))

    job_url = Column(String(1000), unique=True)

    posted_date = Column(Date)

    match_score = Column(Float)

    status = Column(String(50), default="NEW")

    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="jobs")

    resumes = relationship("ResumeVersion", back_populates="job")

    applications = relationship("Application", back_populates="job")

    job_skills = relationship(
        "JobSkill",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    source = relationship("JobSource")