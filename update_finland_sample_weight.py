#!/usr/bin/env python3
"""Set GCDataPoint.sampleWeightGm for LithoSurfer data package 244688701
("GTK: Finland Rock Samples").

Source of the values: GTK's published method documentation (Report of
Investigation 164 / AnalysisMethods.docx) - the charge per laboratory method.
These are NOMINAL per-method charges, not weighed per sample (the same values
are in criticialmineralsexp.analytical_packages.minimumsampleweight):

    175X  XRF pressed pellet          7    g
    511P  ICP-AES aqua regia          0.15 g
    511U  GFAAS aqua regia            0.15 g
    521U  GFAAS aqua regia (Au,Te,Pd) 5    g
    707I  fluorine, NaOH fusion       0.1  g
    811L  total carbon (LECO)         0.5  g
    816L  non-carbonate carbon (LECO) 0.5  g

PUT /api/geochem/GCDataPoint is a FULL replace of GCDataPointLithoDTO (no
partial update exists), so each datapoint's complete current DTO is fetched
and PUT back unchanged except gcdataPointDTO.sampleWeightGm.

Idempotent and resumable: a datapoint that already holds the target value is
skipped, so after any interruption just run it again. Refuses to start if
another copy is already running (the duplicate-creation lesson from the
GCAliquot load).

--dry-run  (default) reads only; reports what WOULD change. NEVER writes.
--pages N  limit to the first N pages (200 datapoints each)
--test-one ID  update one datapoint and print a before/after diff of the whole record
--commit   perform the updates
--verify   read-only: tally sampleWeightGm per method and the element/oxide count totals
"""
import argparse
import collections
import copy
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

HERE = Path(__file__).resolve().parent
SCRIPT_NAME = Path(__file__).name
PACKAGE_ID = 244688701
PAGE_SIZE = 200
EST_DATAPOINTS = 48341
WORKERS = 12
TIMEOUT = 90
WEIGHTS_G = {"175X": 7.0, "511P": 0.15, "511U": 0.15, "521U": 5.0, "707I": 0.1, "811L": 0.5, "816L": 0.5, "308M": 0.2}
LOG_PATH = HERE / f"finland_sample_weight_{PACKAGE_ID}.log"

_token = {"value": None}
_token_lock = threading.Lock()
_creds = {}


def check_no_other_instance():
    if platform.system() != "Windows":
        return
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object -ExpandProperty CommandLine"],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"WARNING: could not check for other instances ({e}); proceeding.", file=sys.stderr)
        return
    lines = [l for l in r.stdout.splitlines() if SCRIPT_NAME in l]
    if len(lines) > 1:
        print(f"REFUSING TO START: {len(lines)} python processes already reference {SCRIPT_NAME}.", file=sys.stderr)
        raise SystemExit(1)


def load_dotenv():
    for env_file in (Path.cwd() / ".env", HERE / ".env"):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip("\"'")
            if v:
                os.environ.setdefault(k.strip(), v)


def raw_request(method, url, body=None, token=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        payload = r.read().decode("utf-8")
    return json.loads(payload) if payload else None


def login(force=False):
    with _token_lock:
        if _token["value"] and not force:
            return _token["value"]
        res = raw_request("POST", f"{_creds['host']}/api/authenticate",
                          {"username": _creds["user"], "password": _creds["pw"], "rememberMe": False})
        _token["value"] = res["id_token"]
        return _token["value"]


def api(method, path, body=None, retries=6):
    url = _creds["host"] + path
    reauthed = False
    for attempt in range(1, retries + 1):
        try:
            return raw_request(method, url, body, login())
        except urllib.error.HTTPError as e:
            if e.code == 401 and not reauthed:
                login(force=True); reauthed = True; continue
            if e.code in (502, 503, 504) and attempt < retries:
                time.sleep(3 * attempt); continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def page_path(page):
    return (f"/api/geochem/GCDataPoint?dataPointLithoCriteria.dataPackageId.equals={PACKAGE_ID}"
            f"&page={page}&size={PAGE_SIZE}&sort=id,asc")


def target_for(dto):
    code = (dto.get("gcdataPointDTO") or {}).get("sourceMethodCode")
    return code, WEIGHTS_G.get(code)


def make_put_body(dto, want):
    """Complete current DTO with only sampleWeightGm changed.

    iCPMSLithoDTO is sent as null: GET returns it as an all-null skeleton with no
    ids, and echoing that skeleton back makes the server CREATE eight empty ICP-MS
    metadata child rows per datapoint (seen on the first test). These datapoints
    are XRF / aqua-regia / combustion, not ICP-MS, so null is the faithful value.
    """
    new = copy.deepcopy(dto)
    new["gcdataPointDTO"]["sampleWeightGm"] = want
    new["iCPMSLithoDTO"] = None
    return new


def same(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k), b.get(k), f"{path}.{k}" if path else k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append((path, a, b))
    return out


def process_page(page, commit, stats, lock):
    rows = api("GET", page_path(page)) or []
    local = collections.Counter()
    for dto in rows:
        code, want = target_for(dto)
        local[f"seen:{code}"] += 1
        if want is None:
            local["unknown_method"] += 1
            continue
        cur = (dto.get("gcdataPointDTO") or {}).get("sampleWeightGm")
        if same(cur, want):
            local["already_ok"] += 1
            continue
        if not commit:
            local["would_update"] += 1
            local[f"would:{code}"] += 1
            continue
        new = make_put_body(dto, want)
        try:
            api("PUT", "/api/geochem/GCDataPoint", new)
            local["updated"] += 1
            local[f"updated:{code}"] += 1
        except urllib.error.HTTPError as e:
            local["failed"] += 1
            with lock, open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"FAILED id={dto.get('id')} http={e.code} {e.read().decode('utf-8','replace')[:200]}\n")
    with lock:
        stats.update(local)
    return page, len(rows)


