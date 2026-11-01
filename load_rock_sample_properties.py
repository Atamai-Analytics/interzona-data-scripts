#!/usr/bin/env python3
"""Load sample properties for LithoSurfer data package 205700763
("GEUS: Greenland Rock Samples") from the criticialmineralsexp Postgres
database, via POST /api/core/SampleProperty/batch.

Source data (already extracted to CSV alongside this script):
  rock_sample_combos.csv    - comboId -> locationName, sourceURL, referenceLink
                               (66 distinct combinations, from
                               location_properties_export filtered to
                               countryname='Greenland',
                               datasource='GEUS - Geological Survey of
                               Denmark and Greenland', sample_type_id=4,
                               isactive=true)
  rock_sample_combo_map.csv - sampleName -> comboId, one row per sample
                               (6957 rows)

For each sample this creates three SampleProperty rows: locationName,
sourceURL, referenceLink.

Matching: the source "sampleName" (e.g. "9218520//AA") is the label used
when the samples were originally batch-created in LithoSurfer, i.e. the
part of the stored name before the "\\\\<session-id>" suffix. This script
fetches all existing samples in the target package and matches on that
label.

Usage:
    python load_rock_sample_properties.py --dry-run [N]   # first N samples only
    python load_rock_sample_properties.py --commit         # full load

Credentials come from .env in this folder (see 00_getting-started/).
"""

import argparse
import csv
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 60
DATA_PACKAGE_ID = 205700763
NAME_SEP = r"\\"  # literal two-backslash label/session-id separator
CHUNK_SIZE = 2000

HERE = Path(__file__).resolve().parent
COMBOS_CSV = HERE / "rock_sample_combos.csv"
COMBO_MAP_CSV = HERE / "rock_sample_combo_map.csv"


def load_dotenv() -> None:
    candidates = [Path.cwd() / ".env", HERE / ".env"]
    for env_file in candidates:
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
            print(f"  ({error}, retrying {attempt}/{retries})", file=sys.stderr)
            time.sleep(2 * attempt)


def authenticate(host: str, username: str, password: str) -> str:
    body = {"username": username, "password": password, "rememberMe": False}
    result = request("POST", f"{host}/api/authenticate", body=body)
    token = result.get("id_token") if result else None
    if not token:
        raise SystemExit(f"Authentication response contained no id_token: {result}")
    return token


def fetch_existing_sample_labels(host: str, token: str) -> dict:
    """Return {label: sampleId} for every sample already in DATA_PACKAGE_ID."""
    labels = {}
    page = 0
    size = 500
    while True:
        url = f"{host}/api/core/sample-with-locations/post?page={page}&size={size}&sort=id,asc"
        body = {"dataPackageId": {"equals": DATA_PACKAGE_ID}}
        batch = request("POST", url, body=body, token=token) or []
        if not batch:
            break
        for item in batch:
            sample = item.get("sampleDTO", {})
            name = sample.get("name") or ""
            sample_id = sample.get("id")
            label = name.split(NAME_SEP, 1)[0]
            if label in labels:
                print(f"WARNING: duplicate label '{label}' (ids {labels[label]} and {sample_id})", file=sys.stderr)
            labels[label] = sample_id
        if len(batch) < size:
            break
        page += 1
    return labels


def load_combos():
    combos = {}
    with COMBOS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            combos[row["comboId"]] = {
                "locationName": row["locationName"],
                "sourceURL": row["sourceURL"],
                "referenceLink": row["referenceLink"],
            }
    return combos


def load_combo_map(limit=None):
    rows = []
    with COMBO_MAP_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append((row["sampleName"], row["comboId"]))
            if limit and len(rows) >= limit:
                break
    return rows


def build_property_dtos(combo_map, combos, label_to_id):
    dtos = []
    unmatched = []
    for sample_name, combo_id in combo_map:
        sample_id = label_to_id.get(sample_name)
        if sample_id is None:
            unmatched.append(sample_name)
            continue
        combo = combos[combo_id]
        for prop_name, prop_value in combo.items():
            dtos.append({
                "id": None,
                "sampleId": sample_id,
                "propName": prop_name,
                "propValue": prop_value,
            })
    return dtos, unmatched


def send_batches(host: str, token: str, dtos: list):
    total_sent = 0
    for start in range(0, len(dtos), CHUNK_SIZE):
        chunk = dtos[start:start + CHUNK_SIZE]
        url = f"{host}/api/core/SampleProperty/batch"
        try:
            request("POST", url, body=chunk, token=token)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:800]
            print(f"\nHTTP {error.code} {error.reason} on chunk starting at {start}\n{detail}", file=sys.stderr)
            raise SystemExit(1)
        total_sent += len(chunk)
        print(f"  sent {total_sent}/{len(dtos)} property rows...")
    return total_sent


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", type=int, metavar="N", help="Only process the first N samples, do not require confirmation")
    group.add_argument("--commit", action="store_true", help="Process all samples and write to LithoSurfer")
    args = parser.parse_args()

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target data package: {DATA_PACKAGE_ID}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    combos = load_combos()
    combo_map = load_combo_map(limit=args.dry_run)
    print(f"\nLoaded {len(combos)} combo definitions, {len(combo_map)} sample rows to process.")

    print("Fetching existing samples in the target package to resolve ids...")
    label_to_id = fetch_existing_sample_labels(host, token)
    print(f"Found {len(label_to_id)} existing samples in package {DATA_PACKAGE_ID}.")

    dtos, unmatched = build_property_dtos(combo_map, combos, label_to_id)

    print(f"\nMatched {len(combo_map) - len(unmatched)} samples ({len(dtos)} property rows to send).")
    if unmatched:
        print(f"WARNING: {len(unmatched)} sample names had no matching sample in the package, e.g.: {unmatched[:5]}", file=sys.stderr)

    if not dtos:
        print("Nothing to send.")
        return 0

    print(f"\nSending {len(dtos)} SampleProperty rows in chunks of {CHUNK_SIZE}...")
    sent = send_batches(host, token, dtos)
    print(f"\nDone. Sent {sent} property rows across {len(combo_map) - len(unmatched)} samples.")
    if args.dry_run:
        print("(dry run - re-run with --commit for the full load)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
