"""Result-level QC for Mineral Resources Tasmania (AUSTRALIA_TAS_MRT). Supersedes fix_mrt_impossible.py (rule 1 is the same rule).

Rules (run after load_mrt_tas.py; values are never changed, only the classification or is_active):
  1. IMPOSSIBLE -> result_status SUSPECT: % above 100 (oxide total 'Sum' above 110), ppm above 1,000,000, an element at >= 99 % of the sample, or an element
     above geochem.analytes.plausible_max_value (except Au, Ag, PGE and Zr: bonanza gold, alluvial osmiridium concentrates, zircon sands).
  2. EXACT DUPLICATE -> is_active = false on all but the first: same sample, analyte, package, value, qualifier, lab job and analysis date from two MRT records.
  3. VALUE BELOW ITS OWN DETECTION LIMIT -> result_status BELOW_DL_PROBABLE (not used in statistics, dl_value = the reported limit): a 'detected' value
     smaller than the lower detection limit reported with it.
  4. LOW OXIDE TOTAL -> the 'Sum' result only is SUSPECT when the total of a whole-rock analysis is below 90 % (incomplete or mis-entered analysis); the
     individual oxides are left as they are.
Every rule writes the affected result_ids to qc_mrt_<rule>_<timestamp>.csv (rollback list). Rollback: rule 2 -> is_active = true; rules 1, 3, 4 ->
  result_status = 'DETECTED', use_in_statistics = true, dl_value = NULL, dl_source = NULL for the listed ids.
Rebuild the wide rows afterwards: python build_chem_wide.py AUSTRALIA_TAS_MRT
Usage: python qc_mrt_results.py [--dry]
"""
import os, sys, csv, datetime
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_TAS_MRT"
R, K = "geochem.analytical_results_australia_tas_mrt", "geochem.result_classifications_australia_tas_mrt"
HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
PPM = "CASE {u} WHEN '%' THEN 10000 WHEN 'ppb' THEN 0.001 ELSE 1 END"


def save(rule, sql):
    c.execute(sql)
    rows = c.fetchall()
    path = os.path.join(HERE, f"qc_mrt_{rule}_{STAMP}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow([d[0] for d in c.description]); w.writerows(rows)
    return [r[0] for r in rows], path


# 1. impossible
ids, path = save("impossible", f"""
SELECT r.result_id, a.analyte_code, r.unit_code, r.value FROM {R} r JOIN geochem.analytes a USING (analyte_id) JOIN {K} k USING (result_id)
WHERE r.is_active AND k.result_status = 'DETECTED' AND (
  (r.unit_code = '%' AND r.value > CASE WHEN a.analyte_code = 'Sum' THEN 110 ELSE 100 END) OR (r.unit_code = 'ppm' AND r.value > 1000000)
  OR (a.is_element AND r.value * {PPM.format(u='r.unit_code')} >= 990000)
  OR (a.is_element AND a.plausible_max_value IS NOT NULL AND a.analyte_code NOT IN ('Au','Ag','Pt','Pd','Rh','Ru','Ir','Os','Zr')
      AND r.value * {PPM.format(u='r.unit_code')} > a.plausible_max_value * {PPM.format(u='a.plausible_max_unit')}))""")
c.execute("UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)", (SRC, ids))
print("1 impossible -> SUSPECT:", c.rowcount, path)

# 2. exact duplicates
ids, path = save("duplicate", f"""
SELECT result_id, sample_id, analyte_id, package_id, value FROM (
  SELECT r.*, row_number() OVER (PARTITION BY sample_id, analyte_id, package_id, value, qualifier_code, report_number, date_analysed ORDER BY result_id) AS rn
  FROM {R} r WHERE r.is_active) x WHERE rn > 1""")
c.execute(f"UPDATE {R} SET is_active = false WHERE result_id = ANY(%s)", (ids,))
print("2 exact duplicates -> inactive:", c.rowcount, path)

# 3. detected value below its own detection limit
ids, path = save("below_own_dl", f"""
SELECT r.result_id, r.value, r.lower_detection_limit FROM {R} r JOIN {K} k USING (result_id)
WHERE r.is_active AND k.result_status = 'DETECTED' AND r.lower_detection_limit IS NOT NULL AND r.value < r.lower_detection_limit * 0.999""")
c.execute(f"""UPDATE geochem.result_classifications k SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = r.lower_detection_limit,
              dl_source = 'REPORTED_LDL' FROM {R} r WHERE k.source_system = %s AND k.result_id = r.result_id AND r.result_id = ANY(%s)""", (SRC, ids))
print("3 value below own detection limit -> BELOW_DL_PROBABLE:", c.rowcount, path)

# 4. low oxide totals
ids, path = save("low_total", f"""
SELECT r.result_id, r.sample_id, r.value FROM {R} r JOIN geochem.analytes a USING (analyte_id) JOIN {K} k USING (result_id)
WHERE r.is_active AND k.result_status = 'DETECTED' AND a.analyte_code = 'Sum' AND r.unit_code = '%' AND r.value < 90""")
c.execute("UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)", (SRC, ids))
print("4 oxide total below 90 % -> Sum SUSPECT:", c.rowcount, path)

c.execute(f"SELECT k.result_status, k.use_in_statistics, r.is_active, count(*) FROM {R} r JOIN {K} k USING (result_id) GROUP BY 1,2,3 ORDER BY 4 DESC")
print(c.fetchall())
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
