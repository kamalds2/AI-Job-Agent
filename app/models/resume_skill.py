from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database.database import Base


class ResumeSkill(Base):
    __tablename__ = "resume_skills"

    resume_id = Column(
        Integer,
        ForeignKey("resume_versions.id"),  # Fixed: was "resumes.id"
        primary_key=True,
    )

    skill_id = Column(
        Integer,
        ForeignKey("skills.id"),
        primary_key=True,
    )

    resume = relationship("ResumeVersion", back_populates="resume_skills")
    skill = relationship("Skill", back_populates="resume_skills")