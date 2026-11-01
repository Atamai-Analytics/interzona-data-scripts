"""Flip MRDS processing plants from is_deposit = true to false.

Scope: USGS MRDS records (created_by migration_mrds_20261014) whose Workings / operation type is 'Processing plant'
and that are currently is_deposit = true (4,127: 1,777 with MRDS development status 'Plant' + 2,350 Producer / Past Producer / Prospect).
NOT touched: 1,165 records with development status 'Plant' but a mine-type operation (Surface / Underground / Placer ...): those
are mine sites that have a plant, not plants.  status, workings_type, comments, commodities are left as they are (a producing plant keeps PRODUCER).
Tag for rollback: modified_by = 'fix_mrds_plants_20261014'
   rollback:  UPDATE core.occurrences SET is_deposit = true, modified_by = NULL, modified_date = NULL WHERE modified_by = 'fix_mrds_plants_20261014';
Usage: python fix_mrds_plants.py [--dry]   (--dry = apply, verify, ROLLBACK)
"""
import os, sys, time
import psycopg2

DRY = "--dry" in sys.argv
TAG = "migration_mrds_20261014"
FIXTAG = "fix_mrds_plants_20261014"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")


def one(sql, p=None):
    c.execute(sql, p); return c.fetchall()


WHERE = "created_by = %s AND workings_type = 'Processing plant' AND is_deposit"
log("before: MRDS is_deposit / total", one("SELECT count(*) FILTER (WHERE is_deposit), count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)))
log("before: all is_deposit", one("SELECT count(*) FILTER (WHERE is_deposit) FROM core.occurrences"))
log("to flip, by status", one(f"SELECT status, count(*) FROM core.occurrences WHERE {WHERE} GROUP BY 1 ORDER BY 2 DESC", (TAG,)))
log("rows to flip already carrying a modified_by (must be 0)", one(f"SELECT count(*) FROM core.occurrences WHERE {WHERE} AND modified_by IS NOT NULL", (TAG,)))
c.execute(f"UPDATE core.occurrences SET is_deposit = false, modified_by = %s, modified_date = now() WHERE {WHERE}", (FIXTAG, TAG))
log("updated", c.rowcount)
log("after: MRDS is_deposit / total", one("SELECT count(*) FILTER (WHERE is_deposit), count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)))
log("after: all is_deposit", one("SELECT count(*) FILTER (WHERE is_deposit) FROM core.occurrences"))
log("remaining MRDS Processing plant with is_deposit (must be 0)", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND workings_type = 'Processing plant' AND is_deposit", (TAG,)))
log("tagged rows (must equal updated)", one("SELECT count(*) FROM core.occurrences WHERE modified_by = %s", (FIXTAG,)))
log("untouched: dev status 'Plant' with mine-type workings, still is_deposit", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND comments ~ 'Development status: Plant' AND workings_type IS DISTINCT FROM 'Processing plant' AND is_deposit", (TAG,)))
log("other sources changed (must be 0)", one("SELECT count(*) FROM core.occurrences WHERE modified_by = %s AND created_by <> %s", (FIXTAG, TAG)))
log("US is_deposit after", one("SELECT count(*) FILTER (WHERE is_deposit) FROM core.occurrences WHERE country_name = 'United States'"))
log("status of flipped rows unchanged", one("SELECT status, count(*) FROM core.occurrences WHERE modified_by = %s GROUP BY 1 ORDER BY 2 DESC", (FIXTAG,)))
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
    log("after rollback: all is_deposit", one("SELECT count(*) FILTER (WHERE is_deposit) FROM core.occurrences"))
else:
    g.commit(); log("COMMITTED")
g.close()
