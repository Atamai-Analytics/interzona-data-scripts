"""IRELAND_GSI_MPM_HISTORIC portable XRF (package MPM_GSRO_PXRF, 541 GSRO samples): censored readings flagged after the unit/placeholder screen
of 15 Nov 2026.
  - frequent column minimum (>= 1% of the readings) = probably half an unreported detection limit (GEMAS rule): Sb 7.5, Ni 5, As 0.5, Cu 2.5,
    Cr 2.5 -> BELOW_DL_PROBABLE, dl_value = 2 x value, dl_source INFERRED_2X_FREQUENT_MIN;
  - Ag = 20 ppm on 513 of 541 readings (not the minimum; source median 0.09 ppm by lab) = a placeholder for 'below the pXRF limit'
    -> BELOW_DL_PROBABLE, dl_value NULL, dl_source PXRF_PLACEHOLDER.
Not used in statistics. Backup of the touched classification rows is written first; rollback = restore result_status/dl_value/dl_source/
use_in_statistics from the backup CSV. Re-run build_chem_wide.py IRELAND_GSI_MPM_HISTORIC afterwards.
Usage: python fix_mpm_pxrf_placeholders.py [--check]
"""
import os, sys, csv, time, psycopg2

CHECK = "--check" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
SEL = """FROM geochem.result_classifications_ireland_gsi_mpm_historic k
         JOIN geochem.analytical_results_ireland_gsi_mpm_historic r USING (result_id)
         JOIN geochem.analytical_packages p ON p.package_id = r.package_id
         WHERE p.package_code = 'MPM_GSRO_PXRF' AND k.result_status = 'DETECTED' AND r.is_active"""
MINS = {"Sb": 7.5, "Ni": 5, "As": 0.5, "Cu": 2.5, "Cr": 2.5}
cond_min = " OR ".join(f"(r.analyte_symbol = '{a}' AND r.value = {v})" for a, v in MINS.items())
cond_ag = "(r.analyte_symbol = 'Ag' AND r.value = 20)"
c.execute(f"SELECT k.result_id, r.analyte_symbol, r.value, k.result_status, k.dl_value, k.dl_source, k.use_in_statistics {SEL} AND ({cond_min} OR {cond_ag})")
rows = c.fetchall()
bk = os.path.join(HERE, f"rc_backup_mpm_pxrf_{time.strftime('%Y%m%d_%H%M%S')}{'_DRY' if CHECK else ''}.csv")
with open(bk, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "analyte", "value", "result_status", "dl_value", "dl_source", "use_in_statistics"]); w.writerows(rows)
print("rows to flag", len(rows), "backup", bk)
c.execute(f"""UPDATE geochem.result_classifications_ireland_gsi_mpm_historic k
              SET result_status = 'BELOW_DL_PROBABLE', dl_value = 2 * r.value, dl_source = 'INFERRED_2X_FREQUENT_MIN', use_in_statistics = false
              {SEL.replace('FROM geochem.result_classifications_ireland_gsi_mpm_historic k', 'FROM').replace('JOIN geochem.analytical_results_ireland_gsi_mpm_historic r USING (result_id)', 'geochem.analytical_results_ireland_gsi_mpm_historic r')}
              AND r.result_id = k.result_id AND ({cond_min})""")
print("frequent minima flagged", c.rowcount)
c.execute(f"""UPDATE geochem.result_classifications_ireland_gsi_mpm_historic k
              SET result_status = 'BELOW_DL_PROBABLE', dl_value = NULL, dl_source = 'PXRF_PLACEHOLDER', use_in_statistics = false
              {SEL.replace('FROM geochem.result_classifications_ireland_gsi_mpm_historic k', 'FROM').replace('JOIN geochem.analytical_results_ireland_gsi_mpm_historic r USING (result_id)', 'geochem.analytical_results_ireland_gsi_mpm_historic r')}
              AND r.result_id = k.result_id AND {cond_ag}""")
print("Ag placeholders flagged", c.rowcount)
if CHECK:
    g.rollback(); print("CHECK - rolled back")
else:
    g.commit(); print("COMMITTED")
