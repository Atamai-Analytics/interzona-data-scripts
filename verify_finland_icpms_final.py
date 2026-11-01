#!/usr/bin/env python3
"""Read-only final check of the ICP-MS 511P -> 308M fix in LithoSurfer package 244688701.

For every Finland rock sample (6,544):
  * 511P [ppm] aliquot must hold exactly the ACTIVE ICP-AES values the database has under 511P after the move
    (= active 511P rows in criticialmineralsexp now), and every stored value must match a database 511P row
    (element + value + '<' operator) - i.e. no ICP-MS value is left behind, nothing ICP-AES was lost.
  * 308M [ppm] aliquot must hold exactly the 308M values the database has (170,021 in total over 6,541 samples)
    and every stored value must match a database 308M row.
Database side = analytical_results (package 115 / 111, isactive) exported to the scratchpad by psql.
"""
import collections
import csv
import os
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/39a17559-2b27-4a0d-992d-48fc9b6665db/scratchpad")
BATCH = 10
lock = threading.Lock()


def eff(e):
    return e["concentration"] if e["concentration"] is not None else e["detectionLimit"]


def load_db():
    db = {115: collections.defaultdict(list), 111: collections.defaultdict(list)}
    for r in csv.DictReader(open(SP / "res_now_511_308.csv", encoding="utf-8")):
        q = bool(r["qualifier_id"]) or float(r["value"]) < 0
        db[int(r["package_id"])][f"{r['locationid']}//AA"].append((r["analyte_code"], abs(float(r["value"])), q))
    return db


def compare(stored, expected):
    """-> (n_missing_in_LS, n_extra_in_LS) by exact multiset match."""
    pool = list(stored)
    missing = 0
    for el, v, q in expected:
        hit = next((e for e in pool if e["elementName"] == el and eff(e) is not None and abs(eff(e) - v) <= 1e-9 * max(1.0, v)
                    and bool(e["relativeOperatorId"]) == q), None)
        if hit is None:
            missing += 1
        else:
            pool.remove(hit)
    return missing, len(pool)


def main():
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    base.login()
    db = load_db()
    labels = sorted(db[115])
    print(f"database: {len(labels)} samples with 511P rows, {len(db[111])} with 308M rows; "
          f"{sum(len(v) for v in db[115].values())} 511P + {sum(len(v) for v in db[111].values())} 308M active rows")
    tally = collections.Counter(); bad = []

    def run(chunk):
        names = [f"{l} 511P [ppm]" for l in chunk] + [f"{l} 308M [ppm]" for l in chunk if l in db[111]]
        q = urllib.parse.quote(",".join(names), safe="")
        rows = None
        for attempt in range(8):                       # the endpoint sometimes answers 504 under load
            try:
                rows = base.api("GET", f"/api/geochem/ElementalConcentration?aliquotName.in={q}&size=20000&sort=id,asc") or []
                break
            except Exception as e:
                import time; time.sleep(15 * (attempt + 1))
        if rows is None:
            raise SystemExit(f"lookup kept failing for {chunk[0]}..")
        by = collections.defaultdict(list)
        for r in rows:
            by[r["aliquotName"]].append(r)
        for l in chunk:
            for pkg, suffix in ((115, "511P"), (111, "308M")):
                exp = db[pkg].get(l, [])
                if pkg == 111 and not exp:
                    st = by.get(f"{l} 308M [ppm]", [])
                    ok = not st
                    miss = extra = len(st)
                else:
                    st = by.get(f"{l} {suffix} [ppm]", [])
                    miss, extra = compare(st, exp)
                    ok = (miss == 0 and extra == 0 and len(st) == len(exp))
                with lock:
                    tally[f"{suffix}_ok" if ok else f"{suffix}_BAD"] += 1
                    if not ok:
                        bad.append((l, suffix, len(st), len(exp), miss, extra))

    chunks = [labels[i:i + BATCH] for i in range(0, len(labels), BATCH)]
    done = [0]

    def wrap(c):
        run(c)
        with lock:
            done[0] += len(c)
            if done[0] % 500 < BATCH:
                print(f"  {done[0]}/{len(labels)} {dict(tally)}", flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(wrap, chunks))
    print("FINAL", dict(tally))
    for b in bad[:20]:
        print("  BAD (label, pkg, stored, expected, missing_in_LS, extra_in_LS):", b)


if __name__ == "__main__":
    main()
