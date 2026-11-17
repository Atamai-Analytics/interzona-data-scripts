"""NSW (AUSTRALIA_NSW_GSNSW) follow-up fixes, 2026-11-17.
1. Electron-microprobe results (result_comment mentions microprobe / electmicro; reports 1490 and 3225, 2,560 results on 152 stream / soil
   samples) are spot analyses of indicator-mineral grains (chromite, ilmenite: median Cr 43 %, FeO 18 %), not bulk sample chemistry ->
   is_active = false, logged to fix_nsw_microprobe_<stamp>.csv.  YFe3 (a spinel ratio parameter) only occurs in these rows.
2. Analyte 'La2O1' (only used by NSW; ALS ME-XRF15b / ME-XRF30 REE-oxide suites beside CeO2, Nd2O3) is La2O3 -> code and name corrected,
   result analyte_name updated, wide column la2o1_t renamed la2o3_t.
3. Analyte 'S2O' (7 results, reported beside SO3 in two XRF files) -> name marks the meaning as unclear.
Usage: python fix_nsw_analytes_microprobe.py [--dry] | --undo <csv>
"""
import csv, os, sys, time
import psycopg2

SRC, PART = "AUSTRALIA_NSW_GSNSW", "australia_nsw_gsnsw"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
c = g.cursor(); c.execute("SET statement_timeout = 0")
T = f"geochem.analytical_results_{PART}"

if len(sys.argv) > 2 and sys.argv[1] == "--undo":
    ids = [int(r["result_id"]) for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"))]
    c.execute(f"UPDATE {T} SET is_active = true WHERE result_id = ANY(%s)", (ids,)); print("reactivated", c.rowcount)
    c.execute("UPDATE geochem.analytes SET analyte_code = 'La2O1', analyte_name = 'La2O1' WHERE analyte_code = 'La2O3' AND analyte_id = 395")
    c.execute(f"UPDATE {T} SET analyte_name = 'La2O1' WHERE analyte_id = 395")
    c.execute("UPDATE geochem.analytes SET analyte_name = 'S2O' WHERE analyte_code = 'S2O'")
    g.commit(); print("undone (rename wide column la2o3_t back to la2o1_t by hand if needed)"); sys.exit()

dry = "--dry" in sys.argv
c.execute(f"""SELECT result_id, sample_id, analyte_symbol, value, unit_code, result_comment FROM {T}
              WHERE is_active AND (result_comment ILIKE '%%microprobe%%' OR result_comment ILIKE '%%electmicro%%')""")
rows = c.fetchall(); print("microprobe results to deactivate", len(rows), "samples", len({r[1] for r in rows}))
out = os.path.join(HERE, f"fix_nsw_microprobe_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "sample_id", "analyte", "value", "unit", "comment"]); w.writerows(rows)
c.execute(f"UPDATE {T} SET is_active = false WHERE result_id = ANY(%s)", ([r[0] for r in rows],)); print("deactivated", c.rowcount)

c.execute("SELECT count(*) FROM geochem.analytes WHERE analyte_code = 'La2O3'"); assert c.fetchone()[0] == 0
c.execute("UPDATE geochem.analytes SET analyte_code = 'La2O3', analyte_name = 'Lanthanum Oxide (La2O3; source label La2O1)' WHERE analyte_id = 395 AND analyte_code = 'La2O1'")
print("La2O1 -> La2O3", c.rowcount)
c.execute(f"UPDATE {T} SET analyte_name = 'Lanthanum Oxide (La2O3; source label La2O1)' WHERE analyte_id = 395"); print("result names", c.rowcount)
c.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'geochem' AND table_name = 'sample_chemistry_wide' AND column_name = 'la2o1_t'""")
if c.fetchone()[0]:
    c.execute("ALTER TABLE geochem.sample_chemistry_wide RENAME COLUMN la2o1_t TO la2o3_t"); print("wide column renamed")
c.execute("UPDATE geochem.analytes SET analyte_name = 'S2O (source label, meaning unclear - reported beside SO3)' WHERE analyte_code = 'S2O'")
print("S2O renamed", c.rowcount)
if dry:
    g.rollback(); print("DRY - rolled back")
else:
    g.commit(); print("COMMITTED; log", out)
