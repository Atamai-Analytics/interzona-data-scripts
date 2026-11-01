#!/usr/bin/env python3
"""Copy documented analytical charge weights onto GCDataPoint.sampleWeightGm (and
an explanatory digestionNotes) for the Victoria and Greenland LithoSurfer packages.

Weights come from package_charge_weights_applied.csv / package_charge_weights_web.csv
(the same audited values written to criticialmineralsexp.analytical_packages
.minimumsampleweight), matched on GCDataPoint.sourceMethodCode == package_code.

Rules (conservative):
  * packages whose weight is a RANGE LOWER BOUND are NOT copied (a minimum is not a charge)
  * an existing, different sampleWeightGm is never overwritten (counted as has_other_weight)
  * existing digestionNotes text is never overwritten (weight is still set; counted notes_kept)
  * iCPMSLithoDTO is sent as null ONLY when it is the empty skeleton (id None) - real
    ICP-MS metadata, if any, is echoed back untouched
  * PUT /api/geochem/GCDataPoint is full-replace, so the complete current DTO is sent back
    with only gcdataPointDTO.sampleWeightGm / digestionNotes changed

Idempotent and resumable (already-correct datapoints are skipped). Refuses to start if
another copy is running.

--dry-run (default) read only; --pages N limit pages per package; --packages a,b,c
--test-one ID   update one datapoint, print a full before/after diff
--commit        perform the updates (also records the pre-update element/oxide count totals)
--verify        read-only audit of every datapoint + count totals per package
"""
import argparse
import collections
import copy
import csv
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
SCRIPT_NAME = Path(__file__).name
LOG_PATH = HERE / "charge_weights_datapoints.log"
PACKAGES = {246454433: ("Victoria soil", 203413), 205700763: ("Greenland rock", 22078),
            205700765: ("Greenland stream", 73459), 205700764: ("Greenland soil", 3567),
            205700762: ("Greenland HMC", 1692)}
CSVS = ("package_charge_weights_applied.csv", "package_charge_weights_web.csv")
SOURCE_SHORT = {"GSV": "Source: Geological Survey of Victoria geochemistry database, method description."}


def load_mapping():
    rows = []
    for f in CSVS:
        rows += list(csv.DictReader(open(HERE / f, encoding="utf-8", newline="")))
    mapping = {}
    for r in rows:
        if r["basis"].startswith("range lower bound"):
            continue
        mapping[r["package_code"]] = (float(r["weight_g"]), build_note(r))
    return mapping


def build_note(r):
    w = float(r["weight_g"])
    txt = " ".join(r["source_text"].replace('"', "").split())
    if len(txt) > 190:
        txt = txt[:187] + "..."
    if r["basis"].startswith("lab-published"):
        qual = "nominal routine charge published by the laboratory (allowed 5-50 g); the charge actually used is not recorded in the source"
    else:
        qual = "nominal, as stated in the method description; not weighed per sample"
    src = r["source"]
    if src.startswith("GSV Geochemistry"):
        src = "Geological Survey of Victoria geochemistry database, method description"
    elif len(src) > 230:
        src = src[:227] + "..."
    return f'Charge {w:g} g ({qual}). Method text: "{txt}". Source: {src}.'


MAPPING = load_mapping()


def check_no_other_instance():
    if platform.system() != "Windows":
        return
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object -ExpandProperty CommandLine"],
                       capture_output=True, text=True, timeout=30)
    lines = [l for l in r.stdout.splitlines() if SCRIPT_NAME in l]
    if len(lines) > 1:
        print(f"REFUSING TO START: {len(lines)} python processes already reference {SCRIPT_NAME}.", file=sys.stderr)
        raise SystemExit(1)


def page_path(pid, page):
    return (f"/api/geochem/GCDataPoint?dataPointLithoCriteria.dataPackageId.equals={pid}"
            f"&page={page}&size={base.PAGE_SIZE}&sort=id,asc")


def make_put_body(dto, weight, note):
    new = copy.deepcopy(dto)
    g = new["gcdataPointDTO"]
    g["sampleWeightGm"] = weight
    if not (g.get("digestionNotes") or "").strip():
        g["digestionNotes"] = note
    if (new.get("iCPMSLithoDTO") or {}).get("id") is None:
        new["iCPMSLithoDTO"] = None      # empty skeleton only; see update_finland_sample_weight
    return new


def process_page(pid, page, commit, stats, lock):
    rows = base.api("GET", page_path(pid, page)) or []
    local = collections.Counter()
    for dto in rows:
        g = dto.get("gcdataPointDTO") or {}
        code = g.get("sourceMethodCode")
        local["read"] += 1
        local["base_ec"] += dto.get("countElementalConcentrations") or 0
        local["base_oc"] += dto.get("countOxideConcentrations") or 0
        m = MAPPING.get(code)
        if m is None:
            local["no_weight_for_method"] += 1
            continue
        weight, note = m
        cur = g.get("sampleWeightGm")
        if base.same(cur, weight) and (g.get("digestionNotes") or "").strip():
            local["already_ok"] += 1
            continue
        if cur is not None and not base.same(cur, weight):
            local["has_other_weight"] += 1
            with lock, open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"SKIPPED id={dto.get('id')} existing weight {cur} kept (target {weight} for {code})\n")
            continue
        if (g.get("digestionNotes") or "").strip() and (g.get("digestionNotes") or "").strip() != note:
            local["notes_kept"] += 1
        if not commit:
            local["would_update"] += 1
            continue
        try:
            base.api("PUT", "/api/geochem/GCDataPoint", make_put_body(dto, weight, note))
            local["updated"] += 1
        except urllib.error.HTTPError as e:
            local["failed"] += 1
            with lock, open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"FAILED id={dto.get('id')} http={e.code} {e.read().decode('utf-8','replace')[:200]}\n")
    with lock:
        stats.update(local)
    return len(rows)


