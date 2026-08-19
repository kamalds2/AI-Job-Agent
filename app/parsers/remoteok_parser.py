from datetime import datetime

from app.schemas.job_data import JobData


class RemoteOKParser:

    def parse_jobs(self, raw_jobs):

        jobs = []

        # RemoteOK's first item is metadata
        for job in raw_jobs[1:]:

            jobs.append(
                JobData(
                    title=job.get("position", ""),
                    company=job.get("company", ""),
                    location=job.get("location", "Remote"),
                    remote=True,
                    experience=None,
                    employment_type=None,
                    salary=job.get("salary_min"),
                    description=job.get("description", ""),
                    job_url=job.get("url", ""),
                    source="RemoteOK",
                    posted_date=datetime.utcnow().date(),
                    skills=job.get("tags", [])
                )
            )

        return jobs