"""Targeted drill-down on the top unit-label suspects from audit_unit_mislabels.py (READ-ONLY)."""
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
c = g.cursor(); c.execute("SET statement_timeout = 900000")


def q(label, sql, p=None):
    t = time.time(); c.execute(sql, p); r = c.fetchall(); print(f"\n[{round(time.time() - t, 1)}s] {label}")
    for x in r: print("  ", x)
    return r


DIST = """SELECT count(*) n, min(r.value) mn, percentile_cont(0.05) WITHIN GROUP (ORDER BY r.value) p5, percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value) med,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY r.value) p95, max(r.value) mx"""
c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'geochem' AND table_name = 'analytical_results' AND column_name IN ('detection_limit', 'value', 'unit_code', 'package_id', 'qualifier_code', 'sample_id')")
print("analytical_results columns present:", [x[0] for x in c.fetchall()])
V, S, U = "AUSTRALIA_VIC_GSV_GEOCHEMISTRY", "SWEDEN_SGU_LITHOGEOCHEMISTRY", "USA_USGS_NGDB"


def dist_for(src, an, pkg, unit):
    q(f"{src} {an} {pkg} [{unit}] distribution and sample types", f"""{DIST} FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
       LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
       WHERE r.source_system = %s AND r.analyte_symbol = %s AND p.package_code = %s AND r.unit_code = %s AND r.is_active AND r.value > 0 AND coalesce(k.use_in_statistics, true)""", (src, an, pkg, unit))
    q("   sample types", """SELECT st.sample_type_name, count(*) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 4) med
       FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) JOIN geochem.samples s ON s.sample_id = r.sample_id JOIN geochem.sample_types st ON st.sample_type_id = s.sample_type_id
       LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
       WHERE r.source_system = %s AND r.analyte_symbol = %s AND p.package_code = %s AND r.unit_code = %s AND r.is_active AND r.value > 0 AND coalesce(k.use_in_statistics, true) GROUP BY 1 ORDER BY 2 DESC LIMIT 5""", (src, an, pkg, unit))


dist_for(V, "Cd", "ANA-MS800", "ppm")
q("Victoria Cd: other packages' medians in the SAME samples-type family (soil) for comparison", """SELECT p.package_code, r.unit_code, count(*) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 4) med
   FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) WHERE r.source_system = %s AND r.analyte_symbol = 'Cd' AND r.is_active AND r.value > 0 GROUP BY 1, 2 HAVING count(*) > 300 ORDER BY 3 DESC LIMIT 8""", (V,))
dist_for(V, "K", "ALS-ICP586", "ppm")
dist_for(S, "Cl", "CEMENTA-TITR", "ppm")
q("Sweden Cl: other packages", """SELECT p.package_code, r.unit_code, count(*) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 3) med FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
   WHERE r.source_system = %s AND r.analyte_symbol = 'Cl' AND r.is_active AND r.value > 0 GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 6""", (S,))
q("USGS packages '14' and '15' (ppb): sample types and a few analytes", """SELECT p.package_code, st.sample_type_name, count(*) n, count(DISTINCT r.analyte_symbol) analytes
   FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) JOIN geochem.samples s ON s.sample_id = r.sample_id JOIN geochem.sample_types st ON st.sample_type_id = s.sample_type_id
   WHERE r.source_system = %s AND p.package_code IN ('14', '15') AND r.is_active GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 6""", (U,))
q("USGS packages '14'/'15': their package rows", """SELECT package_id, package_code, package_name, description FROM geochem.analytical_packages WHERE package_code IN ('14', '15') LIMIT 4""")
q("USGS UNK-CV (percent unit): sample types, analytes and share of the package", """SELECT st.sample_type_name, count(*) n, count(DISTINCT r.analyte_symbol) analytes, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value)::numeric, 3) med_pct
   FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) JOIN geochem.samples s ON s.sample_id = r.sample_id JOIN geochem.sample_types st ON st.sample_type_id = s.sample_type_id
   LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
   WHERE r.source_system = %s AND p.package_code = 'UNK-CV' AND r.unit_code = '%%' AND r.is_active AND r.value > 0 AND coalesce(k.use_in_statistics, true) GROUP BY 1 ORDER BY 2 DESC LIMIT 6""", (U,))
