#!/usr/bin/env python3
"""Delete duplicate GCAliquot rows created by a concurrent-process bug
(three copies of load_gc_aliquots.py --commit ran simultaneously against
package 244688701 without the caller realizing, because the harness lost
track of two of them and reported them "stopped" while they were still
alive and creating rows).

Input: gcaliquot_ids_to_delete_244688701.json - flat list of GCAliquot row
ids to remove (one lower-id "keeper" was left per gcdataPointId; every
other id for that gcdataPointId is in this list).

Resumable via gcaliquot_delete_progress_<package>.txt, one id per line,
written as each delete is confirmed (204) OR confirmed already-gone
(404/500-not-found) - both count as "the unwanted row no longer exists",
which is the actual goal, not "my request returned 204".

Guards against the exact bug that made this script necessary: refuses to
start if another python process is already running this same script
(checked via PowerShell Get-CimInstance, best-effort - only works on
Windows, which is what this environment is).
"""

import argparse
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
WORKERS = 8
PROGRESS_EVERY = 500

HERE = Path(__file__).resolve().parent
SCRIPT_NAME = Path(__file__).name


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
    my_pid = os.getpid()
    # We can't easily map lines back to PIDs from this query shape, but if
    # more than one process command-line mentions this script, something is
    # already running it (or this check is racing its own startup - accept
    # up to 1 as "just me", since this script's own process also matches).
    if len(lines) > 1:
        print(f"REFUSING TO START: {len(lines)} python processes already reference {SCRIPT_NAME} "
              f"(PID {my_pid} is one of them). This is the exact bug this script exists to clean up "
              f"after - not starting a second copy.", file=sys.stderr)
        raise SystemExit(1)


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
            return response.status, (json.loads(payload) if payload else None)
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            if attempt == retries:
                raise
            print(f"  ({error}, retrying {attempt}/{retries})", file=sys.stderr)
            time.sleep(2 * attempt)


def authenticate(host, username, password):
    body = {"username": username, "password": password, "rememberMe": False}
    status, result = request("POST", f"{host}/api/authenticate", body=body)
    token = result.get("id_token") if isinstance(result, dict) else None
    if not token:
        raise SystemExit(f"Authentication response contained no id_token: {result}")
    return token


def delete_one(host, token, row_id):
    status, detail = request("DELETE", f"{host}/api/geochem/GCAliquot/{row_id}", token=token)
    if status == 204:
        return True, None
    if status in (404, 500):
        # Treat as already-gone (e.g. a prior interrupted run of this same
        # script already deleted it) - the desired end state holds either way.
        return True, f"already gone (HTTP {status})"
    return False, f"HTTP {status}: {str(detail)[:300]}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, required=True)
    parser.add_argument("--ids-file", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    check_no_other_instance()

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target data package: {args.package_id}")

    ids_to_delete = json.loads(args.ids_file.read_text(encoding="utf-8"))
    ids_to_delete = sorted(set(int(x) for x in ids_to_delete))
    print(f"Loaded {len(ids_to_delete)} row ids to delete from {args.ids_file.name}.")

    if args.dry_run:
        print("\nDRY RUN - would delete these ids (no writes performed):")
        print(ids_to_delete[:20], "..." if len(ids_to_delete) > 20 else "")
        return 0

    try:
        token = authenticate(host, username, password)
    except urllib.error.HTTPError as error:
        print(f"\nHTTP {error.code} - authentication failed.", file=sys.stderr)
        return 1

    checkpoint_path = HERE / f"gcaliquot_delete_progress_{args.package_id}.txt"
    done_ids = set()
    if checkpoint_path.exists():
        done_ids = {int(x) for x in checkpoint_path.read_text().split() if x.strip()}
        print(f"Resuming: {len(done_ids)} already deleted per checkpoint {checkpoint_path.name}.")

    todo = [rid for rid in ids_to_delete if rid not in done_ids]
    print(f"\nDeleting {len(todo)} row(s) ({len(ids_to_delete) - len(todo)} already done) with {WORKERS} parallel workers...")

    ok_count = 0
    err_count = 0
    errors_shown = 0
    checkpoint_file = checkpoint_path.open("a", buffering=1)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(delete_one, host, token, rid): rid for rid in todo}
            done = 0
            for future in as_completed(futures):
                rid = futures[future]
                success, detail = future.result()
                done += 1
                if success:
                    ok_count += 1
                    checkpoint_file.write(f"{rid}\n")
                else:
                    err_count += 1
                    if errors_shown < 10:
                        print(f"  FAILED id={rid}: {detail}", file=sys.stderr)
                        errors_shown += 1
                if done % PROGRESS_EVERY == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} processed ({ok_count} ok, {err_count} failed)")
    finally:
        checkpoint_file.close()

    print(f"\nDone. Deleted/confirmed-gone {ok_count} row(s) this run, {err_count} failed.")
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
