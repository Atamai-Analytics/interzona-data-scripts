#!/usr/bin/env python3
"""Copy documented charge weights onto GCDataPoint.sampleWeightGm / digestionNotes for the
Victoria and Greenland packages, locating each datapoint BY ID (no paging).

Why: scanning 300k datapoints by offset paging is hours slow (deep pages take ~30 s each).
The 54k datapoints that need updating are known exactly from the datapoint_ids_<pkg>.json
caches (label -> gcdataPointId, built by the original loads) joined to the gcdp_*.tsv files
(label rule from load_gc_datapoints.py: name + ' [units]' when multi-unit; method code from
the TSV). Each id is fetched, its sourceMethodCode double-checked against the TSV, and only
then updated. Update rules, DTO handling and weights are those of update_charge_weights.py
(imported). Resumable/idempotent. Refuses to start if another copy runs.

--dry-run (default)  reads only, never writes        --limit N   first N targets
--commit             perform updates; saves pre-update element/oxide counts to charge_weights_pre_counts.json
--verify             re-reads every target (weight, note, ICP-MS rows, counts vs pre-update) plus a random
                     spot check that untouched datapoints still have no weight
--packages a,b,c     restrict to these package ids
"""
import argparse
import collections
import csv
import json
import os
import platform
import random
import subprocess
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import update_charge_weights as m
import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
SCRIPT_NAME = Path(__file__).name
LOG_PATH = HERE / "charge_weights_datapoints.log"
PRE_PATH = HERE / "charge_weights_pre_counts.json"
TSV_BY_PKG = {246454433: "gcdp_victoria_soil.tsv", 205700763: "gcdp_rock.tsv", 205700765: "gcdp_stream.tsv",
              205700764: "gcdp_soil.tsv", 205700762: "gcdp_hmc.tsv"}


def check_no_other_instance():
    if platform.system() != "Windows":
        return
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object -ExpandProperty CommandLine"],
                       capture_output=True, text=True, timeout=30)
    lines = [l for l in r.stdout.splitlines() if SCRIPT_NAME in l or "update_charge_weights.py" in l]
    if len(lines) > 1:
        print(f"REFUSING TO START: {len(lines)} python processes already reference this updater.", file=sys.stderr)
        raise SystemExit(1)


