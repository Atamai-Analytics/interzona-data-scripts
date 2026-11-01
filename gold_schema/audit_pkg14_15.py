"""USGS NGDB packages '14' (Energy Geochemistry Group 14, ICP-AES) and '15' (Group 15, ICP-MS): are their 'ppb'-labelled values really ppm? (READ-ONLY)
For samples that ALSO have the same element from another package (detected, converted to ppm), compare the package value as labelled (ppb) and as if it were ppm."""
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
U = "USA_USGS_NGDB"
c.execute("SELECT package_id, package_code FROM geochem.analytical_packages WHERE package_code IN ('14', '15')")
pk = dict(c.fetchall())
print("packages", pk)
c.execute("""SELECT p.package_code, r.unit_code, count(*) n, count(DISTINCT r.analyte_symbol) analytes, count(DISTINCT r.sample_id) samples FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
             WHERE r.source_system = %s AND p.package_code IN ('14', '15') AND r.is_active GROUP BY 1, 2 ORDER BY 1, 2""", (U,))
print("units used by the packages:", c.fetchall())
t = time.time()
c.execute("""WITH pk AS (SELECT r.result_id, r.sample_id, r.analyte_symbol an, p.package_code, r.value v FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
                 LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
                 WHERE r.source_system = %s AND p.package_code IN ('14', '15') AND r.unit_code = 'ppb' AND r.is_active AND r.value > 0 AND coalesce(k.use_in_statistics, true)),
             oth AS (SELECT r.sample_id, r.analyte_symbol an, percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value * CASE r.unit_code WHEN 'ppm' THEN 1 WHEN 'mg/kg' THEN 1 WHEN 'ppb' THEN 0.001 WHEN '%%' THEN 10000 END) o_ppm
                     FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
                     LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
                     WHERE r.source_system = %s AND p.package_code NOT IN ('14', '15') AND r.is_active AND r.value > 0 AND coalesce(k.use_in_statistics, true) AND r.unit_code IN ('ppm', 'mg/kg', 'ppb', '%%')
                       AND r.sample_id IN (SELECT sample_id FROM pk) GROUP BY 1, 2)
             SELECT pk.package_code, pk.an, count(*) n_pairs,
                    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY (pk.v / 1000.0) / oth.o_ppm)::numeric, 5) ratio_as_labelled_ppb,
                    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pk.v / oth.o_ppm)::numeric, 3) ratio_if_ppm
             FROM pk JOIN oth ON oth.sample_id = pk.sample_id AND oth.an = pk.an GROUP BY 1, 2 HAVING count(*) >= 15 ORDER BY 1, 3 DESC LIMIT 40""", (U, U))
rows = c.fetchall()
print(f"[{round(time.time() - t)}s] package, analyte, pairs on the same samples, median(package/other) AS LABELLED (ppb), median(package/other) IF ppm")
for r in rows: print("  ", r)
