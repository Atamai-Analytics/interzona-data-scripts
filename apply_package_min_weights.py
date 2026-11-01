#!/usr/bin/env python3
"""Back-populate criticialmineralsexp.analytical_packages.minimumsampleweight
(grams) from an audit CSV (package_charge_weights_applied.csv by default).

DRY RUN BY DEFAULT: runs read-only pre-checks and prints what would change.
--commit : backs up the target rows to CSV, then UPDATEs in ONE transaction.

Safety:
  * only rows where minimumsampleweight IS NULL are touched (existing values -
    e.g. the GTK packages - are never overwritten)
  * a row only matches if BOTH package_id and package_code agree with the CSV
  * sets minimumsampleweightunit = 'g'; leaves recommendedsampleweight alone
  * modified_by = 'claude_charge_20261003', modified_date = now()
  * the transaction is rolled back unless the number of updated rows equals the
    number of CSV rows that matched in the pre-check
Uses psql (QGIS bundle) with the LITHODAT_DB_* variables from .env.
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PSQL = r"C:\Program Files\QGIS 4.0.1\bin\psql.exe"
TAG = "claude_charge_20261003"


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


def psql(sql, extra=()):
    env = dict(os.environ, PGPASSWORD=os.environ["LITHODAT_DB_PASSWORD"])
    cmd = [PSQL, "-h", os.environ.get("LITHODAT_DB_HOST", "localhost"), "-p", os.environ.get("LITHODAT_DB_PORT", "5432"),
           "-U", os.environ["LITHODAT_DB_USER"], "-d", os.environ.get("LITHODAT_DB_NAME", "criticialmineralsexp"),
           "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", *extra, "-c", sql]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"psql failed: {r.stderr.strip()}")
    return r.stdout.strip()


def values_clause(rows):
    return ",".join(f"({int(r['package_id'])},'{r['package_code'].replace(chr(39), chr(39)*2)}',{float(r['weight_g'])})" for r in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(HERE / "package_charge_weights_applied.csv"))
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    load_dotenv()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8", newline="")))
    print(f"{len(rows)} packages in {Path(args.csv).name}")
    vals = values_clause(rows)
    cte = f"WITH w(package_id, package_code, wt) AS (VALUES {vals})"

    matched = int(psql(f"{cte} SELECT count(*) FROM w JOIN analytical_packages p ON p.package_id = w.package_id AND p.package_code = w.package_code;"))
    todo = int(psql(f"{cte} SELECT count(*) FROM w JOIN analytical_packages p ON p.package_id = w.package_id AND p.package_code = w.package_code WHERE p.minimumsampleweight IS NULL;"))
    already = matched - todo
    print(f"matched on id+code: {matched} | currently empty (will be written): {todo} | already have a value (left alone): {already}")
    if matched != len(rows):
        miss = psql(f"{cte} SELECT w.package_id, w.package_code FROM w LEFT JOIN analytical_packages p ON p.package_id = w.package_id AND p.package_code = w.package_code WHERE p.package_id IS NULL;")
        raise SystemExit(f"{len(rows) - matched} CSV rows did not match id+code in analytical_packages:\n{miss}")

    if not args.commit:
        print("DRY RUN - nothing written. Re-run with --commit.")
        return 0

    tagged_before = int(psql(f"SELECT count(*) FROM analytical_packages WHERE modified_by = '{TAG}';"))
    backup = HERE / f"analytical_packages_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    ids = ",".join(str(int(r["package_id"])) for r in rows)
    psql("SELECT 1;", extra=("-c", f"\\copy (SELECT * FROM analytical_packages WHERE package_id IN ({ids}) ORDER BY package_id) TO '{backup.as_posix()}' CSV HEADER"))
    print("backup written:", backup.name, f"({len(rows)} rows)")

    # One statement = one transaction. The DO block raises (and so rolls everything
    # back) unless the number of updated rows equals the pre-check count.
    sql = (f"DO $$ DECLARE n integer; BEGIN "
           f"UPDATE analytical_packages p SET minimumsampleweight = w.wt, minimumsampleweightunit = 'g', "
           f"modified_by = '{TAG}', modified_date = now() "
           f"FROM (VALUES {vals}) AS w(package_id, package_code, wt) "
           f"WHERE p.package_id = w.package_id AND p.package_code = w.package_code AND p.minimumsampleweight IS NULL; "
           f"GET DIAGNOSTICS n = ROW_COUNT; "
           f"IF n <> {todo} THEN RAISE EXCEPTION 'updated % rows, expected {todo} - rolled back', n; END IF; "
           f"END $$;")
    psql(sql)
    print("update executed")
    done = int(psql(f"SELECT count(*) FROM analytical_packages WHERE modified_by = '{TAG}';")) - tagged_before
    print(f"rows newly tagged {TAG}: {done} (expected {todo})")
    return 0 if done == todo else 1


if __name__ == "__main__":
    sys.exit(main())
