# Auto-import all connectors so they register themselves via @register_connector
from app.connectors import (  # noqa: F401
    remoteok_connector,
    wellfound_connector,
    yc_connector,
    greenhouse_connector,
    lever_connector,
    ashby_connector,
    weworkremotely_connector,
    remotive_connector,
    himalayas_connector,
    naukri_connector,
    hirist_connector,      # Arbeitnow (replaced Hirist — no auth needed)
    tier5_connector,
    adzuna_connector,      # Free India API — needs ADZUNA_APP_ID + ADZUNA_APP_KEY in .env
    linkedin_posts_connector,  # Daily LinkedIn hiring posts scraper with recruiter emails
)
