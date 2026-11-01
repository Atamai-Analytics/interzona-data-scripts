#!/usr/bin/env python3
"""Read-only verification of the 128 grab/float rock samples loaded into package 244688701.
For each of the 1,024 new datapoints: stored countElementalConcentrations / countOxideConcentrations must equal
the number of rows for that datapointName in elem_/oxide_finland_rock_extra128.tsv; sampleWeightGm and
digestionNotes must be present and equal the documented per-method values; no stray ICP-MS rows.
Also re-checks the pre-existing sample 8155272//AA against the counts recorded earlier this session."""
import collections
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import update_finland_digestion_notes as notes
import update_finland_sample_weight as base

HERE = Path(__file__).resolve().parent


def main():
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    base.login()
    cache = json.loads((HERE / "datapoint_ids_244688701.json").read_text(encoding="utf-8")); cache.pop("__complete__", None)
    rows = list(csv.DictReader(open(HERE / "gcdp_finland_rock_extra128.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    exp_e = collections.Counter(r["datapointName"] for r in csv.DictReader(open(HERE / "elem_finland_rock_extra128.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    exp_o = collections.Counter(r["datapointName"] for r in csv.DictReader(open(HERE / "oxide_finland_rock_extra128.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    print(f"expected: {len(rows)} datapoints, {sum(exp_e.values())} element rows, {sum(exp_o.values())} oxide rows")
    tally, lock = collections.Counter(), __import__("threading").Lock()
    sums = collections.Counter(); bad = []

    def one(r):
        name = r["datapointName"]
        gid = cache[name]
        dto = base.api("GET", f"/api/geochem/GCDataPoint/{gid}")
        g = dto["gcdataPointDTO"]; code = g["sourceMethodCode"]
        e, o = dto.get("countElementalConcentrations") or 0, dto.get("countOxideConcentrations") or 0
        state = []
        if e != exp_e.get(name, 0): state.append(f"EC {e}!={exp_e.get(name, 0)}")
        if o != exp_o.get(name, 0): state.append(f"OC {o}!={exp_o.get(name, 0)}")
        if not base.same(g.get("sampleWeightGm"), base.WEIGHTS_G.get(code)): state.append("WEIGHT")
        if (g.get("digestionNotes") or "").strip() != notes.NOTES.get(code): state.append("NOTE")
        if (dto.get("iCPMSLithoDTO") or {}).get("id") is not None: state.append("ICPMS-ROWS")
        if dto["dataPointDTO"]["dataPackageId"] != 244688701: state.append("PACKAGE")
        with lock:
            tally["ok" if not state else "PROBLEM"] += 1; sums["ec"] += e; sums["oc"] += o
            if state: bad.append((name, state))

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(one, rows))
    print(f"new datapoints: {dict(tally)} | stored EC sum {sums['ec']} (expect 9831) | OC sum {sums['oc']} (expect 1280)")
    for b in bad[:10]:
        print("  PROBLEM:", b)
    # earlier-recorded counts for sample 8155272//AA (pre-existing outcrop sample)
    earlier = {"707I [%]": (1, 0), "175X [ppm]": (16, 0), "521U [ppb]": (3, 0), "175X [%]": (0, 10), "511U [ppm]": (3, 0), "511P [ppm]": (52, 0), "816L [%]": (1, 0), "811L [%]": (1, 0)}
    same = 0
    for suffix, (ee, oo) in earlier.items():
        dto = base.api("GET", f"/api/geochem/GCDataPoint/{cache[f'8155272//AA {suffix}']}")
        same += (dto.get("countElementalConcentrations"), dto.get("countOxideConcentrations")) == (ee, oo)
    print(f"pre-existing sample 8155272//AA: {same}/8 datapoints unchanged vs counts recorded earlier")


if __name__ == "__main__":
    main()
