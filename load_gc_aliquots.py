#!/usr/bin/env python3
"""Load one GCAliquot per already-loaded GCDataPoint into a LithoSurfer data
package, via single-row POST /api/geochem/GCAliquot (no /batch endpoint
exists for this entity).

Source: reuses the same gcdp_<package>.tsv files produced for the
GCDataPoint load (see load_gc_datapoints.py) - one row per datapointName,
with a "units" column used to reconstruct the exact label (including the
"[units]" suffix for multi-unit data points) that was used as that data
point's name.

Design decision (confirmed with user): geochem_export_detail's aliquotName
is unique per measurement row, not per physical aliquot - essentially every
analysis in this dataset was run on a single prepared aliquot per data
point. So this script creates exactly one GCAliquot per GCDataPoint, named
the same as the data point's own label (not a fabricated constant, not the
source's essentially-arbitrary per-row aliquotName values).

--dry-run does NOT write anything - it only resolves matches and prints
what would be sent. This is deliberate: GCAliquot create is not
transactional/batched and has no uniqueness constraint we can rely on to
make a dry-run test record harmless to re-run into the real commit (we hit
that exact problem twice with the batch-create entities). Only --commit
performs network writes.

Usage:
    python load_gc_aliquots.py --package-id 205700763 --tsv gcdp_rock.tsv --dry-run 5
    python load_gc_aliquots.py --package-id 205700763 --tsv gcdp_rock.tsv --commit
"""

import argparse
import csv
import getpass
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 180  # GCDataPoint records carry heavy nested metadata (a 500-record
# page measured at 3.37MB / ~66s) - the old 60s timeout was routinely
# tripping on legitimately-slow-but-successful responses, causing endless
# spurious retries instead of ever completing.
NAME_SEP = r"\\"
WORKERS = 10
PROGRESS_EVERY = 500

HERE = Path(__file__).resolve().parent
SCRIPT_NAME = Path(__file__).name


def check_no_other_instance():
    """Refuse to start a second concurrent copy of this script.

    This is here because the environment has repeatedly reported this
    script's background process as "stopped" when it was actually still
    alive, leading a well-intentioned resume to start a second (and once, a
    third) copy running against the same package at once. Since GCAliquot
    create has no uniqueness constraint, that produced thousands of
    duplicate rows that had to be found and deleted after the fact. Check
    before every --commit run, not just once.
    """
    if platform.system() != "Windows":
        return
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as error:
        print(f"WARNING: could not check for other running instances ({error}); proceeding anyway.", file=sys.stderr)
        return
    lines = [l for l in result.stdout.splitlines() if SCRIPT_NAME in l]
    if len(lines) > 1:
        print(f"REFUSING TO START: {len(lines)} python processes already reference {SCRIPT_NAME} "
              f"(this process is one of them). Not starting a second copy against the same package.",
              file=sys.stderr)
        raise SystemExit(1)


def load_dotenv() -> None:
    for env_file in (Path.cwd() / ".env", HERE / ".env"):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if value:
                os.environ.setdefault(key.strip(), value)


def request(method: str, url: str, body=None, token=None, retries=6):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            if error.code in (502, 503, 504) and attempt < retries:
                print(f"  (HTTP {error.code}, retrying {attempt}/{retries})", file=sys.stderr)
                time.sleep(3 * attempt)
                continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            if attempt == retries:
                raise
            print(f"  ({error}, retrying {attempt}/{retries})", file=sys.stderr)
            time.sleep(2 * attempt)


def authenticate(host, username, password):
    body = {"username": username, "password": password, "rememberMe": False}
    result = request("POST", f"{host}/api/authenticate", body=body)
    token = result.get("id_token") if result else None
    if not token:
        raise SystemExit(f"Authentication response contained no id_token: {result}")
    return token


def datapoint_id_cache_path(package_id: int) -> Path:
    return HERE / f"datapoint_ids_{package_id}.json"


def fetch_existing_datapoint_labels(host: str, token: str, package_id: int) -> dict:
    """Return {label: gcdataPointId} for every GCDataPoint already in package_id.

    Cached to disk (datapoint_ids_<package>.json), written after EVERY page
    (not just at the end) and resumed by page offset on restart - this
    environment has been killing long-running background processes
    mid-fetch, so a fetch that only saved at completion would restart from
    page 0 every time. Pagination uses an explicit sort so the resume-by-
    page-offset logic sees a stable, repeatable order.
    """
    cache_path = datapoint_id_cache_path(package_id)
    size = 200  # smaller page = lighter/faster individual requests, given
    # how large GCDataPoint's nested payload is (see TIMEOUT comment above)
    labels = {}
    if cache_path.exists():
        labels = json.loads(cache_path.read_text(encoding="utf-8"))
        if labels.get("__complete__"):
            print(f"Loading cached data-point id map from {cache_path.name}...")
            del labels["__complete__"]
            return labels
        print(f"Resuming fetch from cached partial map ({len(labels)} data points already fetched).")

    page = len(labels) // size
    while True:
        url = f"{host}/api/geochem/GCDataPoint/post?page={page}&size={size}&sort=id,asc"
        body = {"dataPointLithoCriteria": {"dataPackageId": {"equals": package_id}}}
        batch = request("POST", url, body=body, token=token) or []
        if not batch:
            break
        for item in batch:
            name = item.get("dataPointDTO", {}).get("name") or ""
            gc_id = item.get("id")
            label = name.split(NAME_SEP, 1)[0]
            labels[label] = gc_id
        cache_path.write_text(json.dumps(labels), encoding="utf-8")
        print(f"  ...fetched page {page} ({len(labels)} data points so far)")
        if len(batch) < size:
            break
        page += 1

    labels["__complete__"] = True
    cache_path.write_text(json.dumps(labels), encoding="utf-8")
    del labels["__complete__"]
    print(f"Cached data-point id map to {cache_path.name} for reuse.")
    return labels


