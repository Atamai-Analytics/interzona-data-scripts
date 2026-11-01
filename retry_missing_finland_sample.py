#!/usr/bin/env python3
"""One-off retry to create the single Finland Rock sample that was silently
dropped by the original batch load (8155272//AA) - see conversation notes.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME_SEP = r"\\"
TIMEOUT = 60


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
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else None


load_dotenv()
host = os.environ.get("LITHOSURFER_HOST").rstrip("/")
username = os.environ["LITHOSURFER_USER"]
password = os.environ["LITHOSURFER_PASSWORD"]

body = {"username": username, "password": password, "rememberMe": False}
result = request("POST", f"{host}/api/authenticate", body=body)
token = result["id_token"]

session_id = "20260901-finland-retry"
label = "8155272//AA"

dto = {
    "id": None,
    "sampleDTO": {
        "id": None,
        "name": f"{label}{NAME_SEP}{session_id}",
        "dataPackageId": 244688701,
        "sampleKindId": 60963,
        "sampleMethodId": 290801,
        "locationKindId": 60556,
        "materialId": 108036,
        "collectDateMin": "1991-09-03",
        "collectDateMax": "1992-09-01",
        "description": None,
    },
    "locationDTO": {
        "id": None,
        "name": "MAP100: 1232 & MAP20: 08",
        "lat": 62.22511836738379,
        "lon": 21.52357080871841,
    },
}
print("payload name:", repr(dto["sampleDTO"]["name"]))

try:
    res = request("POST", f"{host}/api/core/sample-with-locations/batch", body=[dto], token=token)
    print("SUCCESS:", json.dumps(res, indent=2)[:1500])
except urllib.error.HTTPError as e:
    print("FAILED", e.code, e.read().decode("utf-8", "replace")[:1500])
