#!/usr/bin/env python3
"""Load SampleProperty rows into a LithoSurfer data package from a
long-format TSV export of criticialmineralsexp.lithodat_sample_properties2
(sampleName, propname, propvalue - one row per fact, unlike the combo-based
load_sample_properties.py this does NOT pivot per sample, because some
propnames (e.g. "fieldid" on Rock/Stream) are genuinely multi-valued per
sample - a single sample can have several distinct fieldid values (verified:
real, meaningful data - e.g. sequential ranges suggesting a composite
sample spanning multiple original field-collected pieces). SampleProperty
has no uniqueness constraint, so multiple rows with the same propName per
sample is a supported, correct pattern here.

--dry-run does NOT write anything (only resolves matches and prints what
would be sent).

Resumable: since this source has no natural row id, the checkpoint key is
the (sampleName, propname, propvalue) tuple itself - each such row is a
distinct fact that should be created exactly once.

Usage:
    python load_sample_properties2.py --package-id 205700763 --tsv sampleprop2_rock.tsv --dry-run 5
    python load_sample_properties2.py --package-id 205700763 --tsv sampleprop2_rock.tsv --commit
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

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 60
CHUNK_SIZE = 2000
NAME_SEP = r"\\"

HERE = Path(__file__).resolve().parent


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


def fetch_existing_sample_labels(host: str, token: str, package_id: int) -> dict:
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
            labels[label] = sample_id
        print(f"  ...fetched page {page} ({len(labels)} samples so far)")
        if len(batch) < size:
            break
        page += 1
    return labels


def load_rows(tsv_path: Path, limit=None):
    rows = []
    with tsv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", type=int, metavar="N")
    group.add_argument("--commit", action="store_true")
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

    rows = load_rows(args.tsv, limit=args.dry_run)
    print(f"\nLoaded {len(rows)} property rows from {args.tsv.name}.")

    print("Fetching existing samples in the target package to resolve ids...")
    label_to_id = fetch_existing_sample_labels(host, token, args.package_id)
    print(f"Found {len(label_to_id)} existing samples in package {args.package_id}.")

    dtos = []
    keys = []
    unmatched = []
    for row in rows:
        sample_id = label_to_id.get(row["sampleName"])
        if sample_id is None:
            unmatched.append(row["sampleName"])
            continue
        dtos.append({
            "id": None,
            "sampleId": sample_id,
            "propName": row["propname"],
            "propValue": row["propvalue"],
        })
        keys.append(f"{row['sampleName']}|{row['propname']}|{row['propvalue']}")

    print(f"\nMatched {len(dtos)}/{len(rows)} rows.")
    if unmatched:
        print(f"WARNING: {len(unmatched)} rows had no matching sample, e.g.: {unmatched[:5]}", file=sys.stderr)

    if args.dry_run:
        print(f"\nDRY RUN - would create {len(dtos)} SampleProperty(s) (no writes performed):")
        for dto in dtos:
            print(f"  {dto}")
        print("\n(dry run only validates matching - re-run with --commit to actually write)")
        return 0

    checkpoint_path = HERE / f"sampleprop2_progress_{args.package_id}.txt"
    done_keys = set()
    if checkpoint_path.exists():
        done_keys = {x for x in checkpoint_path.read_text().splitlines() if x.strip()}
        print(f"Resuming: {len(done_keys)} rows already sent per checkpoint {checkpoint_path.name}.")

    todo_dtos = []
    todo_keys = []
    for dto, key in zip(dtos, keys):
        if key not in done_keys:
            todo_dtos.append(dto)
            todo_keys.append(key)

    print(f"\nSending {len(todo_dtos)} SampleProperty(s) ({len(dtos) - len(todo_dtos)} already done) in chunks of {CHUNK_SIZE}...")

    checkpoint_file = checkpoint_path.open("a", buffering=1)
    total_sent = 0
    try:
        for start in range(0, len(todo_dtos), CHUNK_SIZE):
            chunk = todo_dtos[start:start + CHUNK_SIZE]
            chunk_keys = todo_keys[start:start + CHUNK_SIZE]
            url = f"{host}/api/core/SampleProperty/batch"
            try:
                request("POST", url, body=chunk, token=token)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:800]
                print(f"\nHTTP {error.code} {error.reason} on chunk starting at {start}\n{detail}", file=sys.stderr)
                raise SystemExit(1)
            for key in chunk_keys:
                checkpoint_file.write(f"{key}\n")
            total_sent += len(chunk)
            print(f"  sent {total_sent}/{len(todo_dtos)} rows...")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Sent {total_sent} SampleProperty(s) this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
