#!/usr/bin/env python3
"""Load OxideConcentration rows into LithoSurfer via
POST /api/geochem/OxideConcentration/batch.

Source: oxide_<package>.tsv, extracted from
criticialmineralsexp.lithodat_datapoint_concentrations (analysis_group =
'Oxide', excluding element_oxide IN ('FETO3','Sum') per user direction -
FETO3 is "Total Fe as Fe2O3" with no distinct LOxide entry, Sum is a QC
total-check column, not a real oxide). LOI/VOL (analysis_group IS NULL)
are also excluded per user direction.

Columns: result_id, datapointName (= datapointname_merged), aliquotName
(= aliquotname_merged), element_oxide, Conc (already unit-normalised to %
- verified against raw `value`, 0 mismatches), qualifier_code.

Same mapping as ElementalConcentration (confirmed with user):
  qualifier_code == ''   -> concentration = Conc, detectionLimit = null,  relativeOperatorId = null
  qualifier_code == '<'  -> concentration = null, detectionLimit = Conc, relativeOperatorId = 1 ('<')
  qualifier_code == 'ND' -> concentration = null, detectionLimit = Conc (if present, else null),
                            relativeOperatorId = null (no "Not Detected" operator exists)
  unqualified negative Conc (none observed for Oxide, but handled defensively
  the same way as Elements) -> treated as "-1 x detection limit" sentinel.

gcdataPointId resolved via the datapoint_ids_<package>.json cache built
during the GCAliquot load. Resumable via oxideconc_progress_<package>.txt
(result_id checkpoint, same design as load_elemental_concentrations.py).

--dry-run does NOT write anything.

Usage:
    python load_oxide_concentrations.py --package-id 205700763 --tsv oxide_rock.tsv --dry-run 5
    python load_oxide_concentrations.py --package-id 205700763 --tsv oxide_rock.tsv --commit
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

HERE = Path(__file__).resolve().parent

BELOW_DETECTION_LIMIT_ID = 1  # LRelativeOperator: '<'


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


def load_oxide_ids(host, token):
    oxides = request("GET", f"{host}/api/geochem/LOxide?size=500", token=token)
    return {o["name"]: o["id"] for o in oxides}


def load_datapoint_cache(package_id: int) -> dict:
    cache_path = HERE / f"datapoint_ids_{package_id}.json"
    if not cache_path.exists():
        raise SystemExit(f"Missing {cache_path.name} - run load_gc_aliquots.py for this package first.")
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    data.pop("__complete__", None)
    return data


def load_rows(tsv_path: Path, limit=None):
    rows = []
    with tsv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def to_float(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build_dto(row, gc_id, oxide_ids):
    oxide_id = oxide_ids.get(row["element_oxide"])
    conc = to_float(row["Conc"])
    qualifier = (row["qualifier_code"] or "").strip()

    if qualifier == "<":
        concentration, detection_limit, rel_op = None, conc, BELOW_DETECTION_LIMIT_ID
    elif qualifier == "ND":
        concentration, detection_limit, rel_op = None, conc, None
    elif not qualifier and conc is not None and conc < 0:
        concentration, detection_limit, rel_op = None, abs(conc), BELOW_DETECTION_LIMIT_ID
    else:
        concentration, detection_limit, rel_op = conc, None, None

    return {
        "id": None,
        "gcdataPointId": gc_id,
        "aliquotName": row["aliquotName"],
        "oxideId": oxide_id,
        "concentration": concentration,
        "detectionLimit": detection_limit,
        "relativeOperatorId": rel_op,
    }


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

    oxide_ids = load_oxide_ids(host, token)
    print(f"Loaded {len(oxide_ids)} oxide reference ids.")

    label_to_gcid = load_datapoint_cache(args.package_id)
    print(f"Loaded {len(label_to_gcid)} cached data-point ids for package {args.package_id}.")

    rows = load_rows(args.tsv, limit=args.dry_run)
    print(f"Loaded {len(rows)} concentration rows from {args.tsv.name}.")

    unmatched_dp = []
    unmatched_ox = []
    dtos = []
    result_ids = []
    for row in rows:
        gc_id = label_to_gcid.get(row["datapointName"])
        if gc_id is None:
            unmatched_dp.append(row["datapointName"])
            continue
        if row["element_oxide"] not in oxide_ids:
            unmatched_ox.append(row["element_oxide"])
            continue
        dtos.append(build_dto(row, gc_id, oxide_ids))
        result_ids.append(row["result_id"])

    print(f"\nMatched {len(dtos)}/{len(rows)} rows.")
    if unmatched_dp:
        print(f"WARNING: {len(unmatched_dp)} rows had no matching data point, e.g.: {unmatched_dp[:5]}", file=sys.stderr)
    if unmatched_ox:
        print(f"WARNING: {len(unmatched_ox)} rows had unrecognised oxide symbols: {sorted(set(unmatched_ox))[:10]}", file=sys.stderr)

    if args.dry_run:
        print(f"\nDRY RUN - would create {len(dtos)} OxideConcentration(s) (no writes performed):")
        for dto in dtos:
            print(f"  {dto}")
        print("\n(dry run only validates matching - re-run with --commit to actually write)")
        return 0

    checkpoint_path = HERE / f"oxideconc_progress_{args.package_id}.txt"
    done_ids = set()
    if checkpoint_path.exists():
        done_ids = {x for x in checkpoint_path.read_text().split() if x.strip()}
        print(f"Resuming: {len(done_ids)} result_ids already sent per checkpoint {checkpoint_path.name}.")

    todo_dtos = []
    todo_result_ids = []
    for dto, rid in zip(dtos, result_ids):
        if rid not in done_ids:
            todo_dtos.append(dto)
            todo_result_ids.append(rid)

    print(f"\nSending {len(todo_dtos)} OxideConcentration(s) ({len(dtos) - len(todo_dtos)} already done) in chunks of {CHUNK_SIZE}...")

    checkpoint_file = checkpoint_path.open("a", buffering=1)
    total_sent = 0
    try:
        for start in range(0, len(todo_dtos), CHUNK_SIZE):
            chunk = todo_dtos[start:start + CHUNK_SIZE]
            chunk_ids = todo_result_ids[start:start + CHUNK_SIZE]
            url = f"{host}/api/geochem/OxideConcentration/batch"
            try:
                request("POST", url, body=chunk, token=token)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:800]
                print(f"\nHTTP {error.code} {error.reason} on chunk starting at {start}\n{detail}", file=sys.stderr)
                raise SystemExit(1)
            # OxideConcentration rows have no natural unique key in the
            # batch response (unlike GCDataPoint/Sample), and empirically
            # the response also carries no reliable per-chunk count either
            # (confirmed on the Finland Rock ElementalConcentration load,
            # 2026-09-04: every chunk reported len()==0 even though a full
            # post-hoc recount showed 100% of rows had actually landed) -
            # see load_elemental_concentrations.py for the full story. So we
            # don't check the response body at all here; HTTP errors (above)
            # are still a real signal and are not silenced. To verify a
            # completed load, page GCDataPoint for the package and sum
            # countOxideConcentrations - that field reflects the live
            # server-side count and is reliable.
            for rid in chunk_ids:
                checkpoint_file.write(f"{rid}\n")
            total_sent += len(chunk)
            print(f"  sent {total_sent}/{len(todo_dtos)} rows...")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Sent {total_sent} OxideConcentration(s) this run.")
    print("Note: this endpoint's /batch response carries no per-chunk success signal - "
          "verify the load by paging GCDataPoint for this package and summing "
          "countOxideConcentrations (should equal the total rows sent).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
