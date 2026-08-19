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
    hirist_connector,
    tier5_connector,
)