def fetch_specific_datapoint_labels(host: str, token: str, package_id: int, wanted_labels: list) -> dict:
    """Look up just a handful of labels directly (fast path for --dry-run),
    instead of paging through the whole package.

    Uses "contains" on the label rather than an exact match against
    "{label}{NAME_SEP}<session-id>" - the session-id suffix varies by
    commit date/run, so hardcoding one here goes stale the moment a new
    commit uses a different date (confirmed: this previously hardcoded
    "20260822-gcdp" from an old GEUS run, silently breaking dry-run
    matching for every load done since). The label itself is already
    unique per data point, so "contains" is safe here.
    """
    labels = {}
    for label in wanted_labels:
        body = {"dataPointLithoCriteria": {"dataPackageId": {"equals": package_id}, "name": {"contains": label}}}
        res = request("POST", f"{host}/api/geochem/GCDataPoint/post?page=0&size=5", body=body, token=token) or []
        for item in res:
            name = item.get("dataPointDTO", {}).get("name") or ""
            if name.split(NAME_SEP, 1)[0] == label:
                labels[label] = item["id"]
                break
    return labels


def load_labels_from_tsv(tsv_path: Path):
    labels = []
    with tsv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            units = row["units"] or ""
            label = f"{row['datapointName']} [{units}]" if "/" in units else row["datapointName"]
            labels.append(label)
    return labels


def create_one(host, token, gc_id, aliquot_name):
    body = {"id": None, "aliquotName": aliquot_name, "gcdataPointId": gc_id}
    try:
        request("POST", f"{host}/api/geochem/GCAliquot", body=body, token=token)
        return True, None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {error.code}: {detail}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", type=int, metavar="N")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    if args.commit:
        check_no_other_instance()

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target data package: {args.package_id}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    labels = load_labels_from_tsv(args.tsv)
    print(f"\nLoaded {len(labels)} data-point labels from {args.tsv.name}.")

    if args.dry_run:
        sample_labels = labels[:args.dry_run]
        print(f"Looking up {len(sample_labels)} specific data points (fast path, no full fetch)...")
        label_to_gcid = fetch_specific_datapoint_labels(host, token, args.package_id, sample_labels)
        matched = [(label, label_to_gcid[label]) for label in sample_labels if label in label_to_gcid]
        unmatched = [label for label in sample_labels if label not in label_to_gcid]
        print(f"\nMatched {len(matched)}/{len(sample_labels)} labels to existing GCDataPoints.")
        if unmatched:
            print(f"WARNING: unmatched: {unmatched}", file=sys.stderr)
        print(f"\nDRY RUN - would create {len(matched)} GCAliquot(s) (no writes performed):")
        for label, gc_id in matched:
            print(f"  aliquotName={label!r} gcdataPointId={gc_id}")
        print("\n(dry run only validates matching - re-run with --commit to actually write)")
        return 0

    print("Fetching existing GCDataPoints in the target package to resolve ids...")
    label_to_gcid = fetch_existing_datapoint_labels(host, token, args.package_id)
    print(f"Found {len(label_to_gcid)} existing data points in package {args.package_id}.")

    matched = [(label, label_to_gcid[label]) for label in labels if label in label_to_gcid]
    unmatched = [label for label in labels if label not in label_to_gcid]
    print(f"\nMatched {len(matched)}/{len(labels)} labels to existing GCDataPoints.")
    if unmatched:
        print(f"WARNING: {len(unmatched)} unmatched, e.g.: {unmatched[:5]}", file=sys.stderr)

    checkpoint_path = HERE / f"gcaliquot_progress_{args.package_id}.txt"
    done_gc_ids = set()
    if checkpoint_path.exists():
        done_gc_ids = {int(x) for x in checkpoint_path.read_text().split() if x.strip()}
        print(f"Resuming: {len(done_gc_ids)} already created per checkpoint {checkpoint_path.name}.")

    todo = [(label, gc_id) for label, gc_id in matched if gc_id not in done_gc_ids]
    print(f"\nCreating {len(todo)} GCAliquot(s) ({len(matched) - len(todo)} already done) with {WORKERS} parallel workers...")

    ok_count = 0
    err_count = 0
    errors_shown = 0
    checkpoint_file = checkpoint_path.open("a", buffering=1)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {
                pool.submit(create_one, host, token, gc_id, label): (label, gc_id)
                for label, gc_id in todo
            }
            done = 0
            for future in as_completed(futures):
                label, gc_id = futures[future]
                success, error_detail = future.result()
                done += 1
                if success:
                    ok_count += 1
                    checkpoint_file.write(f"{gc_id}\n")
                else:
                    err_count += 1
                    if errors_shown < 10:
                        print(f"  FAILED {label!r}: {error_detail}", file=sys.stderr)
                        errors_shown += 1
                if done % PROGRESS_EVERY == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} processed ({ok_count} ok, {err_count} failed)")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Created {ok_count} GCAliquot(s) this run, {err_count} failed.")
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
