"""MRT Tasmania (AUSTRALIA_TAS_MRT): Venture Minerals' acid-digest ICP-ES tin (package 'MRT - acid digestion with ICP emission spectroscopy',
Mt Lindsay and nearby holes) is labelled ppm on 1,356 results but is in percent: detection limit 0.001 and values 0.001-1.0, exactly like the 44
results in the same package that ARE labelled '%' (detection limit 0.001, 0.001-0.155); and the values track the same samples' XRF Sn in %
(median ratio 1.25, log correlation 0.87). Found 2026-11-07 by unit_screen.py (acid vs XRF tin ~14,000x apart).
Fix: unit ppm -> % on those results (values and detection limit as published, note in result_comment). Rows listed first in
fix_mrt_venture_sn_unit_<time>.csv. Rollback: per row UPDATE geochem.analytical_results SET unit_id = old_unit_id, unit_code = old_unit_code,
result_comment = old_comment WHERE source_system = 'AUSTRALIA_TAS_MRT' AND result_id = ...; then python build_chem_wide.py AUSTRALIA_TAS_MRT
Usage: python fix_mrt_venture_sn_unit.py [--dry]
"""
import os, sys, csv, datetime
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_TAS_MRT"
NOTE = "Unit corrected 2026-11-07 from MRT's label 'ppm' to percent: detection limit 0.001 and values match this package's Sn results labelled % and the same samples' XRF Sn %."
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT unit_id FROM geochem.units WHERE unit_code = %s", ("%",))
PCT = c.fetchone()[0]
c.execute("""
SELECT r.result_id, h.hole_name, r.value, r.lower_detection_limit, r.unit_id, r.unit_code, r.result_comment
FROM geochem.analytical_results r
JOIN geochem.samples s ON s.sample_id = r.sample_id AND s.source_system = r.source_system
JOIN drilling.drillholes h ON h.drillhole_id = s.drillhole_id
WHERE r.source_system = %s AND r.is_active AND r.analyte_symbol = 'Sn' AND r.unit_code = 'ppm' AND r.lower_detection_limit = 0.001
  AND h.company = 'Venture Minerals Ltd'
  AND r.package_id = (SELECT package_id FROM geochem.analytical_packages WHERE package_name = 'MRT - acid digestion with ICP emission spectroscopy')
ORDER BY r.result_id""", (SRC,))
rows = c.fetchall()
print("results:", len(rows), "holes:", len({r[1] for r in rows}), "max value:", max(r[2] for r in rows))
assert len(rows) == 1356 and max(float(r[2]) for r in rows) <= 1.0, "scope moved - stop and look"
out = os.path.join(HERE, f"fix_mrt_venture_sn_unit_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "hole", "value", "lower_dl", "old_unit_id", "old_unit_code", "old_comment"]); w.writerows(rows)
c.execute("""UPDATE geochem.analytical_results SET unit_id = %s, unit_code = '%%',
               result_comment = CASE WHEN coalesce(result_comment, '') = '' THEN %s ELSE result_comment || ' | ' || %s END
             WHERE source_system = %s AND result_id = ANY(%s)""", (PCT, NOTE, NOTE, SRC, [r[0] for r in rows]))
print("relabelled ppm -> %:", c.rowcount, "| list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
