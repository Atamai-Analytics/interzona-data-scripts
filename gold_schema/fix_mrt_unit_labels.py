"""MRT Tasmania (AUSTRALIA_TAS_MRT): unit labels that contradict the detection limit published in the same MRT record (found 2026-11-07 by unit_screen.py).

Rule A, '%' -> ppm (all companies): a result labelled '%' whose detection limit is >= 1 and that is either a trace element (not an oxide and not
  Si/Al/Fe/Ca/Mg/Na/K/Ti/Mn/P/S/C/Cl) or a value above 100 (impossible as %). No lab reports trace metals with a 1 % detection limit; e.g. Blythe
  River Iron ME-XRF21 'Ni 20 %' with detection limit 10 (MRT XRF record 12500807), Comstaff 'Pb 30 %' with detection limit 5. ~708 results.
  Results QC had marked SUSPECT (impossible as %) become DETECTED; below-detection classifications are kept.
Rule B, ppm -> '%' (Blythe River Iron Pty Ltd, ALS ME-XRF21 fused-bead XRF only): oxides and major elements labelled ppm with a detection limit
  below 0.1 and a value <= 100 (e.g. 'SiO2 9.56 ppm', detection limit 0.01, in the same record as 'TOTAL 100 %'). Check: with the fix, 491 of the
  524 records' oxides (Fe as Fe2O3) total 90-105 % (median 98.7 %), against 405 before. Not applied to other companies: there 'ppm' values up to
  100 include mineral or size-fraction percentages and 100 placeholders (Tasmanian Advanced Minerals, Pluton, Yunnan Tin) - left for review.
Values and detection limits are left as published; result_comment gets a note. Every touched row is written first to fix_mrt_unit_labels_<time>.csv.
Rollback: per CSV row, UPDATE geochem.analytical_results SET unit_id = old_unit_id, unit_code = old_unit_code, result_comment = old_comment and
  UPDATE geochem.result_classifications SET result_status = old_status, use_in_statistics = old_use (source_system = 'AUSTRALIA_TAS_MRT', result_id);
  then python build_chem_wide.py AUSTRALIA_TAS_MRT
Usage: python fix_mrt_unit_labels.py [--dry]
"""
import os, sys, csv, datetime
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_TAS_MRT"
MAJORS = "('Si','Al','Fe','Ca','Mg','Na','K','Ti','Mn','P','S','C','Cl')"
MAJORS_B = "('Si','Al','Fe','Ca','Mg','Na','K','Ti','Mn','P','S')"
NOTE_A = "Unit corrected 2026-11-07 from MRT's label 'percent (%)' to ppm: the detection limit in the same MRT record (>= 1) is in ppm."
NOTE_B = "Unit corrected 2026-11-07 from MRT's label 'ppm' to percent: ALS ME-XRF21 reports this in % (detection limit < 0.1 in the same record; oxides then total ~100 %)."
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT unit_code, unit_id FROM geochem.units WHERE unit_code = ANY(%s)", (["ppm", "%"],))
UNIT = dict(c.fetchall())
c.execute(f"""
SELECT r.result_id, CASE WHEN r.unit_code = '%%' THEN 'A' ELSE 'B' END AS rule, coalesce(h.company, '(surface)'), r.analyte_symbol, a.analyte_code,
       r.value, r.lower_detection_limit, r.unit_id, r.unit_code, r.result_comment, k.result_status, k.use_in_statistics
FROM geochem.analytical_results r JOIN geochem.analytes a USING (analyte_id)
JOIN geochem.samples s ON s.sample_id = r.sample_id AND s.source_system = r.source_system
LEFT JOIN drilling.drillholes h ON h.drillhole_id = s.drillhole_id
LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
WHERE r.source_system = %s AND r.is_active AND (
  (r.unit_code = '%%' AND r.lower_detection_limit >= 1 AND ((r.analyte_symbol NOT IN {MAJORS} AND NOT a.is_oxide) OR r.value > 100))
  OR (h.company = 'Blythe River Iron Pty Ltd' AND r.package_id = (SELECT package_id FROM geochem.analytical_packages WHERE package_name LIKE 'MRT - XRF%%' LIMIT 1)
      AND r.unit_code = 'ppm' AND r.lower_detection_limit < 0.1 AND (a.is_oxide OR r.analyte_symbol IN {MAJORS_B}) AND r.value <= 100))
ORDER BY 2, 1""", (SRC,))
rows = c.fetchall()
a_rows = [r for r in rows if r[1] == "A"]
b_rows = [r for r in rows if r[1] == "B"]
print("rule A (% -> ppm):", len(a_rows), "| rule B (ppm -> %, Blythe River Iron XRF):", len(b_rows))
assert 690 <= len(a_rows) <= 720, "rule A count moved - stop and look"
assert all(r[2] == "Blythe River Iron Pty Ltd" for r in b_rows) and 400 <= len(b_rows) <= 700, "rule B scope moved - stop and look"
out = os.path.join(HERE, f"fix_mrt_unit_labels_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["result_id", "rule", "company", "analyte", "analyte_code", "value", "lower_dl", "old_unit_id", "old_unit_code", "old_comment", "old_status", "old_use"])
    w.writerows(rows)
for rule, ids, unit, note in (("A", [r[0] for r in a_rows], "ppm", NOTE_A), ("B", [r[0] for r in b_rows], "%", NOTE_B)):
    c.execute("""UPDATE geochem.analytical_results SET unit_id = %s, unit_code = %s,
                   result_comment = CASE WHEN coalesce(result_comment, '') = '' THEN %s ELSE result_comment || ' | ' || %s END
                 WHERE source_system = %s AND result_id = ANY(%s)""", (UNIT[unit], unit, note, note, SRC, ids))
    print(f"rule {rule}: relabelled {c.rowcount}")
c.execute("""UPDATE geochem.result_classifications SET result_status = 'DETECTED', use_in_statistics = true
             WHERE source_system = %s AND result_id = ANY(%s) AND result_status = 'SUSPECT'""", (SRC, [r[0] for r in a_rows]))
print("rule A SUSPECT -> DETECTED:", c.rowcount)
c.execute("""SELECT r.unit_code, k.result_status, count(*), min(r.value), max(r.value) FROM geochem.analytical_results r
             LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
             WHERE r.source_system = %s AND r.result_id = ANY(%s) GROUP BY 1, 2 ORDER BY 1, 2""", (SRC, [r[0] for r in rows]))
print("after:", c.fetchall())
print("rollback list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
