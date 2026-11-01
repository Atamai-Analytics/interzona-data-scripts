#!/usr/bin/env python3
"""Apply the reviewed package descriptions / licence texts to LithoSurfer.

Reads package_descriptions_draft.md: every "### description <id>" or
"### license <id>" heading followed by a ```text fenced block.

DRY RUN BY DEFAULT - prints current vs new text and lengths, writes nothing.
--commit      PUT the changes (one package at a time, stops on the first failure)
--ids a,b,c   restrict to these package ids
--only        description | license   (default: both, if present in the md)

PUT /api/management/data-packages is a FULL replace (DataPackageLithoDTO), so
the body is built from the package's own current GET response - every
property the DTO defines is carried over unchanged except the one being edited.
Before any write the current values are saved to
package_text_backup_<timestamp>.json so each change can be reverted.
After each write the package is read back and compared to what was sent.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
MD = HERE / "package_descriptions_draft.md"


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
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                payload = r.read().decode("utf-8")
            return json.loads(payload) if payload else None
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < 4:
                time.sleep(3 * attempt)
                continue
            raise


def parse_md():
    text = MD.read_text(encoding="utf-8")
    pat = re.compile(r"^### (description|license) (\d+)\s*\n```text\n(.*?)\n```", re.S | re.M)
    out = {}
    for kind, pid, body in pat.findall(text):
        out.setdefault(int(pid), {})[kind] = body.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--ids")
    ap.add_argument("--only", choices=("description", "license"))
    args = ap.parse_args()

    wanted = parse_md()
    if args.ids:
        keep = {int(x) for x in args.ids.split(",")}
        wanted = {k: v for k, v in wanted.items() if k in keep}
    if not wanted:
        raise SystemExit("Nothing to apply (no matching blocks in the markdown).")

    load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io")
    token = request("POST", f"{host}/api/authenticate", body={
        "username": os.environ["LITHOSURFER_USER"],
        "password": os.environ["LITHOSURFER_PASSWORD"], "rememberMe": False})["id_token"]

    swagger = request("GET", f"{host}/v2/api-docs?group=" + urllib.parse.quote("02 Management"), token=token)
    dto_props = list(swagger["definitions"]["DataPackageLithoDTO"]["properties"].keys())
    print("DataPackageLithoDTO properties:", dto_props)

    backups, plan = {}, []
    for pid, blocks in sorted(wanted.items()):
        cur = request("GET", f"{host}/api/management/data-packages/{pid}", token=token)
        backups[pid] = {k: cur.get(k) for k in ("name", "description", "licenseText")}
        body = {k: cur.get(k) for k in dto_props if k in cur}
        missing = [k for k in dto_props if k not in cur]
        changes = {}
        if "description" in blocks and args.only in (None, "description"):
            changes["description"] = blocks["description"]
        if "license" in blocks and args.only in (None, "license"):
            changes["licenseText"] = blocks["license"]
        print(f"\n=== {pid} {cur.get('name')}")
        if missing:
            print("   NOTE: DTO properties absent from GET response (not sent):", missing)
        for field, new in changes.items():
            old = cur.get(field) or ""
            print(f"   {field}: {len(old)} chars -> {len(new)} chars" + ("  (UNCHANGED)" if old.strip() == new.strip() else ""))
        body.update(changes)
        # The DTO also carries a nested copy; keep it in step so the server
        # cannot pick up stale text from there.
        if isinstance(body.get("dataPackageDTO"), dict):
            body["dataPackageDTO"] = {**body["dataPackageDTO"], **changes}
        plan.append((pid, body, changes))

    if not args.commit:
        print("\nDRY RUN - nothing written. Re-run with --commit to apply.")
        return 0

    backup_path = HERE / f"package_text_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
    backup_path.write_text(json.dumps(backups, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nBackup of current text written to {backup_path.name}")

    for pid, body, changes in plan:
        try:
            request("PUT", f"{host}/api/management/data-packages", body=body, token=token)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            print(f"FAILED {pid}: HTTP {e.code} {detail}")
            return 1
        back = request("GET", f"{host}/api/management/data-packages/{pid}", token=token)
        for field, new in changes.items():
            ok = (back.get(field) or "").strip() == new.strip()
            print(f"{pid} {field}: {'OK (read back identical)' if ok else 'MISMATCH - stored text differs from what was sent'}")
            if not ok:
                return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
