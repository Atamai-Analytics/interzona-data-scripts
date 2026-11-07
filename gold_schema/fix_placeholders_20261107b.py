"""Follow-up to fix_placeholders_20261107.py: after the 5 ppm floor of Te by 'AN: Neutron activation analysis' in CANADA_QC_SIGEOM_SED was
reclassified, the rescreen showed a second floor - 1,799 of the remaining 1,889 detected Te results are exactly 10 ppm (source median 0.03 ppm; INAA
Te detection limits are 5-10 ppm, so a second lab period's limit). -> BELOW_DL_PROBABLE, dl_value 10, dl_source 'PLACEHOLDER_AT_DL'.
Rows listed first in fix_placeholders_b_<time>.csv; rollback as in fix_placeholders_20261107.py. Rebuild: python build_chem_wide.py CANADA_QC_SIGEOM_SED
Usage: python fix_placeholders_20261107b.py [--dry]
"""
import os, sys, csv, datetime
import psycopg2

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""SELECT 'QC_SED_TE10', r.source_system, r.result_id, r.analyte_symbol, r.method_name, r.value, r.unit_code, k.result_status, k.use_in_statistics, k.dl_value, k.dl_source
FROM geochem.analytical_results_canada_qc_sigeom_sed r JOIN geochem.result_classifications_canada_qc_sigeom_sed k USING (result_id)
WHERE r.is_active AND r.analyte_symbol = 'Te' AND r.method_name LIKE 'AN:%%' AND r.value = 10 AND r.unit_code = 'ppm' AND r.qualifier_code IS NULL AND k.result_status = 'DETECTED'""")
rows = c.fetchall()
print("Te INAA at 10 ppm:", len(rows))
assert 1700 <= len(rows) <= 1900, "count moved - stop and look"
out = os.path.join(HERE, f"fix_placeholders_b_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["fix", "source_system", "result_id", "analyte", "method", "value", "unit", "old_status", "old_use", "old_dl_value", "old_dl_source"]); w.writerows(rows)
c.execute("""UPDATE geochem.result_classifications SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = 10, dl_source = 'PLACEHOLDER_AT_DL'
             WHERE source_system = 'CANADA_QC_SIGEOM_SED' AND result_id = ANY(%s)""", ([r[2] for r in rows],))
print("-> BELOW_DL_PROBABLE:", c.rowcount, "| list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
