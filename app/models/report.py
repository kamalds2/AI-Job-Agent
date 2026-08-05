from datetime import date

from sqlalchemy import Column, Date, Integer, String

from app.database.database import Base


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True)

    report_date = Column(Date, default=date.today)

    jobs_found = Column(Integer, default=0)

    matched = Column(Integer, default=0)

    applied = Column(Integer, default=0)

    emails_sent = Column(Integer, default=0)

    excel_path = Column(String(500))