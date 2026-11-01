"""Drill-down for the wide-table audit (READ-ONLY): Victoria partial-leach units and the USGS W_p drill-core oddity."""
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
c = g.cursor(); c.execute("SET statement_timeout = 300000")


def q(label, sql, p=None):
    t = time.time(); c.execute(sql, p); r = c.fetchall(); print(f"\n[{round(time.time() - t, 1)}s] {label}")
    for x in r: print("  ", x)
    return r


V = "AUSTRALIA_VIC_GSV_GEOCHEMISTRY"
for an in ("K", "U", "S", "Ba"):
    q(f"Victoria {an}: results by unit (all sample types)", """SELECT r.unit_code, count(*) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 4) med, round(max(r.value)::numeric, 2) mx
        FROM geochem.analytical_results r WHERE r.source_system = %s AND r.analyte_symbol = %s AND r.is_active AND r.value IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""", (V, an))
    q(f"Victoria {an}: unit x package (top 8 by n), with median", """SELECT p.package_code, r.unit_code, count(*) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 4) med
        FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) WHERE r.source_system = %s AND r.analyte_symbol = %s AND r.is_active AND r.value IS NOT NULL
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8""", (V, an))

q("Victoria: how many (analyte, unit) pairs per unit across ALL analytes (active results)", """SELECT unit_code, count(*) n, count(DISTINCT analyte_symbol) analytes FROM geochem.analytical_results
    WHERE source_system = %s AND is_active GROUP BY 1 ORDER BY 2 DESC""", (V,))
q("Victoria: analytes whose results use BOTH ppm and ppb (candidate mislabelled units), with medians per unit", """
    SELECT analyte_symbol, max(CASE WHEN unit_code = 'ppm' THEN n END) n_ppm, max(CASE WHEN unit_code = 'ppb' THEN n END) n_ppb,
           max(CASE WHEN unit_code = 'ppm' THEN med END) med_ppm, max(CASE WHEN unit_code = 'ppb' THEN med END) med_ppb
    FROM (SELECT analyte_symbol, unit_code, count(*) n, percentile_cont(0.5) WITHIN GROUP (ORDER BY value) med FROM geochem.analytical_results
          WHERE source_system = %s AND is_active AND value IS NOT NULL AND unit_code IN ('ppm', 'ppb') GROUP BY 1, 2) x
    GROUP BY 1 HAVING max(CASE WHEN unit_code = 'ppm' THEN n END) IS NOT NULL AND max(CASE WHEN unit_code = 'ppb' THEN n END) IS NOT NULL ORDER BY 1""", (V,))

q("USGS W: _p values by sample type: share of values equal to common round numbers", """SELECT sample_type_name, count(w_p) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY w_p)::numeric) med, mode() WITHIN GROUP (ORDER BY w_p) modal, count(*) FILTER (WHERE w_p = 50000) n_50000,
    count(*) FILTER (WHERE w_p >= 10000) n_ge_10000 FROM geochem.sample_chemistry_wide WHERE source_system = 'USA_USGS_NGDB' AND w_p IS NOT NULL GROUP BY 1 HAVING count(w_p) >= 100 ORDER BY 2 DESC LIMIT 8""")
q("USGS W partial: result rows for 50,000 values - units, packages, qualifiers", """SELECT r.unit_code, p.package_code, coalesce(k.result_status, 'DETECTED') st, count(*) n
    FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
    LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
    WHERE r.source_system = 'USA_USGS_NGDB' AND r.analyte_symbol = 'W' AND r.is_active AND r.value = 50000 GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 8""")
