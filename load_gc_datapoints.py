#!/usr/bin/env python3
"""Load GCDataPoints (+ wrapping DataPoint) into a LithoSurfer data package
from a TSV export of criticialmineralsexp.geochem_export_header, via
POST /api/geochem/GCDataPoint/batch.

Source TSV columns (tab-separated, one row per distinct datapointName,
already deduplicated/aggregated from the header table - see
gcdp_<package>.tsv alongside this script):

    datapointName  sampleName  digestioncategory  digestionmethod
    sourcemethodcode  sourcemethoddesc  laboratorycode  sampleweightgm
    analysisdate  sourceanalysisid  digestiontempcelsius  digestionnotes
    analyticalSessionID  batchID  mountID  units

"units" is the '/'-joined list of distinct sourceunit values seen for that
datapoint in the source (a data point can carry results in more than one
unit, e.g. majors in % and traces in ppm - GCDataPoint.sourceUnit only
holds one value). Per user direction:
  - single unit  -> sourceUnit = that unit, label = datapointName
  - multiple units -> sourceUnit left blank, label = "datapointName [units]"
    so the mixed-unit information is visible in the name instead.

geochemAnalyticalTypeId is deliberately omitted - no lookup list for it
could be found anywhere in the API (checked the Geochem group exhaustively,
the generic vocabs table, and existing populated GCDataPoint records).

Matching: "sampleName" is the label used when the samples were originally
batch-created in LithoSurfer (i.e. before the "\\\\<session-id>" suffix).
This script fetches all existing samples in the target package and matches
on that label, same as load_sample_properties.py.

Usage:
    python load_gc_datapoints.py --package-id 205700763 \\
        --tsv gcdp_rock.tsv --dry-run 5

    python load_gc_datapoints.py --package-id 205700763 \\
        --tsv gcdp_rock.tsv --commit

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
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 60
NAME_SEP = r"\\"

HERE = Path(__file__).resolve().parent
CHUNK_SIZE = 2000

DIGESTION_CATEGORY_IDS = {
    "Selective / Sequential": 205568700,
    "Fire assay": 205568750,
    "Near-total": 205568800,
    "Unknown": 205568850,
    "Partial": 205568900,
    "Total": 205568950,
    "None (in-situ)": 205569000,
}

DIGESTION_METHOD_IDS = {
    "Weak / Partial Leach": 205569050,
    "Single Acid": 205569100,
    "Other Fusion": 205569150,
    "Sodium Peroxide Fusion": 205569200,
    "Combustion / Thermal": 205569250,
    "No Digestion / In-Situ": 205569300,
    "Sequential / Selective Extraction": 205569350,
    "Solvent Extraction": 205569400,
    "Aqua Regia": 205569450,
    "Four-Acid Digest": 205569500,
    "Other / Unknown": 205569550,
    "Three-Acid Digest": 205569600,
    "Fire Assay": 205569650,
    "Lithium Borate Fusion": 205569700,
}

ANALYTE_MATERIAL_ID = 6        # "Crushed Powder" - constant for this dataset
ANALYSIS_SCALE_ID = 731304     # "Whole Rock" - constant for this dataset


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
            print(f"  ({error}, retrying {attempt}/{retries})", file=sys.stderr)
            time.sleep(2 * attempt)


def authenticate(host, username, password):
    body = {"username": username, "password": password, "rememberMe": False}
    result = request("POST", f"{host}/api/authenticate", body=body)
    token = result.get("id_token") if result else None
    if not token:
        raise SystemExit(f"Authentication response contained no id_token: {result}")
    return token


def sample_label_cache_path(package_id: int) -> Path:
    return HERE / f"sample_labels_{package_id}.json"


def fetch_existing_sample_labels(host: str, token: str, package_id: int) -> dict:
    """Return {label: sampleId} for every sample already in package_id.

    Cached to disk (sample_labels_<package>.json), written after EVERY page
    and resumed by page offset on restart - long fetches in this
    environment have been getting killed mid-run with no visibility into
    progress, so this caches incrementally like the other loaders do.
    """
    cache_path = sample_label_cache_path(package_id)
    size = 500
    labels = {}
    if cache_path.exists():
        labels = json.loads(cache_path.read_text(encoding="utf-8"))
        if labels.get("__complete__"):
            print(f"Loading cached sample label map from {cache_path.name}...")
            del labels["__complete__"]
            return labels
        print(f"Resuming fetch from cached partial map ({len(labels)} samples already fetched).")

    page = len(labels) // size
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
        cache_path.write_text(json.dumps(labels), encoding="utf-8")
        print(f"  ...fetched page {page} ({len(labels)} samples so far)")
        if len(batch) < size:
            break
        page += 1

    labels["__complete__"] = True
    cache_path.write_text(json.dumps(labels), encoding="utf-8")
    del labels["__complete__"]
    print(f"Cached sample label map to {cache_path.name} for reuse.")
    return labels


def to_float(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(s):
    f = to_float(s)
    return int(round(f)) if f is not None else None


def load_rows(tsv_path: Path, limit=None):
    rows = []
    with tsv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def build_dtos(rows, package_id, label_to_sample_id, session_id):
    dtos = []
    unmatched_samples = []
    unknown_digestion = []

    for row in rows:
        sample_label = row["sampleName"]
        sample_id = label_to_sample_id.get(sample_label)
        if sample_id is None:
            unmatched_samples.append(sample_label)
            continue

        dig_cat_name = row["digestioncategory"] or None
        dig_method_name = row["digestionmethod"] or None
        dig_cat_id = DIGESTION_CATEGORY_IDS.get(dig_cat_name) if dig_cat_name else None
        dig_method_id = DIGESTION_METHOD_IDS.get(dig_method_name) if dig_method_name else None
        if dig_cat_name and dig_cat_id is None:
            unknown_digestion.append(("category", dig_cat_name))
        if dig_method_name and dig_method_id is None:
            unknown_digestion.append(("method", dig_method_name))

        units = row["units"] or ""
        multi_unit = "/" in units
        label = f"{row['datapointName']} [{units}]" if multi_unit else row["datapointName"]
        source_unit = None if multi_unit else (units or None)

        data_point_dto = {
            "id": None,
            "name": f"{label}{NAME_SEP}{session_id}",
            "dataPackageId": package_id,
            "sampleId": sample_id,
        }

        gcdata_point_dto = {
            "id": None,
            "digestionCategoryId": dig_cat_id,
            "digestionMethodId": dig_method_id,
            "analyteMaterialId": ANALYTE_MATERIAL_ID,
            "analysisScaleId": ANALYSIS_SCALE_ID,
            "sourceMethodCode": row["sourcemethodcode"] or None,
            "sourceMethodDesc": row["sourcemethoddesc"] or None,
            "laboratoryCode": row["laboratorycode"] or None,
            "sourceUnit": source_unit,
            "sampleWeightGm": to_float(row["sampleweightgm"]),
            "analysisDate": row["analysisdate"] or None,
            "sourceAnalysisId": row["sourceanalysisid"] or None,
            "digestionTempCelsius": to_int(row["digestiontempcelsius"]),
            "digestionNotes": row["digestionnotes"] or None,
            "analyticalSessionID": row["analyticalSessionID"] or None,
            "batchID": row["batchID"] or None,
            "mountID": row["mountID"] or None,
        }

        dtos.append({
            "id": None,
            "dataPointDTO": data_point_dto,
            "gcdataPointDTO": gcdata_point_dto,
        })

    return dtos, unmatched_samples, unknown_digestion


def send_one_batch(host, token, chunk):
    """POST one chunk and verify the response actually confirms every
    name - a batch call can return HTTP 200 while silently dropping
    individual rows (confirmed empirically on the Finland sample load).
    Returns (confirmed_dtos, missing_dtos)."""
    try:
        result = request("POST", f"{host}/api/geochem/GCDataPoint/batch", body=chunk, token=token)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:800]
        print(f"\nHTTP {error.code} {error.reason} on a chunk\n{detail}", file=sys.stderr)
        raise SystemExit(1)
    returned_names = set(result.keys()) if isinstance(result, dict) else set()
    confirmed, missing = [], []
    for dto in chunk:
        (confirmed if dto["dataPointDTO"]["name"] in returned_names else missing).append(dto)
    return confirmed, missing


def checkpoint_path(package_id: int) -> Path:
    return HERE / f"gcdp_progress_{package_id}.txt"


def send_batches(host, token, dtos, package_id):
    """Send dtos in chunks, checkpointed by dataPointDTO name so a killed
    run can resume without resending already-confirmed data points (a real
    risk at this scale in an environment that has repeatedly killed
    long-running background processes)."""
    cp_path = checkpoint_path(package_id)
    done_names = set()
    if cp_path.exists():
        done_names = {x for x in cp_path.read_text().splitlines() if x.strip()}
        print(f"Resuming: {len(done_names)} data points already sent per checkpoint {cp_path.name}.")

    todo = [d for d in dtos if d["dataPointDTO"]["name"] not in done_names]
    print(f"\nSending {len(todo)} GCDataPoint(s) ({len(dtos) - len(todo)} already done) in chunks of {CHUNK_SIZE}...")

    total_sent = 0
    unresolved = []
    cp_file = cp_path.open("a", buffering=1)
    try:
        for start in range(0, len(todo), CHUNK_SIZE):
            chunk = todo[start:start + CHUNK_SIZE]
            confirmed, missing = send_one_batch(host, token, chunk)
            if missing:
                print(f"  WARNING: {len(missing)} name(s) not confirmed in batch response, retrying individually: {[d['dataPointDTO']['name'] for d in missing[:5]]}", file=sys.stderr)
                confirmed2, still_missing = send_one_batch(host, token, missing)
                confirmed += confirmed2
                unresolved += still_missing
            for d in confirmed:
                cp_file.write(f"{d['dataPointDTO']['name']}\n")
            total_sent += len(confirmed)
            print(f"  sent {total_sent}/{len(todo)} data points... ({len(confirmed)} confirmed in this chunk)")
    finally:
        cp_file.close()
    if unresolved:
        print(f"\nWARNING: {len(unresolved)} data point(s) still unconfirmed after retry: {[d['dataPointDTO']['name'] for d in unresolved]}", file=sys.stderr)
        print("These were NOT checkpointed - re-run this script to try them again.", file=sys.stderr)
    return total_sent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", type=int, metavar="N")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    base_session_id = f"{date.today():%Y%m%d}-gcdp"
    session_id = f"{base_session_id}-dryruntest" if args.dry_run else base_session_id

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target data package: {args.package_id}")
    print(f"Session id: {session_id}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    rows = load_rows(args.tsv, limit=args.dry_run)
    print(f"\nLoaded {len(rows)} data-point rows from {args.tsv.name}.")

    print("Fetching existing samples in the target package to resolve ids...")
    label_to_id = fetch_existing_sample_labels(host, token, args.package_id)
    print(f"Found {len(label_to_id)} existing samples in package {args.package_id}.")

    dtos, unmatched, unknown_dig = build_dtos(rows, args.package_id, label_to_id, session_id)

    print(f"\nMatched {len(dtos)}/{len(rows)} data points to existing samples.")
    if unmatched:
        print(f"WARNING: {len(unmatched)} rows had no matching sample, e.g.: {unmatched[:5]}", file=sys.stderr)
    if unknown_dig:
        uniq = sorted(set(unknown_dig))
        print(f"WARNING: {len(uniq)} unrecognised digestion category/method names: {uniq[:10]}", file=sys.stderr)

    if args.dry_run:
        print(f"\nDRY RUN - would create {len(dtos)} GCDataPoint(s) (no writes performed):")
        for dto in dtos:
            print(f"  {dto}")
        print("\n(dry run only validates matching - re-run with --commit to actually write)")
        return 0

    if not dtos:
        print("Nothing to send.")
        return 0

    sent = send_batches(host, token, dtos, args.package_id)
    print(f"\nDone. Sent {sent} data points.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
