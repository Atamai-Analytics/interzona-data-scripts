#!/usr/bin/env python3
"""Remove the ICP-MS element values from the 511P [ppm] datapoints of LithoSurfer package 244688701.

Context: the 26 ICP-MS source columns of FINRock.xlsx were stored under 511P (ICP-AES aqua regia). They have been moved to
GTK package 308M in criticialmineralsexp and re-created in LithoSurfer as datapoint '<loc>//AA 308M [ppm]' (datapoints,
aliquots and element values loaded by the standard loaders from gcdp_finland_rock_308M.tsv / elem_finland_rock_308M.tsv).
This script deletes the now-duplicated ICP-MS ElementalConcentration rows from '<loc>//AA 511P [ppm]'.

Aliquots are fetched in batches (GET ElementalConcentration?aliquotName.in=a,b,c - one lookup costs ~5-50 s regardless of
how many aliquots it covers, so single lookups per sample are far too slow).

Per sample, ALL of these must hold before anything is deleted (otherwise the sample is skipped and logged):
  1. the 308M aliquot holds exactly the number of element values the database has for 308M (so the data exists in the new place)
  2. the 511P [ppm] aliquot holds exactly the number the database had before the move (nothing missing / extra)
  3. every ICP-MS row to remove matches exactly one stored value (element + concentration + '<' operator)
Rows the database kept in 511P because AES and MS were numerically identical (icpms_dup.csv) are never touched.
Deleted rows are backed up to finland_fix_backups/icpms_deleted_ec_backup.csv before the DELETE (ElementalConcentration
deletes are soft deletes in LithoSurfer as well). Idempotent: a sample whose 511P aliquot already shows only the ICP-AES count is skipped.
After each batch the 511P aliquots are re-read and must show exactly the ICP-AES count.

--test-one LOCATIONID   process one sample and print before/after counts
--dry-run               read only: tally what would be deleted
--commit                delete
"""
import argparse
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
HERE = Path(__file__).resolve().parent
SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/7e27489a-eae3-4aec-bb30-ae7938a2e666/scratchpad")
BACKUP = HERE / "finland_fix_backups" / "icpms_deleted_ec_backup.csv"
LOG = HERE / "finland_icpms_delete.log"
BATCH = 10          # samples per batched lookup (2 x 10 aliquots, ~1,000 rows; 80 aliquots per request gave 502 gateway timeouts)
lock = threading.Lock()


def log(msg):
    with lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def load_plan():
    sym = {}
    n308 = collections.Counter()
    for r in csv.DictReader(open(HERE / "elem_finland_rock_308M.tsv", encoding="utf-8"), delimiter="\t"):
        sym[r["result_id"]] = r["element_symbol"]
        n308[r["datapointName"].split(" 308M")[0]] += 1          # '<loc>//AA'
    n511 = collections.Counter()
    for r in csv.DictReader(open(SP / "res511_all.csv", encoding="utf-8")):
        if r["isactive"] == "t":                  # inactive rows (e.g. GTK's 999 placeholders) were never loaded into LithoSurfer
            n511[f"{r['locationid']}//AA"] += 1
    plan = collections.defaultdict(list)
    for r in csv.DictReader(open(HERE / "finland_fix_backups" / "icpms_move.csv", encoding="utf-8")):
        plan[f"{r['locationid']}//AA"].append({
            "el": sym[r["result_id"]], "value": float(r["value"]), "qual": bool(r["qualifier_id"])})
    return plan, n308, n511


def get_ecs_batch(aliquots):
    """-> {aliquotName: [EC dto, ...]} for all given aliquot names, one request."""
    q = urllib.parse.quote(",".join(aliquots), safe="")
    rows = base.api("GET", f"/api/geochem/ElementalConcentration?aliquotName.in={q}&size=20000&sort=id,asc") or []
    if len(rows) >= 20000:
        raise SystemExit("batch lookup hit the page size limit - lower BATCH")
    out = collections.defaultdict(list)
    for r in rows:
        out[r["aliquotName"]].append(r)
    return out


def eff(e):
    return e["concentration"] if e["concentration"] is not None else e["detectionLimit"]


def close(a, b):
    return abs(a - b) <= 1e-9 * max(1.0, abs(b))


