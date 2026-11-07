"""MRT Tasmania (AUSTRALIA_TAS_MRT): Australian Hualong's Oceana holes OC3-OC6 carry two silver results per sample from ALS Burnie: the original
acid-digest ICP-ES analysis (package 'MRT - acid digestion with ICP emission spectroscopy', Ag 1-120 ppm, detection limit 1, alongside Pb in the
same record) and a 'Repeat No. 1' record (package 'MRT - emission spectroscopy, digestion not stated') holding only Ag = 1,110-116,500 'ppm'
(detection limit 10). The repeat values do not track the originals under any unit conversion (e.g. 31,800 vs 1 ppm; 116,500 vs 74 ppm), so what
they measure cannot be told from MRT's file (drillhole__Emission Spectroscopy__Results.csv, e.g. ID 1207093 vs 337266). Found 2026-11-07 when
the drill-intercepts tool ranked OC4 at 8,257 g/t Ag over 28 m.

Fix: the repeat Ag results that are >= 100x the original acid-digest Ag of the same sample (and >= 1,000 ppm) become SUSPECT (kept as published,
not used in statistics or the wide table); the original results are untouched. Rows are listed first in fix_mrt_oceana_ag_repeats_<time>.csv.
Rollback: UPDATE geochem.result_classifications SET result_status = old_status, use_in_statistics = old_use WHERE source_system = 'AUSTRALIA_TAS_MRT'
  AND result_id = <id> for each row of that CSV; then python build_chem_wide.py AUSTRALIA_TAS_MRT
Usage: python fix_mrt_oceana_ag_repeats.py [--dry]
"""
import os, sys, csv, datetime
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_TAS_MRT"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT package_id FROM geochem.analytical_packages WHERE package_name IN ('MRT - emission spectroscopy, digestion not stated', 'MRT - acid digestion with ICP emission spectroscopy') ORDER BY package_name")
rows = c.fetchall()
assert len(rows) == 2, rows
ACID, REPEAT = rows[0][0], rows[1][0]  # 'acid ...' sorts before 'emission ...'
c.execute("""
SELECT rep.result_id, h.hole_name, s.depth_from_m, rep.value AS repeat_ag, orig.value AS original_ag, k.result_status, k.use_in_statistics
FROM geochem.analytical_results rep
JOIN geochem.analytical_results orig ON orig.sample_id = rep.sample_id AND orig.source_system = rep.source_system AND orig.analyte_symbol = 'Ag'
     AND orig.package_id = %s AND orig.is_active AND orig.unit_code = 'ppm'
JOIN geochem.samples s ON s.sample_id = rep.sample_id AND s.source_system = rep.source_system
LEFT JOIN drilling.drillholes h ON h.drillhole_id = s.drillhole_id
JOIN geochem.result_classifications k ON k.result_id = rep.result_id AND k.source_system = rep.source_system
WHERE rep.source_system = %s AND rep.analyte_symbol = 'Ag' AND rep.package_id = %s AND rep.is_active AND rep.unit_code = 'ppm'
  AND rep.value >= 1000 AND rep.value >= 100 * greatest(orig.value, 0.5) AND k.use_in_statistics
ORDER BY h.hole_name, s.depth_from_m""", (ACID, SRC, REPEAT))
rows = c.fetchall()
holes = sorted({r[1] for r in rows})
print("results to mark SUSPECT:", len(rows), "holes:", holes)
assert set(holes) <= {"OC3", "OC4", "OC5", "OC6"}, "unexpected holes - stop and look"
out = os.path.join(HERE, f"fix_mrt_oceana_ag_repeats_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "hole", "depth_from_m", "repeat_ag_ppm", "original_ag_ppm", "old_status", "old_use"]); w.writerows(rows)
c.execute("UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)",
          (SRC, [r[0] for r in rows]))
print("marked SUSPECT:", c.rowcount, "| list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
