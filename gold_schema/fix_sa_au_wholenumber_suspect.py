"""SA SARIG drill holes: remaining gold groups that look like ppb published as ppm -> SUSPECT (left out of statistics, wide table, intercepts).
Evidence (18 Nov 2026, after fix_sa_helix_au_units.py and fix_sa_oz_fa2_au_units.py): 14 hole x method groups, 256 detected results, where every
detected Au 'ppm' value is a whole number and the median is >= 2 ppm (Hillgrove B/ETA x10 - e.g. KTRC149B 11 'ppm' vs FA50/AAS 0.02 ppm on the
same hole -, Dominion MAC35 AAS 45 'ppm' with Cu 22 ppm, Minotaur FA1 x2, Hindmarsh AA7). Most lack a second gold method, so the unit is not
relabelled - only the status changes. All results of the group (detected and below-detection) are marked.
Log: fix_sa_au_wholenumber_suspect_<stamp>.csv (result_id, old status, old use_in_statistics). Undo: --undo <log.csv>
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
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '1GB'")

if len(sys.argv) == 3 and sys.argv[1] == "--undo":
    c.execute("CREATE TEMP TABLE u (result_id bigint, old_status text, old_use boolean)")
    with open(sys.argv[2], encoding="utf-8") as f:
        next(f); c.copy_expert("COPY u FROM STDIN WITH (FORMAT csv)", f)
    c.execute(f"UPDATE {RC} k SET result_status = u.old_status, use_in_statistics = u.old_use FROM u WHERE k.source_system = %s AND k.result_id = u.result_id", (SRC,))
    print("restored", c.rowcount); g.commit(); sys.exit()

c.execute(f"""CREATE TEMP TABLE a AS SELECT r.result_id, s.drillhole_id, split_part(substr(r.result_comment, 14), ':', 1) AS m, r.value,
   k.result_status, k.use_in_statistics
 FROM {PART} r JOIN geochem.samples s USING (sample_id)
 JOIN {RC} k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE r.analyte_name = 'Gold' AND r.is_active AND r.unit_code = 'ppm' AND s.drillhole_id IS NOT NULL""")
c.execute("""CREATE TEMP TABLE grp AS SELECT drillhole_id, m FROM a WHERE result_status = 'DETECTED' GROUP BY 1, 2
 HAVING count(*) >= 5 AND bool_and(value = trunc(value)) AND percentile_cont(0.5) WITHIN GROUP (ORDER BY value) >= 2""")
c.execute("""SELECT h.company, grp.m, count(*) FROM grp JOIN drilling.drillholes h USING (drillhole_id) GROUP BY 1, 2 ORDER BY 3 DESC""")
for x in c.fetchall(): print("  ", x)
c.execute("CREATE TEMP TABLE fx AS SELECT a.result_id, a.result_status, a.use_in_statistics FROM a JOIN grp USING (drillhole_id, m) WHERE a.result_status <> 'SUSPECT'")
print("results to mark", c.rowcount)
stamp = time.strftime("%Y%m%d_%H%M%S")
logp = os.path.join(HERE, f"fix_sa_au_wholenumber_suspect_{stamp}.csv")
with open(logp, "w", encoding="utf-8", newline="") as f:
    f.write("result_id,old_status,old_use\n"); c.copy_expert("COPY fx TO STDOUT WITH (FORMAT csv)", f)
print("log", logp)
c.execute(f"UPDATE {RC} k SET result_status = 'SUSPECT', use_in_statistics = false FROM fx WHERE k.source_system = %s AND k.result_id = fx.result_id", (SRC,))
print("marked SUSPECT", c.rowcount)
g.commit(); print("COMMITTED")
