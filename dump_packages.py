#!/usr/bin/env python3
"""Dump every WRITEABLE data package (full DTO incl. description) to JSON.

Usage: python dump_packages.py <out.json> [<id> ...]
With ids: also GET /api/management/data-packages/{id} for each and store it.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


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


def request(method, url, body=None, token=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = r.read().decode("utf-8")
    return json.loads(payload) if payload else None


def main():
    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io")
    tok = request("POST", f"{host}/api/authenticate", body={
        "username": os.environ["LITHOSURFER_USER"],
        "password": os.environ["LITHOSURFER_PASSWORD"],
        "rememberMe": False})["id_token"]
    out = {"writable": request(
        "GET", f"{host}/api/management/litho-users/accessibledataPackages?allowedAccess=WRITEABLE", token=tok)}
    out["full"] = {}
    for pid in sys.argv[2:]:
        out["full"][pid] = request("GET", f"{host}/api/management/data-packages/{pid}", token=tok)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    pk = out["writable"]
    print(f"{len(pk)} writable packages")
    for p in pk if isinstance(pk, list) else []:
        print(p.get("id"), "|", p.get("name"))


if __name__ == "__main__":
    main()
