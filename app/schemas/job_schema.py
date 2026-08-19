from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class JobSchema:
    title: str
    company: str
    location: str

    remote: bool

    experience: Optional[str]

    employment_type: Optional[str]

    salary: Optional[str]

    description: Optional[str]

    job_url: str

    source: str

    posted_date: date

    skills: list[str]