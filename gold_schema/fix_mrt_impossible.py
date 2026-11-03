"""MRT Tasmania (AUSTRALIA_TAS_MRT): classify physically impossible source values as SUSPECT (kept, not used in statistics or the wide table).

Rule (detected results only): a concentration in % above 100 (except the oxide total 'Sum', allowed up to 110 for analytical closure), or in ppm above
1,000,000; an element at 99 % or more of the sample (placeholders such as 1,000,000 ppm); or an element above geochem.analytes.plausible_max_value (its
content in its richest common mineral), except Au, Ag, the platinum-group metals and Zr (bonanza gold, Tasmanian alluvial osmiridium concentrates and
zircon sands can genuinely exceed those limits). Most are ppm values that MRT labels '%' (e.g. S 129,878 '%', Mn 93,500 '%'); the value is left as published, only the classification changes.
Tag for rollback: result_classifications.classified_by is not per-row, so the affected result_ids are written to fix_mrt_impossible_<date>.csv;
   rollback: UPDATE geochem.result_classifications SET result_status = 'DETECTED', use_in_statistics = true WHERE source_system = 'AUSTRALIA_TAS_MRT' AND result_id IN (<ids>);
Rebuild the wide rows afterwards: python build_chem_wide.py AUSTRALIA_TAS_MRT
Usage: python fix_mrt_impossible.py [--dry]
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
c.execute(f"""
SELECT r.result_id, a.analyte_code, r.unit_code, r.value FROM geochem.analytical_results_australia_tas_mrt r JOIN geochem.analytes a USING (analyte_id)
JOIN geochem.result_classifications_australia_tas_mrt k USING (result_id)
WHERE k.result_status = 'DETECTED' AND (
  (r.unit_code = '%' AND r.value > CASE WHEN a.analyte_code = 'Sum' THEN 110 ELSE 100 END) OR (r.unit_code = 'ppm' AND r.value > 1000000)
  OR (a.is_element AND r.value * CASE r.unit_code WHEN '%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END >= 990000)
  OR (a.is_element AND a.plausible_max_value IS NOT NULL AND a.analyte_code NOT IN ('Au','Ag','Pt','Pd','Rh','Ru','Ir','Os','Zr')
      AND r.value * CASE r.unit_code WHEN '%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END
          > a.plausible_max_value * CASE a.plausible_max_unit WHEN '%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END))""")
rows = c.fetchall()
out = os.path.join(HERE, f"fix_mrt_impossible_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")  # one list per run, never overwritten
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "analyte", "unit", "value"]); w.writerows(rows)
c.execute("UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)",
          (SRC, [r[0] for r in rows]))
print("results marked SUSPECT:", c.rowcount, "| list:", out)
c.execute(f"SELECT result_status, use_in_statistics, count(*) FROM geochem.result_classifications WHERE source_system = '{SRC}' GROUP BY 1,2 ORDER BY 3 DESC")
print(c.fetchall())
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
