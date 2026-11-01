#!/usr/bin/env python3
"""Backfill materialId on already-created Sample records for LithoSurfer
data package 246454433 ("Resources Victoria: Soil Samples").

Background: the original load (load_victoria_soil_samples.py) left
materialId null for every sample - the `samples` table itself has no
material/lithology column. Lithology data was later found via
lithology_observations -> mindat_rocks (same join used by the
lithodat_samples view), giving a clean single material for 119,172 of
133,980 samples (see extract_victoria_material_map.R for the exact
exclusion rules: "Unclassified rock" is a real mindat_rocks entry but
semantically meaningless for soil so left null, as are the 157 samples
with genuinely multiple distinct materials and the 239 samples whose
material - Sand/Diorite/Colluvium - had no exact match in LithoSurfer's
materials list).

PUT /api/core/sample-with-locations is a full-replace update (no {id} in
the URL - id goes in the body) - there is no partial-patch endpoint. So
this script fetches the COMPLETE existing SampleWithLocationDTO for every
sample in the package first (cached to disk, resumable), then PUTs back
an exact copy with only sampleDTO.materialId changed - every other field
(name, dataPackageId, sampleKindId, sampleMethodId, locationKindId,
collectDateMin/Max, description, location name/lat/lon) is preserved
unchanged.

Guards against the exact concurrent-process bug that caused duplicate
GCAliquot rows earlier in this project: refuses to start if another copy
of this script is already running.

--dry-run does NOT write anything - only resolves matches and prints what
would change. Only --commit performs network writes, checkpointed by
sample id (resumable across restarts).

Usage:
    python update_victoria_material.py --dry-run 5
    python update_victoria_material.py --commit
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
TIMEOUT = 60
WORKERS = 10
PROGRESS_EVERY = 500
PACKAGE_ID = 246454433

HERE = Path(__file__).resolve().parent
SCRIPT_NAME = Path(__file__).name
MATERIAL_MAP_PATH = HERE / "victoria_material_map.json"
MATERIAL_BY_SAMPLE_PATH = HERE / "victoria_material_by_sample.tsv"
DTO_CACHE_PATH = HERE / f"sample_dtos_{PACKAGE_ID}.json"
CHECKPOINT_PATH = HERE / f"victoria_material_update_progress_{PACKAGE_ID}.txt"


def check_no_other_instance():
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
        print(f"REFUSING TO START: {len(lines)} python processes already reference {SCRIPT_NAME}. "
              f"Not starting a second copy against the same package.", file=sys.stderr)
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


def request(method: str, url: str, body=None, token=None, retries=3):
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
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def authenticate(host, username, password):
    body = {"username": username, "password": password, "rememberMe": False}
    result = request("POST", f"{host}/api/authenticate", body=body)
    token = result.get("id_token") if result else None
    if not token:
        raise SystemExit(f"Authentication response contained no id_token: {result}")
    return token


def fetch_existing_dtos(host: str, token: str) -> dict:
    """Return {sampleName_label: full SampleWithLocationDTO} for every
    sample in PACKAGE_ID. Cached to disk, resumed by page offset."""
    dtos = {}
    if DTO_CACHE_PATH.exists():
        dtos = json.loads(DTO_CACHE_PATH.read_text(encoding="utf-8"))
        if dtos.pop("__complete__", False):
            print(f"Loaded cached DTO map from {DTO_CACHE_PATH.name} ({len(dtos)} samples).")
            return dtos
        print(f"Resuming fetch from cached partial map ({len(dtos)} samples already fetched).")

    size = 500
    page = len(dtos) // size
    while True:
        url = f"{host}/api/core/sample-with-locations/post?page={page}&size={size}&sort=id,asc"
        body = {"dataPackageId": {"equals": PACKAGE_ID}}
        batch = request("POST", url, body=body, token=token) or []
        if not batch:
            break
        for item in batch:
            name = item.get("sampleDTO", {}).get("name") or ""
            label = name.split("\\\\", 1)[0]
            dtos[label] = item
        DTO_CACHE_PATH.write_text(json.dumps(dtos), encoding="utf-8")
        print(f"  ...fetched page {page} ({len(dtos)} samples so far)")
        if len(batch) < size:
            break
        page += 1

    dtos["__complete__"] = True
    DTO_CACHE_PATH.write_text(json.dumps(dtos), encoding="utf-8")
    del dtos["__complete__"]
    return dtos


def load_material_map():
    material_ids = json.loads(MATERIAL_MAP_PATH.read_text(encoding="utf-8"))
    sample_material = {}
    with MATERIAL_BY_SAMPLE_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            sample_material[row["sampleName"]] = row["material"]
    return material_ids, sample_material


def update_one(host, token, dto):
    try:
        request("PUT", f"{host}/api/core/sample-with-locations", body=dto, token=token)
        return True, None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {error.code}: {detail}"


def main():
    parser = argparse.ArgumentParser()
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
    print(f"Target data package: {PACKAGE_ID}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    material_ids, sample_material = load_material_map()
    print(f"Loaded {len(material_ids)} material reference ids and {len(sample_material)} sample->material rows.")

    print("Fetching existing Sample DTOs in the target package to resolve ids...")
    dtos = fetch_existing_dtos(host, token)
    print(f"Found {len(dtos)} existing samples in package {PACKAGE_ID}.")

    todo = []
    unmatched_sample = []
    unmatched_material = []
    already_set = 0
    for label, material_name in sample_material.items():
        dto = dtos.get(label)
        if dto is None:
            unmatched_sample.append(label)
            continue
        material_id = material_ids.get(material_name)
        if material_id is None:
            unmatched_material.append(material_name)
            continue
        if dto["sampleDTO"].get("materialId") == material_id:
            already_set += 1
            continue
        todo.append((label, dto, material_id))

    print(f"\n{len(todo)} sample(s) need materialId set ({already_set} already correct).")
    if unmatched_sample:
        print(f"WARNING: {len(unmatched_sample)} sample labels had no matching DTO, e.g.: {unmatched_sample[:5]}", file=sys.stderr)
    if unmatched_material:
        print(f"WARNING: {len(unmatched_material)} rows had unrecognised material: {sorted(set(unmatched_material))[:10]}", file=sys.stderr)

    if args.dry_run:
        sample = todo[:args.dry_run]
        print(f"\nDRY RUN - would update {len(sample)} of {len(todo)} sample(s) (no writes performed):")
        for label, dto, material_id in sample:
            updated = json.loads(json.dumps(dto))
            updated["sampleDTO"]["materialId"] = material_id
            print(f"  {label}: materialId {dto['sampleDTO'].get('materialId')} -> {material_id}")
        print("\n(dry run only validates matching - re-run with --commit to actually write)")
        return 0

    done_ids = set()
    if CHECKPOINT_PATH.exists():
        done_ids = {x for x in CHECKPOINT_PATH.read_text().split() if x.strip()}
        print(f"Resuming: {len(done_ids)} already updated per checkpoint {CHECKPOINT_PATH.name}.")

    pending = [(label, dto, material_id) for label, dto, material_id in todo if str(dto["id"]) not in done_ids]
    print(f"\nUpdating {len(pending)} Sample(s) ({len(todo) - len(pending)} already done) with {WORKERS} parallel workers...")

    ok_count = 0
    err_count = 0
    errors_shown = 0
    checkpoint_file = CHECKPOINT_PATH.open("a", buffering=1)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {}
            for label, dto, material_id in pending:
                updated = json.loads(json.dumps(dto))
                updated["sampleDTO"]["materialId"] = material_id
                futures[pool.submit(update_one, host, token, updated)] = (label, dto["id"])
            done = 0
            for future in as_completed(futures):
                label, sample_id = futures[future]
                success, error_detail = future.result()
                done += 1
                if success:
                    ok_count += 1
                    checkpoint_file.write(f"{sample_id}\n")
                else:
                    err_count += 1
                    if errors_shown < 10:
                        print(f"  FAILED {label!r} (id={sample_id}): {error_detail}", file=sys.stderr)
                        errors_shown += 1
                if done % PROGRESS_EVERY == 0 or done == len(pending):
                    print(f"  {done}/{len(pending)} processed ({ok_count} ok, {err_count} failed)")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Updated {ok_count} Sample(s) this run, {err_count} failed.")
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
