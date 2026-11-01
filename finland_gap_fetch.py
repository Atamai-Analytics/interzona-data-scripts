#!/usr/bin/env python3
"""Dump every sample in LithoSurfer package 244688701 (GTK: Finland Rock Samples) to JSON:
sample id, name, location name/lat/lon. Read-only.   Usage: python finland_gap_fetch.py <out.json>"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dump_packages as d

PACKAGE_ID = 244688701


def main():
    d.load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io")
    tok = d.request("POST", f"{host}/api/authenticate", body={
        "username": os.environ["LITHOSURFER_USER"], "password": os.environ["LITHOSURFER_PASSWORD"], "rememberMe": False})["id_token"]
    out, page, size = [], 0, 500
    t0 = time.time()
    while True:
        rows = d.request("POST", f"{host}/api/core/sample-with-locations/post?page={page}&size={size}&sort=id,asc",
                         body={"dataPackageId": {"equals": PACKAGE_ID}}, token=tok) or []
        for r in rows:
            s, loc = r.get("sampleDTO") or {}, r.get("locationDTO") or {}
            out.append({"id": s.get("id"), "name": s.get("name"), "locationName": loc.get("name"),
                        "lat": loc.get("latitude"), "lon": loc.get("longitude"), "sourceId": s.get("sourceId")})
        print(f"page {page}: +{len(rows)} (total {len(out)}) {time.time()-t0:.0f}s", flush=True)
        if len(rows) < size:
            break
        page += 1
    Path(sys.argv[1]).write_text(json.dumps(out), encoding="utf-8")
    print("saved", len(out), "samples to", sys.argv[1])


if __name__ == "__main__":
    main()
