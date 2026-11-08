"""Reclassify USGS NGDB laboratory / field blanks (comments 'blank', 'field blank', 'blank filter', 'water/bottle blank ...') from rock /
unknown sample types to sample_type 51 'Quality Control Sample' (2026-11-08; audit side finding: ~463 blanks among the rock samples).
Samples stay active; geochem.sample_chemistry_wide.sample_type_name is updated to match. Log fix_usgs_blanks_qc_<ts>.csv (sample_id, old type).
Usage: python fix_usgs_blanks_qc.py [--dry]
"""
import csv, os, sys, datetime
import psycopg2

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
WHERE = r"""source_system = 'USA_USGS_NGDB' AND (lower(trim(comments)) IN ('blank', 'field blank', 'blank filter')
            OR lower(comments) LIKE 'water/bottle blank%%')"""
c.execute(f"SELECT sample_id, sample_type_id, comments FROM geochem.samples WHERE {WHERE}")
rows = c.fetchall(); print("blank samples", len(rows))
c.execute("SELECT sample_type_name FROM geochem.sample_types WHERE sample_type_id = 51"); qc = c.fetchone()[0]
c.execute(f"UPDATE geochem.samples SET sample_type_id = 51 WHERE {WHERE}"); print("samples updated", c.rowcount)
c.execute("UPDATE geochem.sample_chemistry_wide SET sample_type_name = %s WHERE sample_id = ANY(%s)", (qc, [r[0] for r in rows])); print("wide rows updated", c.rowcount)
p = os.path.join(HERE, f"fix_usgs_blanks_qc_{datetime.datetime.now():%Y%m%d_%H%M%S}{'_DRY' if DRY else ''}.csv")
with open(p, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["sample_id", "old_sample_type_id", "comments"]); w.writerows(rows)
if DRY: g.rollback(); print("DRY RUN - rolled back")
else: g.commit(); print("COMMITTED", p)
