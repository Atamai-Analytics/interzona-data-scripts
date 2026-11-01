#!/usr/bin/env python3
"""Set Sample.originId for every sample in a LithoSurfer data package, via
PUT /api/core/sample-with-locations (single-record update - no batch
update endpoint exists for this entity, confirmed against Swagger).

Mapping confirmed with user:
    Rock Samples (205700763)               -> /InSitu (Rock)          id 3000007
    Stream Sediment Samples (205700765)    -> /Depositional/Fluvial   id 3000001
    Soil Samples (205700764)               -> /Residual               id 3000008
    Heavy Mineral Concentrates (205700762) -> /Depositional/Fluvial   id 3000001

PUT semantics verified via spot-check: sending the full SampleWithLocationDTO
already returned by the search endpoint, with only sampleDTO.originId
changed, updates originId (originName is auto-derived by the API) and
leaves every other field untouched.

Existing-sample DTOs are cached to disk per package (fetch is the slow
part - full pagination, same lesson learned from the GCAliquot load) so a
killed run resumes the fetch instead of restarting it. Updates themselves
are checkpointed by sample id.

--dry-run does NOT write anything - only fetches (or reuses cache) and
prints what would be sent for the first N samples.

Usage:
    python update_sample_origin.py --package-id 205700763 --origin-id 3000007 --dry-run 5
    python update_sample_origin.py --package-id 205700763 --origin-id 3000007 --commit
"""

import argparse
import getpass
import json
import os
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


def request(method, url, body=None, token=None, retries=3):
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


def fetch_samples(host, token, package_id, cache_path):
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("__complete__"):
            print(f"Loading cached samples from {cache_path.name}...")
            return cached["samples"]
        samples = cached.get("samples", [])
        print(f"Resuming fetch from cache ({len(samples)} samples already fetched).")
    else:
        samples = []

    size = 500
    page = len(samples) // size
    while True:
        url = f"{host}/api/core/sample-with-locations/post?page={page}&size={size}&sort=id,asc"
        body = {"dataPackageId": {"equals": package_id}}
        batch = request("POST", url, body=body, token=token) or []
        if not batch:
            break
        samples.extend(batch)
        cache_path.write_text(json.dumps({"samples": samples}), encoding="utf-8")
        print(f"  ...fetched page {page} ({len(samples)} samples so far)")
        if len(batch) < size:
            break
        page += 1

    cache_path.write_text(json.dumps({"samples": samples, "__complete__": True}), encoding="utf-8")
    return samples


def put_one(host, token, sample_dto):
    try:
        request("PUT", f"{host}/api/core/sample-with-locations", body=sample_dto, token=token)
        return True, None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {error.code}: {detail}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, required=True)
    parser.add_argument("--origin-id", type=int, required=True)
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
    print(f"Target package: {args.package_id}")
    print(f"Target originId: {args.origin_id}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    cache_path = HERE / f"sample_dtos_{args.package_id}.json"
    print("\nFetching existing samples (cached, resumable)...")
    samples = fetch_samples(host, token, args.package_id, cache_path)
    print(f"Found {len(samples)} samples in package {args.package_id}.")

    already_set = sum(1 for s in samples if s["sampleDTO"].get("originId") == args.origin_id)
    print(f"{already_set} already have originId={args.origin_id}.")

    if args.dry_run:
        sample_subset = samples[:args.dry_run]
        print(f"\nDRY RUN - would set originId={args.origin_id} on {len(sample_subset)} sample(s) (no writes performed):")
        for s in sample_subset:
            sd = s["sampleDTO"]
            print(f"  id={sd['id']} name={sd['name']!r} current originId={sd.get('originId')}")
        print("\n(dry run only - re-run with --commit to actually write)")
        return 0

    checkpoint_path = HERE / f"origin_update_progress_{args.package_id}.txt"
    done_ids = set()
    if checkpoint_path.exists():
        done_ids = {int(x) for x in checkpoint_path.read_text().split() if x.strip()}
        print(f"Resuming: {len(done_ids)} samples already updated per checkpoint.")

    todo = [s for s in samples if s["sampleDTO"]["id"] not in done_ids and s["sampleDTO"].get("originId") != args.origin_id]
    print(f"\nUpdating {len(todo)} sample(s) with {WORKERS} parallel workers...")

    def apply_and_put(sample):
        sample["sampleDTO"]["originId"] = args.origin_id
        return put_one(host, token, sample)

    checkpoint_file = checkpoint_path.open("a", buffering=1)
    ok_count = 0
    err_count = 0
    errors_shown = 0
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(apply_and_put, s): s["sampleDTO"]["id"] for s in todo}
            done = 0
            for future in as_completed(futures):
                success, err = future.result()
                done += 1
                sample_id = futures[future]
                if success:
                    ok_count += 1
                    checkpoint_file.write(f"{sample_id}\n")
                else:
                    err_count += 1
                    if errors_shown < 10:
                        print(f"  FAILED sample {sample_id}: {err}", file=sys.stderr)
                        errors_shown += 1
                if done % PROGRESS_EVERY == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} processed ({ok_count} ok, {err_count} failed)")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Updated {ok_count} sample(s) this run, {err_count} failed.")
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
