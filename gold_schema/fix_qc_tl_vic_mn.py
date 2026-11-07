"""Two classification fixes found 2026-11-07 by unit_screen.py (values stay as published; only result_classifications change).

1. CANADA_QC_SIGEOM thallium at exactly 500 ppm, methods 'PL: Plasma emission, dissolution not recorded' and 'AN: Neutron activation analysis',
   no '<' qualifier, classified DETECTED (6,039 results): 500 ppm is these methods' Tl detection limit (the same methods' '<' results are '<500')
   and ~1,000x the crustal level, so they are below-detection values that lost their '<'. -> BELOW_DL_PROBABLE, use_in_statistics false,
   dl_value 500, dl_source 'PLACEHOLDER_AT_DL'.
2. AUSTRALIA_VIC_GSV_GEOCHEMISTRY manganese: 36 samples carry the same MX-ICPOES number twice in one package, once as '%' (1.74-4.2, the
   over-range ore-grade result) and once as 'ppm' (same digits, or within 5 %: 2.70 % vs 2.76 'ppm' in one sample) - the ppm copies are duplicates with the wrong unit. -> the ppm copies SUSPECT.
Every touched row is written first to fix_qc_tl_vic_mn_<time>.csv. Rollback: per row UPDATE geochem.result_classifications SET result_status =
old_status, use_in_statistics = old_use, dl_value = old_dl_value, dl_source = old_dl_source WHERE source_system = <source> AND result_id = <id>;
then python build_chem_wide.py CANADA_QC_SIGEOM and python build_chem_wide.py AUSTRALIA_VIC_GSV_GEOCHEMISTRY
Usage: python fix_qc_tl_vic_mn.py [--dry]
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
c.execute("""
SELECT 'QC_TL', r.source_system, r.result_id, r.value, r.unit_code, k.result_status, k.use_in_statistics, k.dl_value, k.dl_source
FROM geochem.analytical_results r JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
WHERE r.source_system = 'CANADA_QC_SIGEOM' AND r.is_active AND r.analyte_symbol = 'Tl' AND r.unit_code = 'ppm' AND r.value = 500
  AND r.qualifier_code IS NULL AND k.result_status = 'DETECTED'
  AND r.method_name IN ('PL: Plasma emission, dissolution not recorded', 'AN: Neutron activation analysis')
UNION ALL
SELECT 'VIC_MN', r.source_system, r.result_id, r.value, r.unit_code, k.result_status, k.use_in_statistics, k.dl_value, k.dl_source
FROM geochem.analytical_results r JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
JOIN geochem.analytical_results p ON p.sample_id = r.sample_id AND p.source_system = r.source_system AND p.analyte_symbol = 'Mn' AND p.unit_code = '%'
     AND p.is_active AND p.value BETWEEN r.value * 0.95 AND r.value * 1.05 AND p.package_id = r.package_id AND p.result_id <> r.result_id
WHERE r.source_system = 'AUSTRALIA_VIC_GSV_GEOCHEMISTRY' AND r.is_active AND r.analyte_symbol = 'Mn' AND r.unit_code = 'ppm' AND k.use_in_statistics
ORDER BY 1, 3""")
rows = c.fetchall()
tl = [r for r in rows if r[0] == "QC_TL"]
mn = [r for r in rows if r[0] == "VIC_MN"]
print("Québec Tl at 500 ppm:", len(tl), "| Victoria Mn ppm copies:", len(mn))
assert len(tl) == 6039 and len(mn) == 36, "scope moved - stop and look"
out = os.path.join(HERE, f"fix_qc_tl_vic_mn_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["fix", "source_system", "result_id", "value", "unit", "old_status", "old_use", "old_dl_value", "old_dl_source"]); w.writerows(rows)
c.execute("""UPDATE geochem.result_classifications SET result_status = 'BELOW_DL_PROBABLE', use_in_statistics = false, dl_value = 500, dl_source = 'PLACEHOLDER_AT_DL'
             WHERE source_system = 'CANADA_QC_SIGEOM' AND result_id = ANY(%s)""", ([r[2] for r in tl],))
print("Tl -> BELOW_DL_PROBABLE:", c.rowcount)
c.execute("""UPDATE geochem.result_classifications SET result_status = 'SUSPECT', use_in_statistics = false
             WHERE source_system = 'AUSTRALIA_VIC_GSV_GEOCHEMISTRY' AND result_id = ANY(%s)""", ([r[2] for r in mn],))
print("Vic Mn ppm copies -> SUSPECT:", c.rowcount, "| list:", out)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
