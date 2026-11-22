"""SAUDI_SGS_NGD: classify the DETECTED Ru, Ir and Re results SUSPECT (not used in statistics) - user OK 2026-11-22 ("Mark Ru, Ir and Re as suspect").
Why: SGS reports them by four-acid ICP-OES at levels about a thousand times crustal abundance (Ru median 10 ppm in 622 of 626 Al Madinah samples,
Ir median ~6 ppb in 351 samples, Re up to 670 ppb) - not credible, most likely spectral interference. Values are NOT changed; a note is appended
to result_comment. Below-detection rows are left alone (already out of statistics).
Backup: sgs_saudi_pge_suspect_backup_<stamp>.csv (result_id, old status, old use_in_statistics, old comment).
Rollback: python fix_sgs_saudi_pge_suspect.py --undo <backup.csv>
Usage: python fix_sgs_saudi_pge_suspect.py [--dry | --undo backup.csv]; then python build_chem_wide.py SAUDI_SGS_NGD
"""
import csv, os, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
NOTE = "SUSPECT: Ru/Ir/Re by ICP-OES at ~1000x crustal abundance, not credible (classified 2026-11-22)"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
R, K = "geochem.analytical_results_saudi_sgs_ngd", "geochem.result_classifications_saudi_sgs_ngd"

if UNDO:
    rows = list(csv.DictReader(open(UNDO, encoding="utf-8")))
    for r in rows:
        c.execute(f"UPDATE {K} SET result_status = %s, use_in_statistics = %s WHERE result_id = %s",
                  (r["result_status"], r["use_in_statistics"] == "True", int(r["result_id"])))
        c.execute(f"UPDATE {R} SET result_comment = %s WHERE result_id = %s", (r["result_comment"] or None, int(r["result_id"])))
    g.commit(); print("restored", len(rows)); sys.exit(0)

c.execute(f"""SELECT k.result_id, k.result_status, k.use_in_statistics, r.result_comment, r.analyte_symbol FROM {K} k JOIN {R} r USING (result_id)
              WHERE r.analyte_symbol IN ('Ru', 'Ir', 'Re') AND k.result_status = 'DETECTED' ORDER BY 1""")
rows = c.fetchall()
print("to mark", len(rows), {s: sum(1 for x in rows if x[4] == s) for s in ("Ru", "Ir", "Re")})
if DRY:
    g.rollback(); print("DRY - nothing changed"); sys.exit(0)
path = os.path.join(HERE, f"sgs_saudi_pge_suspect_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "result_status", "use_in_statistics", "result_comment"])
    w.writerows([x[:4] for x in rows])
print("backup", path)
ids = [x[0] for x in rows]
c.execute(f"UPDATE {K} SET result_status = 'SUSPECT', use_in_statistics = false WHERE result_id = ANY(%s)", (ids,))
print("classified SUSPECT", c.rowcount)
c.execute(f"UPDATE {R} SET result_comment = concat_ws('; ', result_comment, %s) WHERE result_id = ANY(%s)", (NOTE, ids))
print("comments", c.rowcount)
assert c.rowcount == len(ids)
g.commit(); print("COMMITTED")
