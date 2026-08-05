from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class JobData:
    title: str
    company: str
    location: str

    description: str

    job_url: str

    source: str

    remote: bool

    posted_date: Optional[date] = None

    salary: Optional[str] = None

    experience: Optional[str] = None

    employment_type: Optional[str] = None

    skills: list[str] | None = None