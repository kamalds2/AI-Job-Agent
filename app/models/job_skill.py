from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database.database import Base


class JobSkill(Base):
    __tablename__ = "job_skills"

    id = Column(Integer, primary_key=True)

    job_id = Column(Integer, ForeignKey("jobs.id"))

    skill_id = Column(Integer, ForeignKey("skills.id"))

    job = relationship("Job", back_populates="job_skills")

    skill = relationship("Skill", back_populates="job_skills")