def analyse(label, expected, n308, n511, e511, e308, tally):
    """-> list of EC dtos to delete, or None (skipped)."""
    after = n511[label] - len(expected)
    if len(e511) == after:
        tally["already_done"] += 1; return None
    partial = after < len(e511) < n511[label]            # an interrupted earlier run deleted some of this sample's rows
    if len(e511) != n511[label] and not partial:
        tally["SKIP_511_count"] += 1; log(f"SKIP {label}: 511P aliquot has {len(e511)} values, expected {n511[label]}"); return None
    if len(e308) != n308[label]:
        tally["SKIP_308_count"] += 1; log(f"SKIP {label}: 308M aliquot has {len(e308)} values, expected {n308[label]}"); return None
    used, victims, missing = set(), [], 0
    for x in expected:
        want_qual = x["qual"] or x["value"] < 0            # loader stores '<' and unqualified negatives as detectionLimit + operator '<'
        m = [i for i, e in enumerate(e511) if i not in used and e["elementName"] == x["el"]
             and eff(e) is not None and close(eff(e), abs(x["value"]) if want_qual else x["value"])
             and bool(e["relativeOperatorId"]) == want_qual]
        if len(m) == 0 and partial:
            missing += 1; continue                          # already deleted by the interrupted run
        if len(m) != 1:
            tally["SKIP_match"] += 1; log(f"SKIP {label}: {x} matched {len(m)} stored values"); return None
        used.add(m[0]); victims.append(e511[m[0]])
    if partial and missing != n511[label] - len(e511):
        tally["SKIP_partial_inconsistent"] += 1; log(f"SKIP {label}: partial state inconsistent (missing {missing}, expected {n511[label] - len(e511)})"); return None
    tally["ok_to_delete"] += 1
    if partial:
        tally["resumed_partial"] += 1
    return victims


def run_batch(items, n308, n511, commit, tally, pool):
    labels = [l for l, _ in items]
    ali = [f"{l} 511P [ppm]" for l in labels] + [f"{l} 308M [ppm]" for l in labels]
    got = get_ecs_batch(ali)
    todo = []
    for label, expected in items:
        v = analyse(label, expected, n308, n511, got.get(f"{label} 511P [ppm]", []), got.get(f"{label} 308M [ppm]", []), tally)
        if v:
            todo.append((label, expected, v))
    if not commit or not todo:
        return
    with lock, open(BACKUP, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for _, _, vs in todo:
            for v in vs:
                w.writerow([v["id"], v["aliquotName"], v["elementName"], v["concentration"], v["detectionLimit"], v["relativeOperatorId"], v["gcdataPointId"]])
    ids = [v["id"] for _, _, vs in todo for v in vs]
    list(pool.map(lambda i: base.api("DELETE", f"/api/geochem/ElementalConcentration/{i}"), ids))
    after = get_ecs_batch([f"{l} 511P [ppm]" for l, _, _ in todo])
    for label, expected, vs in todo:
        want = n511[label] - len(expected)
        if len(after.get(f"{label} 511P [ppm]", [])) != want:
            tally["POST_count_mismatch"] += 1; log(f"POST-CHECK {label}: 511P aliquot now {len(after.get(f'{label} 511P [ppm]', []))}, expected {want}")
        else:
            tally["deleted_samples"] += 1; tally["deleted_rows"] += len(vs)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--test-one", metavar="LOCATIONID")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    base.login()
    plan, n308, n511 = load_plan()
    print(f"plan: {len(plan)} samples with ICP-MS rows to remove from 511P; {sum(len(v) for v in plan.values())} rows")
    commit = a.commit or bool(a.test_one)
    if commit:
        BACKUP.parent.mkdir(exist_ok=True)
        if not BACKUP.exists():
            BACKUP.write_text("ec_id,aliquotName,element,concentration,detectionLimit,relativeOperatorId,gcdataPointId\n", encoding="utf-8")
    items = sorted(plan.items())[int(os.environ.get("FIX_START", "0")):]
    if os.environ.get("FIX_ONLY"):
        only = {x.strip() for x in os.environ["FIX_ONLY"].split(",")}
        items = [it for it in sorted(plan.items()) if it[0].split("//")[0] in only]      # FIX_START skips the samples already cleaned by earlier runs
    tally = collections.Counter()
    with ThreadPoolExecutor(max_workers=int(os.environ.get("FIX_WORKERS", base.WORKERS))) as pool:
        if a.test_one:
            lab = f"{a.test_one}//AA"
            before = get_ecs_batch([f"{lab} 511P [ppm]", f"{lab} 308M [ppm]"])
            print("before: 511P", len(before[f"{lab} 511P [ppm]"]), "| 308M", len(before[f"{lab} 308M [ppm]"]))
            run_batch([(lab, plan[lab])], n308, n511, True, tally, pool)
            after = get_ecs_batch([f"{lab} 511P [ppm]", f"{lab} 308M [ppm]"])
            print("after:  511P", len(after[f"{lab} 511P [ppm]"]), "| 308M", len(after[f"{lab} 308M [ppm]"]))
            print(dict(tally)); return
        for i in range(0, len(items), BATCH):
            run_batch(items[i:i + BATCH], n308, n511, a.commit, tally, pool)
            print(f"  {min(i + BATCH, len(items))}/{len(items)} {dict(tally)}", flush=True)
    print("FINAL", dict(tally))


if __name__ == "__main__":
    main()
