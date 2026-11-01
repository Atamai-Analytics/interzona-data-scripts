#!/usr/bin/env python3
"""Set GCDataPoint.digestionNotes for LithoSurfer data package 244688701
("GTK: Finland Rock Samples"), one note per GTK laboratory method.

Each note states the nominal charge (also held in sampleWeightGm), a short
procedure summary from GTK's published method documentation (Rock Geochemical
Database of Finland, Report of Investigation 164 / AnalysisMethods), and - for
707I - that the digestion method is recorded under the closest vocabulary entry.

Reuses the verified machinery of update_finland_sample_weight.py (full-DTO PUT
with iCPMSLithoDTO sent as null so the server does not create empty ICP-MS
child rows).

Never overwrites existing text: a datapoint whose digestionNotes is already
non-empty and different is left alone and counted as "has_other_notes".
Idempotent / resumable (already-correct datapoints are skipped). Refuses to
start if another copy is running.

--dry-run  (default) read only, NEVER writes
--pages N  limit pages (200 datapoints each)
--test-one ID  update one datapoint and diff the whole record
--commit   perform the updates
--verify   read-only tally of digestionNotes per method + count totals
"""
import argparse
import collections
import copy
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
LOG_PATH = HERE / "finland_digestion_notes_244688701.log"
SRC = "Source: GTK Rock Geochemical Database of Finland, method documentation (Report of Investigation 164)."
NOMINAL = "nominal, from GTK method documentation, not weighed per sample"

NOTES = {
    "175X": f"Charge 7 g ({NOMINAL}). XRF pressed pellet: 7 g pulverised sample mixed with 210 mg binder wax, pressed at 20 t for 20 s; Philips PW1480 WDXRF, fundamental parameter method RRFPO (Ala-Vainio 1986). {SRC}",
    "511P": f"Charge 0.15 g ({NOMINAL}). Partial leach: 150 mg sample + 3 ml aqua regia, 90 C for 1 h, diluted to 15 ml; ICP-AES, 34 elements (Niskavaara 1995). Partial concentrations - refractory minerals (e.g. zircon, barite, chromite, ilmenite) are hardly dissolved. {SRC}",
    "511U": f"Charge 0.15 g ({NOMINAL}). Partial leach: 0.15 g sample + aqua regia, 90 C for 1 h, diluted to 15 ml; As and Ag by GFAAS, Se/Bi/Sb by GFAAS after reducing co-precipitation with mercury (NaBH4) (Niskavaara & Kontas 1990, modified). {SRC}",
    "521U": f"Charge 5 g ({NOMINAL}). Partial leach: 5 g sample + aqua regia at room temperature overnight, co-precipitation with mercury (SnCl2), precipitate redissolved in aqua regia to 2 ml; Au, Te, Pd by GFAAS (Kontas et al. 1990). {SRC}",
    "707I": f"Charge 0.1 g (100 mg; {NOMINAL}). Total fluorine: 100 mg sample fused with 2 g NaOH in a nickel crucible at 600 C for 20 min, melt dissolved in water, fluoride by ion-selective electrode with TISAB III (Fabbri & Donati 1981). Digestion method is recorded as 'Sodium Peroxide Fusion' - the closest vocabulary entry; the actual flux is NaOH. {SRC}",
    "811L": f"Charge 0.5 g ({NOMINAL}). Total carbon: 0.5 g powdered sample combusted in oxygen at 1370 C (LECO CR-12), CO2 by infrared detection. {SRC}",
    "816L": f"Charge 0.5 g ({NOMINAL}). Non-carbonate carbon (run when total carbon > 0.05 %): carbonate removed by repeated HCl (6 mol/l) treatment and washing, dried at 100 C, then LECO combustion as for 811L; carbonate carbon = C total - C non-carbonate, reported in the database as CO2. {SRC}",
    "308M": f"Charge 0.2 g ({NOMINAL}). Total element ICP-MS: 0.2 g sample + 10 ml 40 % HF and 4 ml 70 % HClO4 in a Teflon dish, evaporated; residue dissolved in 20 ml 8 mol/l HNO3 + 1 ml 30 % H2O2 and filtered; filter residue ashed in platinum, fused with 0.2 g lithium metaborate + 0.02 g sodium perborate, dissolved in 5 ml 0.8 mol/l HNO3 and combined with the filtrate, made up to 100 ml; Perkin-Elmer Sciex Elan 5000, normal resolution, external calibration, one measurement from one dilution (Rautiainen et al. 1996). Digestion method is recorded as 'Lithium Borate Fusion' - the closest vocabulary entry (acid dissolution followed by fusion of the residue). {SRC}",
}


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


def make_put_body(dto, note):
    new = copy.deepcopy(dto)
    new["gcdataPointDTO"]["digestionNotes"] = note
    new["iCPMSLithoDTO"] = None          # see update_finland_sample_weight.make_put_body
    return new


