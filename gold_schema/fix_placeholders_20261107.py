"""Placeholder values found 2026-11-07 by unit_screen.py screen C (one exact value repeated far above the element's median). Values stay as published;
only result_classifications change. Every touched row is written first to fix_placeholders_<time>.csv.

1. CANADA_QC_SIGEOM_SED: As, Sb, Bi by 'EA: Atomic emission spectroscopy' and Te by 'AN: Neutron activation analysis' / 'FX: X-ray fluorescence':
   results exactly at the LOWEST value the method reports for that element (As 1000 ppm = all 131 results; Sb 100; Bi 20; Te 5 and 10), with no '<'
   qualifier anywhere in those methods - the methods' detection limits stored as values (normal levels: As ~2, Sb ~0.1, Bi ~0.09, Te ~0.04 ppm).
   -> BELOW_DL_PROBABLE, dl_value = that value, dl_source 'PLACEHOLDER_AT_DL'. Higher values in the same methods are left as measured.
2. CANADA_ATHABASCA_OF7792 gold, half-detection-limit substitutes: package 2351 (ACME total digest) Au exactly 0.05 ppm where its '<' results give a
   0.1 ppm limit; packages 2349 (ACME aqua regia) and 2352 (ACME 9:1 HNO3:HCl partial) Au exactly 0.25 (half of the 0.5 limit in 2349's '<' results).
   -> BELOW_DL_PROBABLE, dl_value = 2 x value, dl_source 'HALF_DL_SUBSTITUTE'. (SRC total digest 20 ppb is not the method floor - left.)
3. GLOBAL_DEPOSIT_GEOCHEM_GA mercury by AA_CV_WO (Granitto et al. 2021): exactly 36111.11 or 34111.11 ppb in ~280 samples with differing detection
   limits - codes, not measurements. -> SENTINEL, use_in_statistics false.
Rollback: per CSV row UPDATE geochem.result_classifications SET result_status = old_status, use_in_statistics = old_use, dl_value = old_dl_value,
dl_source = old_dl_source WHERE source_system = <source> AND result_id = <id>; then rebuild the wide rows of the three sources.
Usage: python fix_placeholders_20261107.py [--dry]
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
c.execute("SET statement_timeout = 0")
SEL = "SELECT %s, r.source_system, r.result_id, r.analyte_symbol, r.method_name, r.value, r.unit_code, k.result_status, k.use_in_statistics, k.dl_value, k.dl_source"
groups = {}

c.execute(SEL % "'QC_SED_FLOOR'" + """
FROM geochem.analytical_results_canada_qc_sigeom_sed r JOIN geochem.result_classifications_canada_qc_sigeom_sed k USING (result_id)
JOIN (SELECT analyte_symbol, method_name, min(value) AS floor FROM geochem.analytical_results_canada_qc_sigeom_sed
      WHERE is_active AND value > 0 AND ((analyte_symbol IN ('As', 'Sb', 'Bi') AND method_name LIKE 'EA:%%') OR (analyte_symbol = 'Te' AND (method_name LIKE 'AN:%%' OR method_name LIKE 'FX:%%')))
      GROUP BY 1, 2) f USING (analyte_symbol, method_name)
WHERE r.is_active AND r.value = f.floor AND r.qualifier_code IS NULL AND k.result_status = 'DETECTED'""")
groups["QC_SED_FLOOR"] = c.fetchall()

c.execute(SEL % "'ATH_HALF_DL'" + """
FROM geochem.analytical_results_canada_athabasca_of7792 r JOIN geochem.result_classifications_canada_athabasca_of7792 k USING (result_id)
WHERE r.is_active AND r.analyte_symbol = 'Au' AND r.qualifier_code IS NULL AND k.result_status = 'DETECTED'
  AND ((r.package_id = 2351 AND r.value = 0.05 AND r.unit_code = 'ppm') OR (r.package_id IN (2349, 2352) AND r.value = 0.25))""")
groups["ATH_HALF_DL"] = c.fetchall()

c.execute(SEL % "'GA_HG_CODE'" + """
FROM geochem.analytical_results_global_deposit_geochem_ga r JOIN geochem.result_classifications_global_deposit_geochem_ga k USING (result_id)
WHERE r.is_active AND r.analyte_symbol = 'Hg' AND r.method_code = 'AA_CV_WO' AND r.value IN (36111.11, 34111.11) AND k.result_status = 'DETECTED'""")
groups["GA_HG_CODE"] = c.fetchall()

for k_, rows in groups.items():
    by = {}
    for r in rows: by[(r[3], r[4][:25] if r[4] else "", str(r[5]), r[6])] = by.get((r[3], r[4][:25] if r[4] else "", str(r[5]), r[6]), 0) + 1
    print(k_, len(rows), by)
n = {k_: len(v) for k_, v in groups.items()}
assert 3800 <= n["QC_SED_FLOOR"] <= 4000 and 750 <= n["ATH_HALF_DL"] <= 900 and 260 <= n["GA_HG_CODE"] <= 300, ("counts moved - stop and look", n)

out = os.path.join(HERE, f"fix_placeholders_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["fix", "source_system", "result_id", "analyte", "method", "value", "unit", "old_status", "old_use", "old_dl_value", "old_dl_source"])
    for rows in groups.values(): w.writerows(rows)
c.execute("""UPDATE geochem.result_classifications k SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = r.value, dl_source = 'PLACEHOLDER_AT_DL'
             FROM geochem.analytical_results r WHERE k.source_system = 'CANADA_QC_SIGEOM_SED' AND r.source_system = k.source_system AND r.result_id = k.result_id AND k.result_id = ANY(%s)""",
          ([r[2] for r in groups["QC_SED_FLOOR"]],))
print("QC sediments -> BELOW_DL_PROBABLE:", c.rowcount)
c.execute("""UPDATE geochem.result_classifications k SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = 2 * r.value, dl_source = 'HALF_DL_SUBSTITUTE'
             FROM geochem.analytical_results r WHERE k.source_system = 'CANADA_ATHABASCA_OF7792' AND r.source_system = k.source_system AND r.result_id = k.result_id AND k.result_id = ANY(%s)""",
          ([r[2] for r in groups["ATH_HALF_DL"]],))
print("Athabasca Au -> BELOW_DL_PROBABLE:", c.rowcount)
c.execute("""UPDATE geochem.result_classifications SET result_status = 'SENTINEL', use_in_statistics = false
             WHERE source_system = 'GLOBAL_DEPOSIT_GEOCHEM_GA' AND result_id = ANY(%s)""", ([r[2] for r in groups["GA_HG_CODE"]],))
print("GA Hg -> SENTINEL:", c.rowcount, "| list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
