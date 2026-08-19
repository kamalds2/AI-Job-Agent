from abc import ABC, abstractmethod
import sys


class BaseConnector(ABC):
    """
    Abstract base class for all job source connectors.

    All connectors must implement:
      - fetch_jobs(): Download raw data from the job source
      - parse_jobs(raw): Convert raw data into list[JobData]

    The search_jobs() method runs the full pipeline.

    SSL: On Windows, verify=False is used to bypass local CA chain issues.
         On Linux/Mac, standard SSL verification applies.
    """

    connector_name = "base"

    # On Windows, SSL cert verification often fails due to missing CA chains.
    # verify=False is safe for public job APIs we are only reading from.
    CLIENT_KWARGS = {
        "verify": sys.platform != "win32",  # False on Windows, True elsewhere
        "timeout": 30,
        "follow_redirects": True,
    }

    @abstractmethod
    async def fetch_jobs(self):
        """Download raw data from the job source."""
        pass

    @abstractmethod
    async def parse_jobs(self, raw_jobs):
        """Convert raw data into list[JobData]."""
        pass

    async def search_jobs(self):
        """
        Standard search pipeline — fetch → parse.
        Called by SearchManager for every connector.
        """
        raw_jobs = await self.fetch_jobs()
        jobs = await self.parse_jobs(raw_jobs)
        return jobs