"""MRT Tasmania (AUSTRALIA_TAS_MRT): Cu on BCD Resources' 2008 Jarmans / Salisbury Hill RC holes JRC1-JRC6 is labelled 'percent (%)' in MRT's
own file (drillhole__Emission Spectroscopy__Results.csv) but the values are ppm: Cu 2-125 '%' sits beside Zn 15-27 ppm from the same MX-ICPOES run,
the Cu detection limit is 2 (as for Zn ppm), and the same lab package on Venture's Mt Lindsay holes reports Cu in ppm. Found 2026-11-07 when the
drill-intercepts tool ranked them at 11-16 % Cu over 50-78 m from surface.

Fix: unit % -> ppm on those 227 results (value and detection limit unchanged, as published), a note in result_comment, and results that QC had marked
SUSPECT (impossible % values) go back to DETECTED / use_in_statistics. Every touched row is written first to fix_mrt_jarmans_cu_unit_<time>.csv.
Rollback: for each row of that CSV, UPDATE geochem.analytical_results SET unit_id = old_unit_id, unit_code = old_unit_code, result_comment = old_comment
  WHERE source_system = 'AUSTRALIA_TAS_MRT' AND result_id = ...; and UPDATE geochem.result_classifications SET result_status = old_status,
  use_in_statistics = old_use WHERE source_system = 'AUSTRALIA_TAS_MRT' AND result_id = ...; then rebuild the wide rows.
Afterwards: python build_chem_wide.py AUSTRALIA_TAS_MRT
Usage: python fix_mrt_jarmans_cu_unit.py [--dry]
"""
import os, sys, csv, datetime
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_TAS_MRT"
HOLES = ["JRC1", "JRC2", "JRC3", "JRC4", "JRC5", "JRC6"]
NOTE = "Unit corrected 2026-11-07 from MRT's label 'percent (%)' to ppm (detection limit 2 as for Zn ppm in the same run; same package reports Cu in ppm elsewhere)."
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT unit_id FROM geochem.units WHERE unit_code = 'ppm'")
PPM = c.fetchone()[0]
c.execute("""
SELECT r.result_id, h.hole_name, r.value, r.lower_detection_limit, r.unit_id, r.unit_code, r.result_comment, k.result_status, k.use_in_statistics
FROM geochem.analytical_results r
JOIN geochem.samples s ON s.sample_id = r.sample_id AND s.source_system = r.source_system
JOIN drilling.drillholes h ON h.drillhole_id = s.drillhole_id
LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
WHERE r.source_system = %s AND r.analyte_symbol = 'Cu' AND r.method_code = 'MX-ICPOES' AND r.unit_code = '%%' AND h.hole_name = ANY(%s)
ORDER BY r.result_id""", (SRC, HOLES))
rows = c.fetchall()
assert len(rows) == 227, f"expected 227 rows, found {len(rows)} - stop and look"
assert max(float(r[2]) for r in rows) <= 200, "a value is too high to be ppm Cu of this kind - stop and look"
out = os.path.join(HERE, f"fix_mrt_jarmans_cu_unit_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["result_id", "hole", "value", "lower_detection_limit", "old_unit_id", "old_unit_code", "old_comment", "old_status", "old_use"])
    w.writerows(rows)
ids = [r[0] for r in rows]
c.execute("""UPDATE geochem.analytical_results SET unit_id = %s, unit_code = 'ppm',
               result_comment = CASE WHEN coalesce(result_comment, '') = '' THEN %s ELSE result_comment || ' | ' || %s END
             WHERE source_system = %s AND result_id = ANY(%s)""", (PPM, NOTE, NOTE, SRC, ids))
print("results relabelled % -> ppm:", c.rowcount)
c.execute("""UPDATE geochem.result_classifications SET result_status = 'DETECTED', use_in_statistics = true
             WHERE source_system = %s AND result_id = ANY(%s) AND result_status = 'SUSPECT'""", (SRC, ids))
print("SUSPECT -> DETECTED:", c.rowcount)
c.execute("""SELECT r.unit_code, k.result_status, count(*), min(r.value), max(r.value) FROM geochem.analytical_results r
             LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
             WHERE r.source_system = %s AND r.result_id = ANY(%s) GROUP BY 1, 2""", (SRC, ids))
print("after:", c.fetchall())
print("rollback list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
