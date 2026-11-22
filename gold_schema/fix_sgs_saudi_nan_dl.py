"""One-off fix (2026-11-22) for the first SAUDI_SGS_NGD load: columns without a published detection limit (Wadi al 'Ays LOI) were stored
with lower_detection_limit = NaN, so qc_results.py rule 3 classified those detected values BELOW_DL_PROBABLE. Sets the limit to NULL and the
classification back to DETECTED (in statistics). The loader's num() now returns None for NaN. Rebuild the wide rows afterwards.
Usage: python fix_sgs_saudi_nan_dl.py [--dry]
"""
import os, sys, psycopg2

DRY = "--dry" in sys.argv
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""UPDATE geochem.result_classifications_saudi_sgs_ngd k SET result_status = 'DETECTED', dl_value = NULL, dl_source = NULL, use_in_statistics = true
             FROM geochem.analytical_results_saudi_sgs_ngd r
             WHERE r.result_id = k.result_id AND r.lower_detection_limit = 'NaN'::numeric AND r.qualifier_code IS NULL AND k.result_status = 'BELOW_DL_PROBABLE'""")
print("classifications reset", c.rowcount)
c.execute("UPDATE geochem.analytical_results_saudi_sgs_ngd SET lower_detection_limit = NULL WHERE lower_detection_limit = 'NaN'::numeric")
print("NaN limits cleared", c.rowcount)
if DRY:
    g.rollback(); print("DRY - rolled back")
else:
    g.commit(); print("COMMITTED")
