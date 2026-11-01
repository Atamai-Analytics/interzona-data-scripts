"""Drill-down 3 (READ-ONLY): what are the USGS UNK-CV '%' results, and do packages 14/15 'ppb' values match other methods on the same samples?"""
import os, time
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 1200000"); c.execute("SET work_mem = '256MB'")


def q(label, sql, p=None):
    t = time.time(); c.execute(sql, p); r = c.fetchall(); print(f"\n[{round(time.time() - t, 1)}s] {label}")
    for x in r: print("  ", x)
    return r


U = "USA_USGS_NGDB"
q("UNK-CV: analytes, units, value distribution (detected only)", """SELECT r.analyte_symbol, r.unit_code, count(*) n, round(percentile_cont(0.1) WITHIN GROUP (ORDER BY r.value)::numeric, 3) p10,
   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 3) med, round(percentile_cont(0.9) WITHIN GROUP (ORDER BY r.value)::numeric, 3) p90, count(DISTINCT r.value) distinct_values, r.qualifier_code
   FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
   WHERE r.source_system = %s AND p.package_code = 'UNK-CV' AND r.is_active AND r.value > 0 AND coalesce(k.use_in_statistics, true) GROUP BY 1, 2, 8 HAVING count(*) > 300 ORDER BY 3 DESC LIMIT 14""", (U,))
q("UNK-CV Ni (%): on the SAME samples, what do the other Ni results say (ppm-equivalent medians)?", """
   WITH cv AS (SELECT r.sample_id, r.value * 10000 AS ni_cv_ppm FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
               WHERE r.source_system = %s AND p.package_code = 'UNK-CV' AND r.analyte_symbol = 'Ni' AND r.unit_code = '%%' AND r.is_active AND r.value > 0 LIMIT 3000),
   oth AS (SELECT r.sample_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY CASE r.unit_code WHEN 'ppm' THEN r.value WHEN 'mg/kg' THEN r.value WHEN 'ppb' THEN r.value / 1000 WHEN '%%' THEN r.value * 10000 END) AS ni_other_ppm
           FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) WHERE r.source_system = %s AND r.analyte_symbol = 'Ni' AND p.package_code <> 'UNK-CV' AND r.is_active AND r.value > 0
           AND r.sample_id IN (SELECT sample_id FROM cv) GROUP BY 1)
   SELECT count(*) samples_with_both, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cv.ni_cv_ppm)::numeric) med_cv_ppm, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY oth.ni_other_ppm)::numeric) med_other_ppm,
          round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cv.ni_cv_ppm / oth.ni_other_ppm)::numeric, 1) med_ratio FROM cv JOIN oth USING (sample_id)""", (U, U))
q("UNK-CV: how many samples have UNK-CV results, and which top analytes drive wide-table extremes", """SELECT count(DISTINCT r.sample_id) samples, count(*) results FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
   WHERE r.source_system = %s AND p.package_code = 'UNK-CV' AND r.is_active""", (U,))
q("UNK-CV: raw examples (one grab rock sample, all its results)", """SELECT r.analyte_symbol, r.unit_code, r.value, r.qualifier_code, p.package_code FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
   WHERE r.source_system = %s AND r.sample_id = (SELECT r2.sample_id FROM geochem.analytical_results r2 JOIN geochem.analytical_packages p2 USING (package_id) WHERE r2.source_system = %s AND p2.package_code = 'UNK-CV' AND r2.analyte_symbol = 'Ni' AND r2.is_active LIMIT 1 OFFSET 777)
   AND r.is_active ORDER BY p.package_code, r.analyte_symbol LIMIT 30""", (U, U))
