from abc import ABC, abstractmethod

from app.schemas.job_data import JobData


class BaseConnector(ABC):

    connector_name = ""

    connector_type = ""

    priority = 0

    @abstractmethod
    async def search_jobs(self) -> list[JobData]:
        """
        Every connector must return a list of JobData.
        """
        pass