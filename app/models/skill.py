from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True)

    name = Column(String(100), unique=True, nullable=False)

    category = Column(String(100))

    created_at = Column(DateTime, default=datetime.utcnow)

    job_skills = relationship("JobSkill", back_populates="skill")

    resume_skills = relationship("ResumeSkill", back_populates="skill")