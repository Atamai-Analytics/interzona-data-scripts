"""Strip the USGS NGDB above-range marker from '>' results of ONE load (created_by = TAG).

NGDB CSVs write values above the upper limit as the limit plus a ".1111" suffix, rounded in the file to e.g. "2000.11", "2.11", "0.51"
(= limit 0.5). load_usgs_ngdb_sedsoil.py only stripped a literal "1111" before 2026-11-14, so these rows kept the marker (2.11 % instead of 2 %).
Rule (same as the fixed loader): for values with 2+ decimals ending in 1 (the rounded marker), remove the trailing 1s; if that leaves 0
("0.11", "0.000111") the limit itself ended in 1, so one 1 is kept (0.1, 0.0001). Values like 0.32 or 1.47 (no marker) are left alone. value and upper_detection_limit are both set.
Old values go to fix_gt_backup_<TAG>_<stamp>.csv (rollback = update value / upper_detection_limit back from the CSV by result_id).
Usage: python fix_usgs_ngdb_gt_marker.py TAG [--dry]
"""
import csv, datetime, os, sys
import psycopg2

TAG = sys.argv[1]
DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor()
c.execute("SET statement_timeout = 0")
# trailing zeros of the numeric text first, then the trailing 1s (and a bare '.')
T = r"regexp_replace(value::text, '0+$', '')"
S = rf"regexp_replace({T}, '1+$', '')"
NEW = rf"CASE WHEN rtrim({S}, '.')::numeric = 0 THEN {S} || '1' ELSE rtrim({S}, '.') END"
c.execute(rf"""CREATE TEMP TABLE fx AS
  SELECT result_id, value AS old_value, upper_detection_limit AS old_udl, ({NEW})::numeric AS new_value
  FROM geochem.analytical_results_usa_usgs_ngdb
  WHERE created_by = %s AND qualifier_code = '>' AND value::text LIKE '%%.%%' AND regexp_replace(value::text, '0+$', '') ~ '\.[0-9]*[0-9]1$'""", (TAG,))
c.execute("SELECT count(*), count(*) FILTER (WHERE new_value <= 0) FROM fx"); n, bad = c.fetchone()
print("rows to fix", n, "| non-positive results (must be 0)", bad)
assert bad == 0
c.execute("SELECT old_value, new_value, count(*) FROM fx GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15"); print(c.fetchall())
if DRY:
    g.rollback(); print("DRY RUN"); sys.exit(0)
path = os.path.join(HERE, f"fix_gt_backup_{TAG}_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
c.execute("SELECT result_id, old_value, old_udl FROM fx")
with open(path, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["result_id", "value", "upper_detection_limit"]); w.writerows(c.fetchall())
c.execute("""UPDATE geochem.analytical_results_usa_usgs_ngdb r SET value = fx.new_value, upper_detection_limit = fx.new_value
             FROM fx WHERE r.result_id = fx.result_id""")
print("updated", c.rowcount, "backup", path)
assert c.rowcount == n
g.commit()
