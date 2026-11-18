"""SA SARIG (both phases): move results whose method family was mis-assigned by the old family() rule to the right package.
The old rule matched code patterns before the method's own description: '4AB/MS' (four-acid digest, ICP-MS) matched 'b/ms' -> aqua regia, and aqua
regia gold methods (Au-TL43, Au-ST43 ...) matched 'au' -> fire assay. sa_sarig_common.family() / load_sa_sarig_surface.family() are fixed; across all
1,235 SARIG method-dictionary entries the corrected rule changes exactly these 12 codes. A result moves only if it sits in the old package and its
result_comment ('SARIG method <code>: <description>') carries the matching description text. The label trigger re-resolves method fields.
Log CSV: fix_sa_method_family_<stamp>.csv (result_id, old package, new package). Undo: python fix_sa_method_family.py --undo <log.csv>
Re-build afterwards: build_chem_wide.py AUSTRALIA_SA_SARIG (refreshes drilling.hole_grade_max too).
"""
import csv, os, sys, time
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
PART = "geochem.analytical_results_australia_sa_sarig"
# (method code, old package, new package, text the description must contain)
MOVES = [(c, "SA-FA-ICPMS", "SA-AR-ICPMS", "%aqua%") for c in ("Au-AROR43", "Au-ST43", "Au-ST44", "Au-TL26", "Au-TL43", "Au-TL44", "AuME-TL44", "Au-OG44")] + \
        [(c, "SA-FA-AAS", "SA-AR-AAS", "%aqua%") for c in ("Au-ZF42", "AUSL1", "AUSL2")] + [("4AB/MS", "SA-AR-ICPMS", "SA-4A-ICPMS", "%four acid%")]

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
t0 = time.time()

if len(sys.argv) == 3 and sys.argv[1] == "--undo":
    c.execute("CREATE TEMP TABLE u (result_id bigint, old_pkg int, new_pkg int)")
    with open(sys.argv[2], encoding="utf-8") as f:
        next(f); c.copy_expert("COPY u FROM STDIN WITH (FORMAT csv)", f)
    c.execute(f"UPDATE {PART} r SET package_id = u.old_pkg FROM u WHERE r.result_id = u.result_id AND r.package_id = u.new_pkg")
    print("restored", c.rowcount); g.commit(); sys.exit()

c.execute("SELECT package_code, package_id FROM geochem.analytical_packages WHERE package_code LIKE 'SA-%%'"); pid = dict(c.fetchall())
c.execute("CREATE TEMP TABLE m (code text, old_pkg int, new_pkg int, need text)")
c.executemany("INSERT INTO m VALUES (%s,%s,%s,%s)", [(a, pid[b], pid[d], e) for a, b, d, e in MOVES])
c.execute(f"""CREATE TEMP TABLE fx AS
  SELECT r.result_id, r.package_id AS old_pkg, m.new_pkg FROM {PART} r
  JOIN m ON m.old_pkg = r.package_id AND m.code = split_part(substr(r.result_comment, 14), ':', 1)
  WHERE r.result_comment LIKE 'SARIG method %%' AND r.result_comment ILIKE m.need""")
print(f"{time.time() - t0:.0f}s to move", c.rowcount)
c.execute("""SELECT a.package_code, b.package_code, count(*) FROM fx
             JOIN geochem.analytical_packages a ON a.package_id = fx.old_pkg JOIN geochem.analytical_packages b ON b.package_id = fx.new_pkg
             GROUP BY 1,2 ORDER BY 3 DESC""")
for x in c.fetchall(): print("  ", x)
stamp = time.strftime("%Y%m%d_%H%M%S")
logp = os.path.join(HERE, f"fix_sa_method_family_{stamp}.csv")
with open(logp, "w", encoding="utf-8", newline="") as f:
    f.write("result_id,old_pkg,new_pkg\n"); c.copy_expert("COPY fx TO STDOUT WITH (FORMAT csv)", f)
print("log", logp)
c.execute("CREATE INDEX ON fx (result_id)"); c.execute("ANALYZE fx")
c.execute(f"UPDATE {PART} r SET package_id = fx.new_pkg FROM fx WHERE r.result_id = fx.result_id")
print(f"{time.time() - t0:.0f}s moved", c.rowcount)
g.commit(); print("COMMITTED")
