#!/usr/bin/env python3
"""One-off cleanup: remove all Sample/Location and SampleProperty records
from LithoSurfer package 244688701 ("GTK: Finland Rock Samples"), so it can
be reloaded from the rebuilt lithodat_samples view (corrected sampleName
grain).

Deleting a Sample does NOT cascade to its SampleProperty rows (verified) -
they must be deleted explicitly first. SampleProperty has no bulk-delete
endpoint, so each row is deleted individually via a thread pool
(checkpointed, resumable). Samples themselves ARE deleted in one call via
sample-with-locations/deleteByCriteria.

Usage:
    python cleanup_finland_package.py --dry-run   # count only, no writes
    python cleanup_finland_package.py --commit
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
PACKAGE_ID = 244688701
WORKERS = 10
PROGRESS_EVERY = 1000

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


def fetch_sample_ids(host, token):
    ids = []
    page = 0
    size = 500
    while True:
        url = f"{host}/api/core/sample-with-locations/post?page={page}&size={size}&sort=id,asc"
        body = {"dataPackageId": {"equals": PACKAGE_ID}}
        batch = request("POST", url, body=body, token=token) or []
        if not batch:
            break
        for item in batch:
            ids.append(item["sampleDTO"]["id"])
        print(f"  ...fetched sample page {page} ({len(ids)} so far)")
        if len(batch) < size:
            break
        page += 1
    return ids


def fetch_property_ids(host, token, sample_ids):
    prop_ids = []
    chunk_size = 200
    for i in range(0, len(sample_ids), chunk_size):
        chunk = sample_ids[i:i + chunk_size]
        page = 0
        while True:
            url = f"{host}/api/core/SampleProperty/post?page={page}&size=2000"
            body = {"sampleId": {"in": chunk}}
            batch = request("POST", url, body=body, token=token) or []
            prop_ids.extend(p["id"] for p in batch)
            if len(batch) < 2000:
                break
            page += 1
        print(f"  ...fetched properties for {min(i + chunk_size, len(sample_ids))}/{len(sample_ids)} samples ({len(prop_ids)} properties so far)")
    return prop_ids


def delete_one_property(host, token, prop_id):
    try:
        request("DELETE", f"{host}/api/core/SampleProperty/{prop_id}", token=token)
        return True, None
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target package: {PACKAGE_ID}")

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    print("\nFetching sample ids...")
    sample_ids = fetch_sample_ids(host, token)
    print(f"Found {len(sample_ids)} samples.")

    print("\nFetching property ids for those samples...")
    prop_ids = fetch_property_ids(host, token, sample_ids)
    print(f"Found {len(prop_ids)} properties.")

    if args.dry_run:
        print(f"\nDRY RUN - would delete {len(prop_ids)} SampleProperty rows and {len(sample_ids)} Sample/Location records. No writes performed.")
        return 0

    checkpoint_path = HERE / "finland_cleanup_progress.txt"
    done_ids = set()
    if checkpoint_path.exists():
        done_ids = {int(x) for x in checkpoint_path.read_text().split() if x.strip()}
        print(f"Resuming: {len(done_ids)} properties already deleted per checkpoint.")

    todo = [pid for pid in prop_ids if pid not in done_ids]
    print(f"\nDeleting {len(todo)} SampleProperty rows ({len(prop_ids) - len(todo)} already done) with {WORKERS} parallel workers...")

    checkpoint_file = checkpoint_path.open("a", buffering=1)
    ok_count = 0
    err_count = 0
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(delete_one_property, host, token, pid): pid for pid in todo}
            done = 0
            for future in as_completed(futures):
                success, err = future.result()
                done += 1
                if success:
                    ok_count += 1
                    checkpoint_file.write(f"{futures[future]}\n")
                else:
                    err_count += 1
                if done % PROGRESS_EVERY == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} processed ({ok_count} ok, {err_count} failed)")
    finally:
        checkpoint_file.close()

    print(f"\nDeleted {ok_count} properties this run, {err_count} failed.")
    if err_count:
        print("Stopping before sample deletion due to property-delete failures. Re-run to retry.", file=sys.stderr)
        return 1

    print(f"\nAll properties deleted. Bulk-deleting {len(sample_ids)} samples via deleteByCriteria...")
    url = f"{host}/api/core/sample-with-locations/deleteByCriteria?dataPackageId.equals={PACKAGE_ID}"
    try:
        request("DELETE", url, token=token)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:800]
        print(f"HTTP {error.code} {error.reason}\n{detail}", file=sys.stderr)
        return 1

    print("Done. Samples deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