def process_page(page, commit, stats, lock):
    rows = base.api("GET", base.page_path(page)) or []
    local = collections.Counter()
    for dto in rows:
        code = (dto.get("gcdataPointDTO") or {}).get("sourceMethodCode")
        note = NOTES.get(code)
        local[f"seen:{code}"] += 1
        if note is None:
            local["unknown_method"] += 1
            continue
        cur = (dto["gcdataPointDTO"].get("digestionNotes") or "").strip()
        if cur == note:
            local["already_ok"] += 1
            continue
        if cur:
            local["has_other_notes"] += 1
            with lock, open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"SKIPPED id={dto.get('id')} existing notes kept: {cur[:120]!r}\n")
            continue
        if not commit:
            local["would_update"] += 1
            continue
        try:
            base.api("PUT", "/api/geochem/GCDataPoint", make_put_body(dto, note))
            local["updated"] += 1
        except urllib.error.HTTPError as e:
            local["failed"] += 1
            with lock, open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"FAILED id={dto.get('id')} http={e.code} {e.read().decode('utf-8','replace')[:200]}\n")
    with lock:
        stats.update(local)
    return page, len(rows)


def run_pages(commit, max_pages):
    pages = list(range(max_pages if max_pages else (base.EST_DATAPOINTS // base.PAGE_SIZE + 3)))
    stats, lock = collections.Counter(), threading.Lock()
    done = got = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
        for f in as_completed([ex.submit(process_page, p, commit, stats, lock) for p in pages]):
            _, n = f.result()
            done += 1; got += n
            if done % 10 == 0 or done == len(pages):
                print(f"  pages {done}/{len(pages)} | read {got} | updated {stats['updated']} | would_update {stats['would_update']} "
                      f"| already_ok {stats['already_ok']} | has_other_notes {stats['has_other_notes']} | failed {stats['failed']} "
                      f"| {(time.time()-t0)/60:.1f} min", flush=True)
    return stats, got


def test_one(dp_id):
    before = base.api("GET", f"/api/geochem/GCDataPoint/{dp_id}")
    code = before["gcdataPointDTO"].get("sourceMethodCode")
    note = NOTES.get(code)
    cur = before["gcdataPointDTO"].get("digestionNotes")
    print(f"datapoint {dp_id}: method {code}, current digestionNotes={cur!r}, new note {len(note or '')} chars")
    if note is None or (cur and cur.strip() != note):
        raise SystemExit("no note for this method, or existing different notes present - not touching")
    base.api("PUT", "/api/geochem/GCDataPoint", make_put_body(before, note))
    after = base.api("GET", f"/api/geochem/GCDataPoint/{dp_id}")
    d = base.diff(before, after)
    print(f"fields that differ after the PUT ({len(d)}):")
    for p, a, b in d:
        print(f"   {p}: {str(a)[:60]!r} -> {str(b)[:90]!r}")
    print("   sampleWeightGm still:", after["gcdataPointDTO"].get("sampleWeightGm"),
          "| counts:", after.get("countElementalConcentrations"), after.get("countOxideConcentrations"),
          "| ICPMS rows:", after["iCPMSLithoDTO"].get("id"))


def verify(max_pages):
    pages = list(range(max_pages if max_pages else (base.EST_DATAPOINTS // base.PAGE_SIZE + 3)))
    tally = collections.Counter(); ec = oc = n = 0

    def one(p):
        rows = base.api("GET", base.page_path(p)) or []
        t = collections.Counter(); e = o = 0
        for dto in rows:
            g = dto["gcdataPointDTO"]
            code = g.get("sourceMethodCode")
            ok_note = (g.get("digestionNotes") or "").strip() == NOTES.get(code)
            ok_w = base.same(g.get("sampleWeightGm"), base.WEIGHTS_G.get(code))
            icp = (dto.get("iCPMSLithoDTO") or {}).get("id")
            t[(code, ok_note, ok_w, icp is not None)] += 1
            e += dto.get("countElementalConcentrations") or 0
            o += dto.get("countOxideConcentrations") or 0
        return t, e, o, len(rows)

    with ThreadPoolExecutor(max_workers=base.WORKERS) as ex:
        for i, f in enumerate(as_completed([ex.submit(one, p) for p in pages]), 1):
            t, e, o, k = f.result()
            tally.update(t); ec += e; oc += o; n += k
            if i % 20 == 0:
                print(f"  verified pages {i}/{len(pages)}", flush=True)
    print(f"\nVERIFY: datapoints={n} element_conc={ec} oxide_conc={oc}")
    for (code, ok_note, ok_w, has_icp), c in sorted(tally.items(), key=lambda x: str(x[0])):
        print(f"   {code}: note_ok={ok_note} weight_ok={ok_w} icpms_rows_present={has_icp}: {c}")
    bad = sum(c for (code, ok_note, ok_w, has_icp), c in tally.items() if not (ok_note and ok_w) or has_icp)
    print(f"datapoints with a wrong/missing note, wrong weight, or stray ICP-MS rows: {bad}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--test-one", type=int)
    ap.add_argument("--pages", type=int, default=0)
    a = ap.parse_args()
    if a.commit and a.dry_run:
        raise SystemExit("choose one of --commit / --dry-run")
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    if a.commit or a.test_one:
        check_no_other_instance()
    base.login()
    if a.test_one:
        return test_one(a.test_one)
    if a.verify:
        return verify(a.pages)
    stats, got = run_pages(a.commit, a.pages)
    print("\n" + ("COMMIT" if a.commit else "DRY RUN (nothing written)") + f" - datapoints read: {got}")
    for k in sorted(stats):
        print(f"   {k}: {stats[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
