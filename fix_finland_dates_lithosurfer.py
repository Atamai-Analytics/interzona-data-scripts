#!/usr/bin/env python3
"""Shift the 6,169 originally loaded GTK Finland rock samples in LithoSurfer package 244688701 forward by one day.

The original ingestion stored every sample date exactly 1 day early (verified against FINRock.xlsx SAMDATE$);
criticialmineralsexp.samples.sampledate was corrected on 2026-10-04 (backup finland_fix_backups/samples_sampledate_before_datefix.csv).
This script brings LithoSurfer in line with the corrected database:
  * Sample.collectDateMin  : old date -> source date (+1 day)
  * Sample.collectDateMax  : old max  -> +1 day (convention min + 364 d is kept)
  * SampleProperty 'sampledate_original' : old date -> source date

Safe by construction: each value is only changed when it currently equals the EXPECTED OLD value (from the pre-fix database
export); values already at the new value are skipped (idempotent/resumable); anything else is reported and left untouched.
PUT /api/core/sample-with-locations (and SampleProperty) is a full replace, so the complete current DTO is sent back
with only the date field(s) changed.

--test-one LABEL   change one sample (+ property) and print a diff of the full records
--dry-run          read only: tally what would change
--commit           apply
"""
import argparse
import collections
import copy
import csv
import datetime as dt
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
SCRATCH = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/7e27489a-eae3-4aec-bb30-ae7938a2e666/scratchpad")
PKG = 244688701
CHUNK = 200
LOG = HERE / "finland_dates_lithosurfer.log"
lock = threading.Lock()


def d1(s):
    return dt.date.fromisoformat(s)


def load_plan():
    labels = json.loads((HERE / "sample_labels_244688701.json").read_text(encoding="utf-8"))
    labels.pop("__complete__", None)
    newd = {r["sampleid"]: r["new_date"] for r in csv.DictReader(open(SCRATCH / "date_fix.csv", encoding="utf-8"))}
    plan = []
    for r in csv.DictReader(open(SCRATCH / "ex_samples.csv", encoding="utf-8")):
        label = f"{r['locationid']}//AA"
        if label not in labels:
            raise SystemExit(f"label {label} not in LithoSurfer cache")
        old, new = r["sampledate"], newd[r["sampleid"]]
        assert d1(new) - d1(old) == dt.timedelta(days=1), (label, old, new)
        plan.append({"label": label, "id": labels[label], "old": old, "new": new})
    return plan


def fetch_samples(ids):
    out = {}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        rows = base.api("POST", f"/api/core/sample-with-locations/post?page=0&size={CHUNK}",
                        {"dataPackageId": {"equals": PKG}, "id": {"in": chunk}}) or []
        for r in rows:
            out[r["sampleDTO"]["id"]] = r
    return out


def fetch_props(ids):
    out = {}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        rows = base.api("POST", "/api/core/SampleProperty/post?page=0&size=2000",
                        {"sampleId": {"in": chunk}, "propName": {"equals": "sampledate_original"}}) or []
        for p in rows:
            out.setdefault(p["sampleId"], []).append(p)
    return out


def process(item, sdto, props, commit, tally):
    """One sample: returns nothing; updates tally."""
    sd = sdto["sampleDTO"]
    # ---- sample dates
    cmin, cmax = sd.get("collectDateMin"), sd.get("collectDateMax")
    want_min = item["new"]
    want_max = (d1(item["new"]) + dt.timedelta(days=364)).isoformat()
    old_max = (d1(item["old"]) + dt.timedelta(days=364)).isoformat()
    if cmin == want_min and cmax == want_max:
        tally["sample_already"] += 1
    elif cmin == item["old"] and cmax == old_max:
        tally["sample_to_change"] += 1
        if commit:
            new = copy.deepcopy(sdto)
            new["sampleDTO"]["collectDateMin"], new["sampleDTO"]["collectDateMax"] = want_min, want_max
            base.api("PUT", "/api/core/sample-with-locations", new)
            tally["sample_changed"] += 1
    else:
        tally["sample_UNEXPECTED"] += 1
        with lock:
            open(LOG, "a", encoding="utf-8").write(f"UNEXPECTED sample {item['label']} min={cmin} max={cmax} expected old {item['old']}/{old_max} or new {want_min}/{want_max}\n")
    # ---- property
    plist = props.get(item["id"], [])
    if len(plist) != 1:
        tally["prop_UNEXPECTED_count"] += 1
        with lock:
            open(LOG, "a", encoding="utf-8").write(f"UNEXPECTED property count {len(plist)} for {item['label']}\n")
        return
    p = plist[0]
    if p["propValue"] == item["new"]:
        tally["prop_already"] += 1
    elif p["propValue"] == item["old"]:
        tally["prop_to_change"] += 1
        if commit:
            q = dict(p); q["propValue"] = item["new"]
            base.api("PUT", "/api/core/SampleProperty", q)
            tally["prop_changed"] += 1
    else:
        tally["prop_UNEXPECTED"] += 1
        with lock:
            open(LOG, "a", encoding="utf-8").write(f"UNEXPECTED property {item['label']} value={p['propValue']} expected {item['old']}/{item['new']}\n")


def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, p + "." + k)
    else:
        yield p, o


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--test-one", metavar="LABEL")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    base.login()
    plan = load_plan()
    print(f"plan: {len(plan)} samples")
    if a.test_one:
        plan = [x for x in plan if x["label"] == a.test_one]
        assert len(plan) == 1
    ids = [x["id"] for x in plan]
    print("fetching samples + properties ...")
    samples = fetch_samples(ids)
    props = fetch_props(ids)
    print(f"fetched {len(samples)} samples, {sum(len(v) for v in props.values())} properties")
    missing = [x["label"] for x in plan if x["id"] not in samples]
    if missing:
        raise SystemExit(f"{len(missing)} samples not returned, e.g. {missing[:3]}")
    tally = collections.Counter()
    if a.test_one:
        before_s = copy.deepcopy(samples[plan[0]["id"]]); before_p = copy.deepcopy(props[plan[0]["id"]])
        process(plan[0], samples[plan[0]["id"]], props, True, tally)
        after_s = fetch_samples([plan[0]["id"]])[plan[0]["id"]]; after_p = fetch_props([plan[0]["id"]])[plan[0]["id"]]
        fb, fa = dict(flat(before_s)), dict(flat(after_s))
        for k in sorted(set(fb) | set(fa)):
            if fb.get(k) != fa.get(k): print("SAMPLE", k, fb.get(k), "->", fa.get(k))
        fb, fa = dict(flat({"p": before_p})), dict(flat({"p": after_p}))
        for k in sorted(set(fb) | set(fa)):
            if fb.get(k) != fa.get(k): print("PROP", k, fb.get(k), "->", fa.get(k))
        print(dict(tally))
        return
    with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
        list(ex.map(lambda it: process(it, samples[it["id"]], props, a.commit, tally), plan))
    print(dict(tally))


if __name__ == "__main__":
    main()
