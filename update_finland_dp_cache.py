#!/usr/bin/env python3
"""Refresh datapoint_ids_244688701.json after the Finland gap fix:
  * drop the 13 labels for the removed regional-till datapoints
  * add the 1,024 datapoints created from gcdp_finland_rock_extra128.tsv (found by session id 20261004-gcdp)
Read-only against LithoSurfer. The pre-change cache is backed up in finland_gap_backups/."""
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dump_packages as d

HERE = Path(__file__).resolve().parent
PKG = 244688701
NAME_SEP = "\\" * 2
REMOVED_LOCS = [8498221, 8597179, 8234067, 8322531, 8279833, 8169049, 8567644, 8255688, 8635340, 8223324, 8269662, 8294254, 8388645]


def main():
    d.load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io")
    tok = d.request("POST", f"{host}/api/authenticate", body={
        "username": os.environ["LITHOSURFER_USER"], "password": os.environ["LITHOSURFER_PASSWORD"], "rememberMe": False})["id_token"]
    pk = d.request("GET", f"{host}/api/management/data-packages/{PKG}", token=tok)
    print("package counts: samples", pk["countSamples"], "| GC datapoints", pk["countGCDataPoints"], "(expect 6169 / 49352)")

    wanted = {r["datapointName"] for r in csv.DictReader(open(HERE / "gcdp_finland_rock_extra128.tsv", encoding="utf-8", newline=""), delimiter="\t")}
    found, page = {}, 0
    while True:
        rows = d.request("POST", f"{host}/api/geochem/GCDataPoint/post?page={page}&size=200&sort=id,asc", token=tok,
                         body={"dataPointLithoCriteria": {"dataPackageId": {"equals": PKG}, "name": {"contains": "20261004-gcdp"}}}) or []
        for r in rows:
            label = (r["dataPointDTO"]["name"] or "").split(NAME_SEP, 1)[0]
            if label in wanted:
                found[label] = r["id"]
        print(f"  page {page}: +{len(rows)} (matched {len(found)}/{len(wanted)})", flush=True)
        if len(rows) < 200:
            break
        page += 1
    missing = wanted - set(found)
    if missing:
        raise SystemExit(f"{len(missing)} new datapoints not found in LithoSurfer, e.g. {sorted(missing)[:3]} - cache NOT changed")

    path = HERE / f"datapoint_ids_{PKG}.json"
    cache = json.loads(path.read_text(encoding="utf-8"))
    before = len([k for k in cache if k != "__complete__"])
    for loc in REMOVED_LOCS:
        cache.pop(f"{loc}//AA 511P [ppm]", None)
    cache.update(found)
    cache["__complete__"] = True
    path.write_text(json.dumps(cache), encoding="utf-8")
    after = len([k for k in cache if k != "__complete__"])
    print(f"cache entries: {before} -> {after} (expect 48341 - 13 + 1024 = 49352)")


if __name__ == "__main__":
    main()
