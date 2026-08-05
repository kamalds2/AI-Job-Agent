from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(255), nullable=False, unique=True)
    website = Column(String(500))
    careers_url = Column(String(500))
    industry = Column(String(100))
    headquarters = Column(String(255))

    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="company")
    recruiters = relationship("Recruiter", back_populates="company")