def build_targets(pkgs):
    targets, missing = [], collections.Counter()
    for pid in pkgs:
        cache = json.loads((HERE / f"datapoint_ids_{pid}.json").read_text(encoding="utf-8"))
        cache.pop("__complete__", None)
        with open(HERE / TSV_BY_PKG[pid], encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                code = r["sourcemethodcode"]
                if code not in m.MAPPING:
                    continue
                units = r["units"] or ""
                label = f"{r['datapointName']} [{units}]" if "/" in units else r["datapointName"]
                gid = cache.get(label)
                if gid is None:
                    missing[pid] += 1
                else:
                    targets.append((pid, gid, code))
    return targets, missing


def log(line):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def process_target(pid, gid, code, commit, stats, lock, pre):
    try:
        dto = base.api("GET", f"/api/geochem/GCDataPoint/{gid}")
    except urllib.error.HTTPError as e:
        with lock:
            stats["get_failed"] += 1; log(f"GET FAILED id={gid} http={e.code}")
        return
    g = dto.get("gcdataPointDTO") or {}
    with lock:
        stats["read"] += 1
        pre[str(gid)] = [dto.get("countElementalConcentrations") or 0, dto.get("countOxideConcentrations") or 0]
    if g.get("sourceMethodCode") != code:
        with lock:
            stats["method_mismatch"] += 1; log(f"MISMATCH id={gid} expected {code} found {g.get('sourceMethodCode')} - not touched")
        return
    weight, note = m.MAPPING[code]
    cur = g.get("sampleWeightGm")
    notes_now = (g.get("digestionNotes") or "").strip()
    if base.same(cur, weight) and notes_now:
        with lock:
            stats["already_ok"] += 1
        return
    if cur is not None and not base.same(cur, weight):
        with lock:
            stats["has_other_weight"] += 1; log(f"SKIPPED id={gid} existing weight {cur} kept (target {weight} for {code})")
        return
    if notes_now and notes_now != note:
        with lock:
            stats["notes_kept"] += 1
    if not commit:
        with lock:
            stats["would_update"] += 1
        return
    try:
        base.api("PUT", "/api/geochem/GCDataPoint", m.make_put_body(dto, weight, note))
        with lock:
            stats["updated"] += 1
    except urllib.error.HTTPError as e:
        with lock:
            stats["failed"] += 1; log(f"FAILED id={gid} http={e.code} {e.read().decode('utf-8', 'replace')[:200]}")


def run(commit, pkgs, limit):
    targets, missing = build_targets(pkgs)
    if missing:
        print("WARNING: TSV rows with no id in cache:", dict(missing))
    if limit:
        targets = targets[:limit]
    by_pkg = collections.Counter(p for p, _, _ in targets)
    print("targets:", {m.PACKAGES[p][0]: n for p, n in by_pkg.items()}, "total", len(targets), flush=True)
    stats, lock, pre = collections.Counter(), threading.Lock(), {}
    t0 = time.time(); done = 0
    with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
        for f in as_completed([ex.submit(process_target, p, g, c, commit, stats, lock, pre) for p, g, c in targets]):
            f.result(); done += 1
            if done % 1000 == 0 or done == len(targets):
                print(f"  {done}/{len(targets)} | updated {stats['updated']} | would_update {stats['would_update']} | already_ok {stats['already_ok']} "
                      f"| other_weight {stats['has_other_weight']} | notes_kept {stats['notes_kept']} | mismatch {stats['method_mismatch']} "
                      f"| failed {stats['failed'] + stats['get_failed']} | {(time.time() - t0) / 60:.1f} min", flush=True)
                if commit:
                    with lock:
                        existing = json.loads(PRE_PATH.read_text(encoding="utf-8")) if PRE_PATH.exists() else {}
                        existing.update(pre); PRE_PATH.write_text(json.dumps(existing), encoding="utf-8")
    print("\n" + ("COMMIT" if commit else "DRY RUN (nothing written)") + " - " + ", ".join(f"{k}={stats[k]}" for k in sorted(stats)), flush=True)


def verify(pkgs, sample_unmapped):
    targets, _ = build_targets(pkgs)
    pre = json.loads(PRE_PATH.read_text(encoding="utf-8")) if PRE_PATH.exists() else {}
    tally, lock = collections.Counter(), threading.Lock()

    def one(pid, gid, code):
        dto = base.api("GET", f"/api/geochem/GCDataPoint/{gid}")
        g = dto["gcdataPointDTO"]; weight, note = m.MAPPING[code]
        notes = (g.get("digestionNotes") or "").strip()
        st = ("weight-ok" if base.same(g.get("sampleWeightGm"), weight) else "WEIGHT-WRONG") + \
             ("/note-ours" if notes == note else "/note-other" if notes else "/NOTE-EMPTY")
        if g.get("sourceMethodCode") != code:
            st += "/METHOD-MISMATCH"
        if (dto.get("iCPMSLithoDTO") or {}).get("id") is not None:
            st += "/icpms-rows"
        c = [dto.get("countElementalConcentrations") or 0, dto.get("countOxideConcentrations") or 0]
        st += ("/counts-same" if pre[str(gid)] == c else "/COUNTS-CHANGED") if str(gid) in pre else "/no-baseline"
        with lock:
            tally[(m.PACKAGES[pid][0], st)] += 1

    with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
        for i, f in enumerate(as_completed([ex.submit(one, p, g, c) for p, g, c in targets]), 1):
            f.result()
            if i % 5000 == 0:
                print(f"  verified {i}/{len(targets)}", flush=True)
    print(f"\nVERIFY targets: {len(targets)}")
    for k, c in sorted(tally.items()):
        print(f"   {k[0]} | {k[1]}: {c}")
    tset = {g for _, g, _ in targets}; pool = []
    for pid in pkgs:
        cache = json.loads((HERE / f"datapoint_ids_{pid}.json").read_text(encoding="utf-8")); cache.pop("__complete__", None)
        pool += [(pid, v) for v in cache.values() if v not in tset]
    random.seed(1); pick = random.sample(pool, min(sample_unmapped, len(pool)))
    bad = collections.Counter()

    def chk(pid, gid):
        g = base.api("GET", f"/api/geochem/GCDataPoint/{gid}")["gcdataPointDTO"]
        with lock:
            bad["HAS WEIGHT (unexpected)" if g.get("sampleWeightGm") is not None else "empty (expected)"] += 1

    with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
        list(ex.map(lambda a: chk(*a), pick))
    print(f"untouched-datapoint spot check ({len(pick)} random): {dict(bad)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--packages", default=",".join(str(p) for p in m.PACKAGES))
    a = ap.parse_args()
    if a.commit and a.dry_run:
        raise SystemExit("choose one of --commit / --dry-run")
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    pkgs = [int(x) for x in a.packages.split(",")]
    if a.commit:
        check_no_other_instance()
    base.login()
    if a.verify:
        return verify(pkgs, 1500)
    run(a.commit, pkgs, a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
