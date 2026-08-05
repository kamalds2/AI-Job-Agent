from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class Recruiter(Base):
    __tablename__ = "recruiters"

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"))

    name = Column(String(255))

    email = Column(String(255))

    phone = Column(String(50))

    linkedin = Column(String(500))

    company = relationship("Company", back_populates="recruiters")

    applications = relationship("Application", back_populates="recruiter")