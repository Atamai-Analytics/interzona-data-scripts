#!/usr/bin/env python3
"""[COPY for the 375 DUPLICATE$=D rock samples - see make_finland_flagD375_inputs.py]
Load Samples (+ nested Locations) for LithoSurfer data package 244688701
("GTK: Finland Rock Samples") from finland_samples.tsv, extracted from
criticialmineralsexp.lithodat_samples, via
POST /api/core/sample-with-locations/batch.

Constants confirmed for this dataset (100% consistent across all 6,054 rows):
  sampleKindId    = 60963   ("Rock")
  sampleMethodId  = 290801  ("Hand Sample")
  locationKindId  = 60556   ("Outcrop location")

materialId resolved per row via finland_material_ids.json (57 distinct
values, all confirmed to exist in the materials taxonomy).

archiveId is omitted - source lastKnownArchive was set to null (no
"Geological Survey of Finland" archive entry was created).

One Location per sample (not deduplicated by locationName) - verified that
samples sharing the same locationName have distinct lat/lon (locationName
is a map-sheet/regional label, not a shared physical point).

collectDateMin/Max reformatted from source DD.MM.YYYY to YYYY-MM-DD.

Naming: label = sampleName as-is (already includes "//AA" suffix from
source), full name = label + "\\\\" + session-id, per batch-create rules.

--dry-run does NOT write anything (only resolves matches and prints what
would be sent). Only --commit performs network writes, chunked and
checkpointed by label (resumable across restarts, same design as the other
loaders in this folder).

Usage:
    python load_finland_samples.py --dry-run 5
    python load_finland_samples.py --commit
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
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 60
CHUNK_SIZE = 2000
NAME_SEP = r"\\"

DATA_PACKAGE_ID = 244688701
SAMPLE_KIND_ID = 60963
SAMPLE_METHOD_ID = 290801
LOCATION_KIND_ID = 60556  # unused here: see LOCATION_KIND_BY_SAMTYPE
LOCATION_KIND_BY_SAMTYPE = {"P": 60556, "L": 287903, "R": 60551}  # P outcrop; L boulder -> Boulder; R block field -> Other

HERE = Path(__file__).resolve().parent
TSV_PATH = HERE / "finland_samples_flagD375.tsv"
MATERIAL_MAP_PATH = HERE / "finland_material_ids.json"


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


def reformat_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def load_rows(limit=None):
    rows = []
    with TSV_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def build_dto(row, material_ids, session_id):
    label = row["sampleName"]
    material_id = material_ids.get(row["material"])

    sample_dto = {
        "id": None,
        "name": f"{label}{NAME_SEP}{session_id}",
        "dataPackageId": DATA_PACKAGE_ID,
        "sampleKindId": SAMPLE_KIND_ID,
        "sampleMethodId": SAMPLE_METHOD_ID,
        "locationKindId": LOCATION_KIND_BY_SAMTYPE[row["src_samtype"]],
        "materialId": material_id,
        "collectDateMin": reformat_date(row["collectDateMin"]),
        "collectDateMax": reformat_date(row["collectDateMax"]),
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

    base_session_id = f"{date.today():%Y%m%d}-finland-flagD375"
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

    material_ids = json.loads(MATERIAL_MAP_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(material_ids)} material reference ids.")

    rows = load_rows(limit=args.dry_run)
    print(f"Loaded {len(rows)} sample rows from {TSV_PATH.name}.")

    dtos = []
    labels = []
    unmatched_material = []
    for row in rows:
        if row["material"] not in material_ids:
            unmatched_material.append(row["material"])
            continue
        dtos.append(build_dto(row, material_ids, session_id))
        labels.append(row["sampleName"])

    if unmatched_material:
        print(f"WARNING: {len(unmatched_material)} rows had unrecognised material: {sorted(set(unmatched_material))[:10]}", file=sys.stderr)

    if args.dry_run:
        print(f"\nDRY RUN - would create {len(dtos)} Sample(s) (no writes performed):")
        for dto in dtos:
            print(f"  {dto}")
        print("\n(dry run only validates construction - re-run with --commit to actually write)")
        return 0

    checkpoint_path = HERE / "finland_flagD375_sample_progress.txt"
    done_labels = set()
    if checkpoint_path.exists():
        done_labels = {x for x in checkpoint_path.read_text().splitlines() if x.strip()}
        print(f"Resuming: {len(done_labels)} labels already created per checkpoint {checkpoint_path.name}.")

    todo = [(dto, label) for dto, label in zip(dtos, labels) if label not in done_labels]
    print(f"\nSending {len(todo)} Sample(s) ({len(dtos) - len(todo)} already done) in chunks of {CHUNK_SIZE}...")

    def send_chunk(chunk, chunk_labels, chunk_dto_by_label):
        """POST one chunk and verify the batch response actually confirms
        every label - a batch call can return HTTP 200 while silently
        dropping individual rows (confirmed empirically: sample
        8155272//AA was checkpointed as created by the original run but
        was never actually in the package). Returns (confirmed_labels,
        missing_labels)."""
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
