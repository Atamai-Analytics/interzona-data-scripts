#!/usr/bin/env python3
"""Load Samples (+ nested Locations) for LithoSurfer data package 246454433
("Resources Victoria: Soil Samples") from victoria_soil_samples.tsv,
extracted from criticialmineralsexp samples/locations (all 6 SOIL-category
sample_type_ids for datasource='Resources Victoria', scoped to samples that
have at least one active analytical_results row - see
extract_victoria_soil_samples.R), via POST /api/core/sample-with-locations/batch.

Constants confirmed for this dataset:
  sampleKindId   = 60959     ("Soil")
  locationKindId = 206538051 ("Regolith Sample Site")

sampleMethodId is resolved per row from the method_code column (derived from
samples.sampletypelocal) via METHOD_ID_MAP, confirmed with user:
  UNK1                -> Unknown           (61209)
  AUGE1, HAUG1, MAUG1  -> Auger             (287851)
  SHOV1, BULK1, LAG1   -> Grab              (61205)
  MAG1, SEL1           -> Other             (61201)

materialId is omitted (left null) - unlike Finland Rock, this source data
has no material/lithology field for soil samples, and no generic "Soil"
material entry exists in LithoSurfer's materials list to fall back to.
SampleDTO has no enforced required-fields list (confirmed via swagger), and
Finland Rock already established the precedent of omitting a field
(archiveId) this way.

Naming: label = samplenumber (verified 100% unique across the full scope -
132,210/132,210 - no merged-name reconciliation needed), full name = label
+ "\\\\" + session-id, per batch-create rules.

--dry-run does NOT write anything (only resolves matches and prints what
would be sent). Only --commit performs network writes, chunked and
checkpointed by label (resumable across restarts), using the same
diff-and-retry-confirmed-names pattern as load_finland_samples.py (this
endpoint DOES return a {name: id} map we can verify against, unlike the
concentration endpoints).

Usage:
    python load_victoria_soil_samples.py --dry-run 5
    python load_victoria_soil_samples.py --commit
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
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 60
CHUNK_SIZE = 2000
NAME_SEP = r"\\"

DATA_PACKAGE_ID = 246454433
SAMPLE_KIND_ID = 60959
LOCATION_KIND_ID = 206538051

METHOD_ID_MAP = {
    "UNK1": 61209,   # Unknown
    "AUGE1": 287851,  # Auger
    "HAUG1": 287851,  # Auger
    "MAUG1": 287851,  # Auger
    "SHOV1": 61205,   # Grab
    "BULK1": 61205,   # Grab
    "LAG1": 61205,    # Grab
    "MAG1": 61201,    # Other
    "SEL1": 61201,    # Other
}

HERE = Path(__file__).resolve().parent
TSV_PATH = HERE / "victoria_soil_samples.tsv"


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


def load_rows(limit=None):
    rows = []
    with TSV_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def build_dto(row, session_id):
    label = row["sampleName"]
    method_id = METHOD_ID_MAP.get(row["method_code"])
    sample_date = row["sampledate"] or None

    sample_dto = {
        "id": None,
        "name": f"{label}{NAME_SEP}{session_id}",
        "dataPackageId": DATA_PACKAGE_ID,
        "sampleKindId": SAMPLE_KIND_ID,
        "sampleMethodId": method_id,
        "locationKindId": LOCATION_KIND_ID,
        "materialId": None,
        "collectDateMin": sample_date,
        "collectDateMax": sample_date,
        "description": row["sampleComment"] or None,
    }

    location_dto = {
        "id": None,
        "name": row["locationName"] or None,
        "lat": float(row["latitude"]) if row["latitude"] else None,
        "lon": float(row["longitude"]) if row["longitude"] else None,
    }

    return {
        "id": None,
        "sampleDTO": sample_dto,
        "locationDTO": location_dto,
    }


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", type=int, metavar="N")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    base_session_id = f"{date.today():%Y%m%d}-victoria"
    session_id = f"{base_session_id}-dryruntest" if args.dry_run else base_session_id

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target data package: {DATA_PACKAGE_ID}")
    print(f"Session id: {session_id}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    rows = load_rows(limit=args.dry_run)
    print(f"Loaded {len(rows)} sample rows from {TSV_PATH.name}.")

    dtos = []
    labels = []
    unmatched_method = []
    for row in rows:
        if row["method_code"] not in METHOD_ID_MAP:
            unmatched_method.append(row["method_code"])
            continue
        dtos.append(build_dto(row, session_id))
        labels.append(row["sampleName"])

    if unmatched_method:
        print(f"WARNING: {len(unmatched_method)} rows had unrecognised method_code: {sorted(set(unmatched_method))[:10]}", file=sys.stderr)

    if args.dry_run:
        print(f"\nDRY RUN - would create {len(dtos)} Sample(s) (no writes performed):")
        for dto in dtos:
            print(f"  {dto}")
        print("\n(dry run only validates construction - re-run with --commit to actually write)")
        return 0

    checkpoint_path = HERE / "victoria_sample_progress.txt"
    done_labels = set()
    if checkpoint_path.exists():
        done_labels = {x for x in checkpoint_path.read_text().splitlines() if x.strip()}
        print(f"Resuming: {len(done_labels)} labels already created per checkpoint {checkpoint_path.name}.")

    todo = [(dto, label) for dto, label in zip(dtos, labels) if label not in done_labels]
    print(f"\nSending {len(todo)} Sample(s) ({len(dtos) - len(todo)} already done) in chunks of {CHUNK_SIZE}...")

    def send_chunk(chunk, chunk_labels, chunk_dto_by_label):
        """POST one chunk and verify the batch response actually confirms
        every label - a batch call can return HTTP 200 while silently
        dropping individual rows (confirmed empirically on the Finland
        sample load). Returns (confirmed_labels, missing_labels)."""
        url = f"{host}/api/core/sample-with-locations/batch"
        try:
            result = request("POST", url, body=chunk, token=token)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:800]
            print(f"\nHTTP {error.code} {error.reason} on a chunk\n{detail}", file=sys.stderr)
            raise SystemExit(1)
        returned_names = set(result.keys()) if isinstance(result, dict) else set()
        confirmed, missing = [], []
        for label in chunk_labels:
            full_name = chunk_dto_by_label[label]["sampleDTO"]["name"]
            (confirmed if full_name in returned_names else missing).append(label)
        return confirmed, missing

    checkpoint_file = checkpoint_path.open("a", buffering=1)
    total_sent = 0
    unresolved = []
    try:
        for start in range(0, len(todo), CHUNK_SIZE):
            chunk = [d for d, _ in todo[start:start + CHUNK_SIZE]]
            chunk_labels = [l for _, l in todo[start:start + CHUNK_SIZE]]
            dto_by_label = {l: d for d, l in zip(chunk, chunk_labels)}

            confirmed, missing = send_chunk(chunk, chunk_labels, dto_by_label)
            if missing:
                print(f"  WARNING: {len(missing)} label(s) not confirmed in batch response, retrying individually: {missing[:5]}", file=sys.stderr)
                retry_chunk = [dto_by_label[l] for l in missing]
                confirmed2, still_missing = send_chunk(retry_chunk, missing, dto_by_label)
                confirmed += confirmed2
                unresolved += still_missing

            for label in confirmed:
                checkpoint_file.write(f"{label}\n")
            total_sent += len(confirmed)
            print(f"  sent {total_sent}/{len(todo)} samples...")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Sent {total_sent} Sample(s) this run.")
    if unresolved:
        print(f"WARNING: {len(unresolved)} label(s) still unconfirmed after retry: {unresolved}", file=sys.stderr)
        print("These were NOT checkpointed - re-run this script to try them again.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
