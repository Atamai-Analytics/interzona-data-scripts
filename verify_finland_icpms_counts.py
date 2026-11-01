#!/usr/bin/env python3
"""Fast read-only count check of the ICP-MS 511P -> 308M fix: for every Finland rock sample the 511P [ppm] datapoint must hold
exactly the active 511P rows the database now has (ICP-AES only) and the 308M [ppm] datapoint exactly the active 308M rows.
Uses GCDataPoint.countElementalConcentrations (one GET per datapoint)."""
import collections
import csv
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/39a17559-2b27-4a0d-992d-48fc9b6665db/scratchpad")
lock = threading.Lock()


def main():
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    base.login()
    cache = json.loads((HERE / "datapoint_ids_244688701.json").read_text(encoding="utf-8")); cache.pop("__complete__", None)
    exp = {115: collections.Counter(), 111: collections.Counter()}
    for r in csv.DictReader(open(SP / "res_now_511_308.csv", encoding="utf-8")):
        exp[int(r["package_id"])][f"{r['locationid']}//AA"] += 1
    jobs = [(f"{l} 511P [ppm]", n) for l, n in exp[115].items()] + [(f"{l} 308M [ppm]", n) for l, n in exp[111].items()]
    print(f"checking {len(jobs)} datapoints ({len(exp[115])} x 511P, {len(exp[111])} x 308M); expected EC totals {sum(exp[115].values())} / {sum(exp[111].values())}")
    tally, bad, sums = collections.Counter(), [], collections.Counter()

    def one(job):
        name, want = job
        dto = base.api("GET", f"/api/geochem/GCDataPoint/{cache[name]}")
        got = dto.get("countElementalConcentrations") or 0
        with lock:
            sums[name.split(" ")[1]] += got
            if got == want: tally["ok"] += 1
            else:
                tally["BAD"] += 1; bad.append((name, got, want))

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(one, jobs))
    print("FINAL", dict(tally), "| stored EC totals:", dict(sums))
    for b in bad[:20]:
        print("  BAD (datapoint, stored, expected):", b)


if __name__ == "__main__":
    main()
