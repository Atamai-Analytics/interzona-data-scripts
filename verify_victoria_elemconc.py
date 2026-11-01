#!/usr/bin/env python3
"""Ground-truth verification: sum countElementalConcentrations across all
GCDataPoints for the Victoria Soil package, compare against rows sent by
load_elemental_concentrations.py.

Usage: python verify_victoria_elemconc.py
"""
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_HOST = "https://api.lithosurfer.io"
PACKAGE_ID = 246454433
TIMEOUT = 60
PAGE_SIZE = 200


def load_dotenv():
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


def request(method, url, body=None, token=None, retries=6):
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
        except urllib.error.HTTPError as error:
            if error.code in (502, 503, 504) and attempt < retries:
                print(f"  (HTTP {error.code}, retrying {attempt}/{retries})", file=sys.stderr)
                time.sleep(3 * attempt)
                continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
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


def main():
    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", DEFAULT_HOST)
    username = os.environ.get("LITHOSURFER_USER") or input("Username: ")
    password = os.environ.get("LITHOSURFER_PASSWORD") or getpass.getpass("Password: ")

    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Target data package: {PACKAGE_ID}")

    token = authenticate(host, username, password)

    total_datapoints = 0
    total_ec = 0
    total_oc = 0
    n_zero_ec = 0
    page = 0
    while True:
        url = (
            f"{host}/api/geochem/GCDataPoint?dataPointLithoCriteria.dataPackageId.equals={PACKAGE_ID}"
            f"&page={page}&size={PAGE_SIZE}&sort=id,desc"
        )
        batch = request("GET", url, token=token)
        if not batch:
            break
        for dp in batch:
            total_datapoints += 1
            ec = dp.get("countElementalConcentrations") or 0
            oc = dp.get("countOxideConcentrations") or 0
            total_ec += ec
            total_oc += oc
            if ec == 0:
                n_zero_ec += 1
        if page % 20 == 0:
            print(f"page {page}: {total_datapoints} datapoints so far, total_ec={total_ec}, n_zero_ec={n_zero_ec}", flush=True)
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    print(f"FINAL: {total_datapoints} datapoints, total_ec={total_ec}, total_oc={total_oc}, n_zero_ec={n_zero_ec}")


if __name__ == "__main__":
    sys.exit(main())
