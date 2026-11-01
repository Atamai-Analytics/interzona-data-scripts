#!/usr/bin/env python3
"""Load sample properties into a LithoSurfer data package from a
comboId-based CSV export of criticialmineralsexp.location_properties_export,
via POST /api/core/SampleProperty/batch.

Generic version of load_rock_sample_properties.py, parameterised by
package id and CSV paths so it can be reused for each GEUS sample type
(rock, stream sediment, soil, heavy mineral concentrate).

Expects two CSV files:
  <combos-csv>   comboId,<propName1>,<propName2>,...  (one row per distinct
                 combination of property values; empty cell = property
                 not written for that combo)
  <map-csv>      sampleName,comboId  (one row per sample)

Matching: "sampleName" is the label used when the samples were originally
batch-created in LithoSurfer, i.e. the part of the stored name before the
"\\\\<session-id>" suffix. This script fetches all existing samples in the
target package and matches on that label.

Usage:
    python load_sample_properties.py --package-id 205700765 \\
        --combos-csv stream_sample_combos.csv \\
        --map-csv stream_sample_combo_map.csv \\
        --dry-run 5

    python load_sample_properties.py --package-id 205700765 \\
        --combos-csv stream_sample_combos.csv \\
        --map-csv stream_sample_combo_map.csv \\
        --commit

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
NAME_SEP = r"\\"  # literal two-backslash label/session-id separator
CHUNK_SIZE = 2000

HERE = Path(__file__).resolve().parent


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


def fetch_existing_sample_labels(host: str, token: str, package_id: int) -> dict:
    """Return {label: sampleId} for every sample already in package_id."""
    labels = {}
    page = 0
    size = 500
    while True:
        url = f"{host}/api/core/sample-with-locations/post?page={page}&size={size}&sort=id,asc"
        body = {"dataPackageId": {"equals": package_id}}
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


def load_combos(path: Path):
    combos = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        prop_names = [c for c in reader.fieldnames if c != "comboId"]
        for row in reader:
            combos[row["comboId"]] = {p: row[p] for p in prop_names if row[p]}
    return combos


def load_combo_map(path: Path, limit=None):
    rows = []
    with path.open(encoding="utf-8") as f:
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
    parser.add_argument("--package-id", type=int, required=True)
    parser.add_argument("--combos-csv", type=Path, required=True)
    parser.add_argument("--map-csv", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", type=int, metavar="N", help="Only process the first N samples")
    group.add_argument("--commit", action="store_true", help="Process all samples and write to LithoSurfer")
    args = parser.parse_args()

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

    combos = load_combos(args.combos_csv)
    combo_map = load_combo_map(args.map_csv, limit=args.dry_run)
    print(f"\nLoaded {len(combos)} combo definitions, {len(combo_map)} sample rows to process.")

    print("Fetching existing samples in the target package to resolve ids...")
    label_to_id = fetch_existing_sample_labels(host, token, args.package_id)
    print(f"Found {len(label_to_id)} existing samples in package {args.package_id}.")

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
