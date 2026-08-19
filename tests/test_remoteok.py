from app.connectors.remoteok_connector import RemoteOKConnector

connector = RemoteOKConnector()

jobs = connector.fetch_jobs()

print(type(jobs))
print(len(jobs))
print(jobs[0])