def run_pages(commit, max_pages):
    pages = list(range(max_pages if max_pages else (EST_DATAPOINTS // PAGE_SIZE + 3)))
    stats, lock = collections.Counter(), threading.Lock()
    done = got = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process_page, p, commit, stats, lock) for p in pages]
        for f in as_completed(futs):
            page, n = f.result()
            done += 1; got += n
            if done % 10 == 0 or done == len(pages):
                el = time.time() - t0
                print(f"  pages {done}/{len(pages)} | datapoints read {got} | updated {stats['updated']} | would_update {stats['would_update']} "
                      f"| already_ok {stats['already_ok']} | failed {stats['failed']} | {el/60:.1f} min", flush=True)
    return stats, got


def test_one(dp_id):
    before = api("GET", f"/api/geochem/GCDataPoint/{dp_id}")
    code, want = target_for(before)
    print(f"datapoint {dp_id}: method {code}, current sampleWeightGm={before['gcdataPointDTO'].get('sampleWeightGm')}, target={want}")
    if want is None:
        raise SystemExit("no target weight for this method")
    new = make_put_body(before, want)
    api("PUT", "/api/geochem/GCDataPoint", new)
    after = api("GET", f"/api/geochem/GCDataPoint/{dp_id}")
    d = diff(before, after)
    print(f"fields that differ after the PUT ({len(d)}):")
    for p, a, b in d:
        print(f"   {p}: {a!r} -> {b!r}")
    for k in ("countElementalConcentrations", "countOxideConcentrations"):
        print(f"   {k}: {before.get(k)} -> {after.get(k)}")


def verify(max_pages):
    pages = list(range(max_pages if max_pages else (EST_DATAPOINTS // PAGE_SIZE + 3)))
    tally = collections.Counter(); ec = oc = n = 0
    lock = threading.Lock()

    def one(p):
        rows = api("GET", page_path(p)) or []
        t = collections.Counter(); e = o = 0
        for dto in rows:
            g = dto.get("gcdataPointDTO") or {}
            t[(g.get("sourceMethodCode"), g.get("sampleWeightGm"))] += 1
            e += dto.get("countElementalConcentrations") or 0
            o += dto.get("countOxideConcentrations") or 0
        return t, e, o, len(rows)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, f in enumerate(as_completed([ex.submit(one, p) for p in pages]), 1):
            t, e, o, k = f.result()
            tally.update(t); ec += e; oc += o; n += k
            if i % 20 == 0:
                print(f"  verified pages {i}/{len(pages)}", flush=True)
    print(f"\nVERIFY: datapoints={n} element_conc={ec} oxide_conc={oc}")
    for (code, w), c in sorted(tally.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
        print(f"   {code}  sampleWeightGm={w}: {c}")
    bad = sum(c for (code, w), c in tally.items() if WEIGHTS_G.get(code) is None or not same(w, WEIGHTS_G.get(code)))
    print(f"datapoints NOT at their target weight: {bad}")


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
    load_dotenv()
    _creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                  user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    if a.commit or a.test_one:
        check_no_other_instance()
    login()
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
