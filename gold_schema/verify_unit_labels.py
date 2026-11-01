"""Verification after the unit relabel + Victoria/Sweden wide rebuilds (READ-ONLY): medians of the corrected columns vs the audit's earlier numbers."""
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
c = g.cursor(); c.execute("SET statement_timeout = 600000")


def q(label, sql, p=None):
    t = time.time(); c.execute(sql, p); r = c.fetchall(); print(f"\n[{round(time.time() - t, 1)}s] {label}")
    for x in r: print("  ", x)


V, S = "AUSTRALIA_VIC_GSV_GEOCHEMISTRY", "SWEDEN_SGU_LITHOGEOCHEMISTRY"
q("Victoria wide K (ppm) by basis, stream sediment (was ALS-ICP586 median 0.76 ppm)", """SELECT 'k_t' col, count(k_t), round(percentile_cont(0.5) WITHIN GROUP (ORDER BY k_t)::numeric, 1) med, round(max(k_t)::numeric) mx FROM geochem.sample_chemistry_wide WHERE source_system = %s AND sample_type_name = 'Stream Sediment' AND k_t IS NOT NULL
   UNION ALL SELECT 'k_p', count(k_p), round(percentile_cont(0.5) WITHIN GROUP (ORDER BY k_p)::numeric, 1), round(max(k_p)::numeric) FROM geochem.sample_chemistry_wide WHERE source_system = %s AND sample_type_name = 'Stream Sediment' AND k_p IS NOT NULL""", (V, V))
q("Victoria wide Cd (ppm) by sample type, partial basis (was median 12 ppm in soils)", """SELECT sample_type_name, count(cd_p) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cd_p)::numeric, 4) med, round(percentile_cont(0.99) WITHIN GROUP (ORDER BY cd_p)::numeric, 3) p99, round(max(cd_p)::numeric, 2) mx
   FROM geochem.sample_chemistry_wide WHERE source_system = %s AND cd_p IS NOT NULL GROUP BY 1 HAVING count(cd_p) >= 200 ORDER BY 2 DESC LIMIT 8""", (V,))
q("Sweden wide Cl (ppm) rock samples (the relabelled results were 0.07 ppm)", """SELECT 'cl_t' col, count(cl_t), round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cl_t)::numeric, 1), round(max(cl_t)::numeric) FROM geochem.sample_chemistry_wide WHERE source_system = %s AND cl_t IS NOT NULL
   UNION ALL SELECT 'cl_p', count(cl_p), round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cl_p)::numeric, 1), round(max(cl_p)::numeric) FROM geochem.sample_chemistry_wide WHERE source_system = %s AND cl_p IS NOT NULL""", (S, S))
q("Row counts per source (unchanged expected)", "SELECT source_system, count(*) FROM geochem.sample_chemistry_wide GROUP BY 1 ORDER BY 2 DESC")
q("Relabelled results: units now", """SELECT r.source_system, p.package_code, r.analyte_symbol, r.unit_code, count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
   WHERE (r.source_system = %s AND p.package_code IN ('ALS-ICP586', 'ANA-MS800', 'AMD-WEAK-ACID') AND r.analyte_symbol IN ('K', 'Cd')) OR (r.source_system = %s AND p.package_code = 'CEMENTA-TITR' AND r.analyte_symbol = 'Cl') GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4""", (V, S))
