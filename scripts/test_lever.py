import sys, httpx
sys.path.insert(0, "c:\\kamal\\AI-Job-Agent")

# Larger batch of potential Lever companies to find working ones
candidates = [
    "pipedrive", "wealthsimple", "harvest", "clio", "lever",
    "bazaarvoice", "pendo", "mixpanel", "heap", "amplitude",
    "figma", "airtable", "notion", "loom", "miro",
    "brex", "mercury", "ramp", "gusto", "rippling",
    "lattice", "culture-amp", "15five", "betterworks",
    "cockroachlabs", "yugabyte", "timescale", "planetscale",
    "sourcegraph", "codeium", "cursor", "replit",
    "snyk", "lacework", "wiz", "orca-security",
    "confluent", "starburst", "dremio", "databricks",
    "prefect-technologies", "dagster-labs", "astronomer",
    "observeinc", "chronosphere", "honeycomb-io",
    "supabase", "pocketbase", "appwrite", "hasura",
    "temporal", "inngest", "trigger",
]

found = []
for c in candidates:
    try:
        r = httpx.get(f"https://api.lever.co/v0/postings/{c}?mode=json", verify=False, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if len(data) > 0:
                found.append({"token": c, "jobs": len(data)})
                print(f"FOUND {c}: {len(data)} jobs")
            else:
                pass  # 200 but empty
    except Exception as e:
        pass

print(f"\nTotal working: {len(found)}")
for f in found:
    print(f"  {f['token']}: {f['jobs']} jobs")