def run(commit, pkgs, max_pages):
    for pid in pkgs:
        label, est = PACKAGES[pid]
        pages = list(range(max_pages if max_pages else (est // base.PAGE_SIZE + 3)))
        stats, lock = collections.Counter(), threading.Lock()
        done = 0
        t0 = time.time()
        print(f"\n=== {label} ({pid}) - {len(pages)} pages", flush=True)
        with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
            for f in as_completed([ex.submit(process_page, pid, p, commit, stats, lock) for p in pages]):
                f.result(); done += 1
                if done % 20 == 0 or done == len(pages):
                    print(f"  pages {done}/{len(pages)} | read {stats['read']} | updated {stats['updated']} | would_update {stats['would_update']} "
                          f"| already_ok {stats['already_ok']} | other_weight {stats['has_other_weight']} | notes_kept {stats['notes_kept']} "
                          f"| failed {stats['failed']} | {(time.time()-t0)/60:.1f} min", flush=True)
        print(f"--- {label} DONE ({'COMMIT' if commit else 'DRY RUN'}): " + ", ".join(f"{k}={stats[k]}" for k in sorted(stats)), flush=True)


def test_one(dp_id):
    before = base.api("GET", f"/api/geochem/GCDataPoint/{dp_id}")
    g = before["gcdataPointDTO"]
    code = g.get("sourceMethodCode")
    m = MAPPING.get(code)
    print(f"datapoint {dp_id}: method {code}, weight={g.get('sampleWeightGm')}, notes={g.get('digestionNotes')!r}")
    if m is None:
        raise SystemExit("no documented weight for this method")
    weight, note = m
    print(f"  target weight {weight} g; note ({len(note)} chars): {note}")
    base.api("PUT", "/api/geochem/GCDataPoint", make_put_body(before, weight, note))
    after = base.api("GET", f"/api/geochem/GCDataPoint/{dp_id}")
    d = base.diff(before, after)
    print(f"fields that differ after the PUT ({len(d)}):")
    for p, a, b in d:
        print(f"   {p}: {str(a)[:50]!r} -> {str(b)[:70]!r}")
    print("   counts:", before.get("countElementalConcentrations"), before.get("countOxideConcentrations"), "->",
          after.get("countElementalConcentrations"), after.get("countOxideConcentrations"))


def verify(pkgs, max_pages):
    for pid in pkgs:
        label, est = PACKAGES[pid]
        pages = list(range(max_pages if max_pages else (est // base.PAGE_SIZE + 3)))
        tally, lock = collections.Counter(), threading.Lock()
        sums = collections.Counter()

        def one(p):
            rows = base.api("GET", page_path(pid, p)) or []
            t = collections.Counter(); e = o = 0
            for dto in rows:
                g = dto["gcdataPointDTO"]; code = g.get("sourceMethodCode")
                m = MAPPING.get(code); w = g.get("sampleWeightGm")
                notes = (g.get("digestionNotes") or "").strip()
                if m is None:
                    state = "unmapped-weight-empty" if w is None else "UNMAPPED-HAS-WEIGHT"
                else:
                    state = ("weight-ok" if base.same(w, m[0]) else "WEIGHT-WRONG") + ("/note-ours" if notes == m[1] else "/note-other" if notes else "/NOTE-EMPTY")
                if (dto.get("iCPMSLithoDTO") or {}).get("id") is not None:
                    state += "/icpms-rows"
                t[state] += 1; e += dto.get("countElementalConcentrations") or 0; o += dto.get("countOxideConcentrations") or 0
            return t, e, o, len(rows)

        n = 0
        with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
            for i, f in enumerate(as_completed([ex.submit(one, p) for p in pages]), 1):
                t, e, o, k = f.result(); tally.update(t); sums["ec"] += e; sums["oc"] += o; n += k
                if i % 40 == 0:
                    print(f"  {label}: verified pages {i}/{len(pages)}", flush=True)
        print(f"\nVERIFY {label} ({pid}): datapoints={n} element_conc={sums['ec']} oxide_conc={sums['oc']}")
        for k, c in sorted(tally.items()):
            print(f"   {k}: {c}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--test-one", type=int)
    ap.add_argument("--pages", type=int, default=0)
    ap.add_argument("--packages", default=",".join(str(p) for p in PACKAGES))
    a = ap.parse_args()
    if a.commit and a.dry_run:
        raise SystemExit("choose one of --commit / --dry-run")
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    pkgs = [int(x) for x in a.packages.split(",")]
    if a.commit or a.test_one:
        check_no_other_instance()
    base.login()
    if a.test_one:
        return test_one(a.test_one)
    if a.verify:
        return verify(pkgs, a.pages)
    run(a.commit, pkgs, a.pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
