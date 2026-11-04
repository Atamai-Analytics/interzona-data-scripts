"""Result-level QC for one geochemistry source (same rules as qc_mrt_results.py, which stays as the record of the Tasmania run), plus a plausibility
check on that source's drilling.intercepts.

Rules (values are never changed, only the classification or is_active):
  1. IMPOSSIBLE -> result_status SUSPECT: % above 100 (oxide total 'Sum' above 110), ppm above 1,000,000, an element at >= 99 % of the sample, or an
     element or oxide above geochem.analytes.plausible_max_value (except Au, Ag, PGE and Zr: bonanza gold, PGE concentrates, zircon sands).
  2. EXACT DUPLICATE -> is_active = false on all but the first: same sample, analyte, package, value, qualifier, report number and analysis date.
  3. VALUE BELOW ITS OWN DETECTION LIMIT -> BELOW_DL_PROBABLE (not used in statistics, dl_value = the reported limit).
  4. LOW OXIDE TOTAL -> the 'Sum' result only is SUSPECT when a whole-rock total is below 90 %.
  5. IMPOSSIBLE INTERCEPT -> drilling.intercepts.is_active = false (comment says why): same tests as rule 1 on the grade, with Au, Ag and PGE allowed up
     to 5 % (50,000 g/t) instead of being exempt.
Every rule writes the affected ids to qc_<source>_<rule>_<timestamp>.csv (rollback list). Rollback: rule 2 / 5 -> is_active = true; rules 1, 3, 4 ->
  result_status = 'DETECTED', use_in_statistics = true, dl_value = NULL, dl_source = NULL for the listed ids.
Rebuild the wide rows afterwards: python build_chem_wide.py <source>
Usage: python qc_results.py <SOURCE_SYSTEM> [--dry]
"""
import os, sys, csv, datetime
import psycopg2

SRC = sys.argv[1]
DRY = "--dry" in sys.argv
P = SRC.lower()
R, K = f"geochem.analytical_results_{P}", f"geochem.result_classifications_{P}"
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
PRECIOUS = "('Au','Ag','Pt','Pd','Rh','Ru','Ir','Os')"


def save(rule, sql):
    c.execute(sql)
    rows = c.fetchall()
    path = os.path.join(HERE, f"qc_{P}_{rule}_{STAMP}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow([d[0] for d in c.description]); w.writerows(rows)
    return [r[0] for r in rows], path


# 1. impossible
ids, path = save("impossible", f"""
SELECT r.result_id, a.analyte_code, r.unit_code, r.value FROM {R} r JOIN geochem.analytes a USING (analyte_id) JOIN {K} k USING (result_id)
WHERE r.is_active AND k.result_status = 'DETECTED' AND (
  (r.unit_code = '%' AND r.value > CASE WHEN a.analyte_code = 'Sum' THEN 110 ELSE 100 END) OR (r.unit_code = 'ppm' AND r.value > 1000000)
  OR (a.is_element AND r.value * {PPM.format(u='r.unit_code')} >= 990000)
  OR ((a.is_element OR a.is_oxide) AND a.plausible_max_value IS NOT NULL AND a.analyte_code NOT IN {PRECIOUS[:-1]},'Zr')
      AND r.value * {PPM.format(u='r.unit_code')} > a.plausible_max_value * {PPM.format(u='a.plausible_max_unit')}))""")
c.execute("UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)", (SRC, ids))
print("1 impossible -> SUSPECT:", c.rowcount, path, flush=True)

# 2. exact duplicates
ids, path = save("duplicate", f"""
SELECT result_id, sample_id, analyte_id, package_id, value FROM (
  SELECT r.*, row_number() OVER (PARTITION BY sample_id, analyte_id, package_id, value, qualifier_code, report_number, date_analysed ORDER BY result_id) AS rn
  FROM {R} r WHERE r.is_active) x WHERE rn > 1""")
c.execute(f"UPDATE {R} SET is_active = false WHERE result_id = ANY(%s)", (ids,))
print("2 exact duplicates -> inactive:", c.rowcount, path, flush=True)

# 3. detected value below its own detection limit
ids, path = save("below_own_dl", f"""
SELECT r.result_id, r.value, r.lower_detection_limit FROM {R} r JOIN {K} k USING (result_id)
WHERE r.is_active AND k.result_status = 'DETECTED' AND r.lower_detection_limit IS NOT NULL AND r.value < r.lower_detection_limit * 0.999""")
c.execute(f"""UPDATE geochem.result_classifications k SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = r.lower_detection_limit,
              dl_source = 'REPORTED_LDL' FROM {R} r WHERE k.source_system = %s AND k.result_id = r.result_id AND r.result_id = ANY(%s)""", (SRC, ids))
print("3 value below own detection limit -> BELOW_DL_PROBABLE:", c.rowcount, path, flush=True)

# 4. low oxide totals
ids, path = save("low_total", f"""
SELECT r.result_id, r.sample_id, r.value FROM {R} r JOIN geochem.analytes a USING (analyte_id) JOIN {K} k USING (result_id)
WHERE r.is_active AND k.result_status = 'DETECTED' AND a.analyte_code = 'Sum' AND r.unit_code = '%' AND r.value < 90""")
c.execute("UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false WHERE source_system = %s AND result_id = ANY(%s)", (SRC, ids))
print("4 oxide total below 90 % -> Sum SUSPECT:", c.rowcount, path, flush=True)

# 5. impossible intercepts
ids, path = save("intercept_impossible", f"""
SELECT i.intercept_id, a.analyte_code, i.unit_code, i.grade FROM drilling.intercepts i JOIN geochem.analytes a USING (analyte_id)
WHERE i.source_system = '{SRC}' AND i.is_active AND i.grade IS NOT NULL AND (
  (i.unit_code = '%' AND i.grade > 100) OR (i.unit_code = 'ppm' AND i.grade > 1000000)
  OR (a.is_element AND i.grade * {PPM.format(u='i.unit_code')} >= 990000)
  OR (a.analyte_code IN {PRECIOUS} AND i.grade * {PPM.format(u='i.unit_code')} > 50000)
  OR ((a.is_element OR a.is_oxide) AND a.plausible_max_value IS NOT NULL AND a.analyte_code NOT IN {PRECIOUS[:-1]},'Zr')
      AND i.grade * {PPM.format(u='i.unit_code')} > a.plausible_max_value * {PPM.format(u='a.plausible_max_unit')}))""")
c.execute("""UPDATE drilling.intercepts SET is_active = false,
               comments = concat_ws('; ', comments, 'QC: grade physically implausible (likely a unit or element error in the source); not used')
             WHERE intercept_id = ANY(%s)""", (ids,))
print("5 impossible intercepts -> inactive:", c.rowcount, path, flush=True)

c.execute(f"SELECT k.result_status, k.use_in_statistics, r.is_active, count(*) FROM {R} r JOIN {K} k USING (result_id) GROUP BY 1,2,3 ORDER BY 4 DESC")
print(c.fetchall())
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
