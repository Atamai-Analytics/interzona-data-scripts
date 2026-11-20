"""SA SARIG drill holes: Kelaray Pty Ltd fire-assay gold (SARIG method FA50/AAS) values >= 5 ppm are not gold -> SUSPECT
(left out of statistics, wide table, intercepts).
Evidence (20 Nov 2026), 15 Kelaray holes near Kanmantoo (KTRC 19-32, KTDD122, KTDD131):
- Where FA50 < 5 ppm it agrees with FA25/AAS on the same interval (0.25 vs 0.24, 0.48 vs 0.45, 3.51 vs 3.78) and tracks Cu (corr lnAu-lnCu +0.58).
- Where FA50 >= 5 ppm it disagrees with FA25/AAS 10-100x (KTDD122 132 m 29.78 vs 0.08; KTRC 23 7 m 39.77 vs 0.88), runs opposite to Cu
  (corr -0.49; KTDD131 108-110 m 40.54 'ppm' Au with Cu 2 ppm, Ag/Bi at detection) and clusters near 10/20/25/30/40/50 (a spike at 40-41 in
  the SA-wide fire-assay histogram). Highest Kelaray FA25 value is 5.39 ppm. No other company shows the pattern.
- Shallow B/ETA aqua-regia gold in the same holes is 1-61 ppb.
No unit factor explains the values, so only the status changes. Values < 5 ppm are kept.
Log: fix_sa_kelaray_fa50_suspect_<stamp>.csv (result_id, old status, old use_in_statistics). Undo: --undo <log.csv>
Re-build afterwards: build_chem_wide.py AUSTRALIA_SA_SARIG.
"""
import os, sys, time
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
SRC = "AUSTRALIA_SA_SARIG"
PART = "geochem.analytical_results_australia_sa_sarig"
RC = "geochem.result_classifications"
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
c = g.cursor(); c.execute("SET statement_timeout = 0")

if len(sys.argv) == 3 and sys.argv[1] == "--undo":
    c.execute("CREATE TEMP TABLE u (result_id bigint, old_status text, old_use boolean)")
    with open(sys.argv[2], encoding="utf-8") as f:
        next(f); c.copy_expert("COPY u FROM STDIN WITH (FORMAT csv)", f)
    c.execute(f"UPDATE {RC} k SET result_status = u.old_status, use_in_statistics = u.old_use FROM u WHERE k.source_system = %s AND k.result_id = u.result_id", (SRC,))
    print("restored", c.rowcount); g.commit(); sys.exit()

c.execute(f"""CREATE TEMP TABLE fx AS SELECT r.result_id, k.result_status, k.use_in_statistics, h.hole_name
 FROM drilling.drillholes h JOIN geochem.samples s ON s.drillhole_id = h.drillhole_id
 JOIN {PART} r ON r.sample_id = s.sample_id
 JOIN {RC} k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE h.source_system = %s AND h.company = 'KELARAY PTY LTD.' AND r.analyte_name = 'Gold' AND r.is_active AND r.unit_code = 'ppm'
   AND r.result_comment LIKE 'SARIG method FA50/AAS:%%' AND r.value >= 5 AND k.result_status <> 'SUSPECT'""", (SRC,))
print("results to mark", c.rowcount)
c.execute("SELECT hole_name, count(*) FROM fx GROUP BY 1 ORDER BY 2 DESC")
for x in c.fetchall(): print("  ", x)
stamp = time.strftime("%Y%m%d_%H%M%S")
logp = os.path.join(HERE, f"fix_sa_kelaray_fa50_suspect_{stamp}.csv")
with open(logp, "w", encoding="utf-8", newline="") as f:
    f.write("result_id,old_status,old_use\n"); c.copy_expert("COPY (SELECT result_id, result_status, use_in_statistics FROM fx) TO STDOUT WITH (FORMAT csv)", f)
print("log", logp)
c.execute(f"UPDATE {RC} k SET result_status = 'SUSPECT', use_in_statistics = false FROM fx WHERE k.source_system = %s AND k.result_id = fx.result_id", (SRC,))
print("marked SUSPECT", c.rowcount)
g.commit(); print("COMMITTED")
