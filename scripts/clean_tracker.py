import json
from pathlib import Path
import re

TRACKING_FILE = Path("data/applied_jobs.json")
if TRACKING_FILE.exists():
    with open(TRACKING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    history = data.get("history", [])
    applied_keys = set()
    emailed_keys = set()

    for h in history:
        portal = (h.get("portal") or "").lower().strip()
        company = re.sub(r"[^\w]", "", (h.get("company") or "").lower())
        title = re.sub(r"[^\w]", "", (h.get("title") or "").lower())
        jid = (h.get("job_id") or "").strip()
        status = h.get("status")

        norm_key = f"{portal}_{company}_{title}"
        jid_key = f"{portal}_{jid}".lower() if jid else ""

        if status in ("APPLIED", "SUBMITTED", "DRY_RUN_COMPLETED"):
            applied_keys.add(norm_key)
            if jid_key:
                applied_keys.add(jid_key)
        elif status in ("EXTERNAL_LINK_EMAILED", "DIRECT_APPLY_EMAILED"):
            emailed_keys.add(norm_key)
            if jid_key:
                emailed_keys.add(jid_key)

    new_data = {
        "applied_keys": sorted(list(applied_keys)),
        "emailed_keys": sorted(list(emailed_keys)),
        "history": history,
    }

    with open(TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2)

    print(f"Rebuilt applied_jobs.json: {len(applied_keys)} applied keys, {len(emailed_keys)} emailed keys, {len(history)} total history records.")
