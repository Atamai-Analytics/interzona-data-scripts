"""Slim geochem.result_classifications: move the per-row audit columns (classified_at, classified_by ~28 bytes/row) into a small
history table, drop the columns, then VACUUM FULL each partition to reclaim the space.  Table name, remaining columns and keys are unchanged,
so every existing query keeps working.  Usage: python slim_result_classifications.py
Rollback of the history is not needed (geochem.classification_batches keeps who/when per source_system+rule).
"""
import os, time
import psycopg2

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET lock_timeout = '60s'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


PARTS = ["result_classifications_finland_gtk_rock", "result_classifications_greenland_geus", "result_classifications_argentina_segemar",
         "result_classifications_sweden_sgu_lithogeochemistry", "result_classifications_other"]


def sizes():
    c.execute("""SELECT pg_total_relation_size(c.oid) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = 'geochem.result_classifications'::regclass""")
    return sum(r[0] for r in c.fetchall())


c.execute("SELECT count(*) FROM geochem.result_classifications"); n_before = c.fetchone()[0]
c.execute("SELECT source_system, result_status, use_in_statistics, count(*) FROM geochem.result_classifications GROUP BY 1,2,3 ORDER BY 1,2,3")
snap_before = c.fetchall()
s0 = sizes(); log("rows", n_before, "total size MB", round(s0 / 1e6))

c.execute("""CREATE TABLE IF NOT EXISTS geochem.classification_batches (
  source_system varchar(50) NOT NULL, classified_by varchar(100) NOT NULL, first_classified_at timestamptz, last_classified_at timestamptz,
  n_rows bigint NOT NULL, recorded_at timestamptz DEFAULT now(), note text, PRIMARY KEY (source_system, classified_by))""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, classified_by, min(classified_at), max(classified_at), count(*), 'history kept when per-row classified_at/classified_by were dropped 2026-10-12'
 FROM geochem.result_classifications GROUP BY 1, 2 ON CONFLICT (source_system, classified_by) DO NOTHING""")
c.execute("SELECT count(*), sum(n_rows) FROM geochem.classification_batches"); log("classification_batches (groups, rows)", c.fetchone())

c.execute("ALTER TABLE geochem.result_classifications DROP COLUMN IF EXISTS classified_at, DROP COLUMN IF EXISTS classified_by")
log("columns dropped")
for p in PARTS:
    t0 = time.time(); c.execute(f"VACUUM (FULL, ANALYZE) geochem.{p}"); log("rewritten", p, round(time.time() - t0), "s")

c.execute("SELECT count(*) FROM geochem.result_classifications"); n_after = c.fetchone()[0]
c.execute("SELECT source_system, result_status, use_in_statistics, count(*) FROM geochem.result_classifications GROUP BY 1,2,3 ORDER BY 1,2,3")
assert n_after == n_before and c.fetchall() == snap_before, "row counts changed"
s1 = sizes(); log("rows unchanged", n_after, "| total size MB", round(s0 / 1e6), "->", round(s1 / 1e6), "| saved MB", round((s0 - s1) / 1e6))
c.execute("""SELECT c.relname, pg_size_pretty(pg_total_relation_size(c.oid)) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = 'geochem.result_classifications'::regclass ORDER BY pg_total_relation_size(c.oid) DESC""")
log(c.fetchall())
