#!/usr/bin/env python3
"""One-off cleanup: remove duplicate SampleProperty rows created because a
--dry-run N was always run before --commit for each package, and --commit
re-processes the whole CSV from the top (no skip), so the first N samples
in each package got their properties sent twice via the create-only
/api/core/SampleProperty/batch endpoint.

For each (package, [affected sample labels]) below: resolve the sample
id, fetch its SampleProperty rows, group by (propName, propValue), and
delete all but the lowest id in each group.
"""

import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_HOST = "https://app.ausgeochem.org"
TIMEOUT = 60

AFFECTED = {
    205700763: ["9224519//AA", "9224124//AA", "9222094//AA", "9224241//AA", "9220686//AA"],
    205700765: ["8783174//AA", "8781550//AA", "8786097//AA", "8788300//AA", "8784849//AA"],
    205700764: ["9225477//AA", "9225478//AA", "9225479//AA", "9225480//AA", "9225481//AA"],
    205700762: ["9227542//AA", "9227248//AA", "9227732//AA", "9227039//AA", "9227547//AA"],
}


def load_dotenv() -> None:
    env_file = Path.cwd() / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if value:
            os.environ.setdefault(key.strip(), value)


def request(method: str, url: str, body=None, token=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else None


def authenticate(host, username, password):
    body = {"username": username, "password": password, "rememberMe": False}
    result = request("POST", f"{host}/api/authenticate", body=body)
    return result["id_token"]


def main():
    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST).rstrip("/")
    username = os.environ.get("LITHOSURFER_USER") or input("LithoSurfer user: ").strip()
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")
    token = authenticate(host, username, password)

    total_deleted = 0
    total_checked = 0
    for package_id, labels in AFFECTED.items():
        print(f"\nPackage {package_id}:")
        for label in labels:
            total_checked += 1
            body = {"dataPackageId": {"equals": package_id}, "name": {"contains": label}}
            samples = request("POST", f"{host}/api/core/sample-with-locations/post?page=0&size=5", body=body, token=token)
            sample = next((s for s in samples if s["sampleDTO"]["name"].split(r"\\", 1)[0] == label), None)
            if sample is None:
                print(f"  WARNING: could not find sample for label {label}", file=sys.stderr)
                continue
            sample_id = sample["sampleDTO"]["id"]

            props = request("POST", f"{host}/api/core/SampleProperty/post?page=0&size=50",
                             body={"sampleId": {"equals": sample_id}}, token=token) or []

            groups = {}
            for p in props:
                key = (p.get("propName"), p.get("propValue"))
                groups.setdefault(key, []).append(p["id"])

            deleted_here = 0
            for key, ids in groups.items():
                ids.sort()
                for dup_id in ids[1:]:
                    request("DELETE", f"{host}/api/core/SampleProperty/{dup_id}", token=token)
                    deleted_here += 1
                    total_deleted += 1
            print(f"  {label} (sample {sample_id}): {len(props)} rows -> deleted {deleted_here} duplicate(s)")

    print(f"\nChecked {total_checked} samples, deleted {total_deleted} duplicate property rows.")


if __name__ == "__main__":
    main()
