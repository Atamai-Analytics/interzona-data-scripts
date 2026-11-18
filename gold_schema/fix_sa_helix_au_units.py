"""SA SARIG drill holes: gold by SARIG method B/AAS (aqua regia, flame AAS) published as ppm that is really ppb.
Evidence (18 Nov 2026): in 47 holes (Helix Resources LRC holes) the B/AAS Au values are whole numbers (median 14) and their median ratio to the
other gold method on the SAME intervals (mostly B/SAAS solvent extraction, 0.005-0.02 ppm) is >100 (about 600-1,000x); e.g. LRC467 0-4 m
B/AAS 2 'ppm' vs B/SAAS 0.005 ppm. B/AAS gold in the other ~2,400 holes has median ~0.01 ppm and agrees with other methods (ratio < 5).
Rule: holes where >= 3 detected B/AAS Au results pair with another detected gold result and the median ratio > 100 -> all B/AAS Au results of
those holes ppm -> ppb (unit_id only; values and detection limits unchanged, they are in the source's real unit).
Log: fix_sa_helix_au_units_<stamp>.csv (result_id, old unit_id). Undo: python fix_sa_helix_au_units.py --undo <log.csv>
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
PART = "geochem.analytical_results_australia_sa_sarig"
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '1GB'")

if len(sys.argv) == 3 and sys.argv[1] == "--undo":
    c.execute("CREATE TEMP TABLE u (result_id bigint, old_unit int)")
    with open(sys.argv[2], encoding="utf-8") as f:
        next(f); c.copy_expert("COPY u FROM STDIN WITH (FORMAT csv)", f)
    c.execute(f"UPDATE {PART} r SET unit_id = u.old_unit FROM u WHERE r.result_id = u.result_id")
    print("restored", c.rowcount); g.commit(); sys.exit()

c.execute("SELECT unit_id FROM geochem.units WHERE unit_code = 'ppb'"); PPB = c.fetchone()[0]
c.execute(f"""CREATE TEMP TABLE b AS SELECT r.result_id, r.sample_id, r.unit_id, r.value, k.result_status, s.drillhole_id
 FROM {PART} r JOIN geochem.samples s USING (sample_id)
 LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE r.analyte_name = 'Gold' AND r.is_active AND r.unit_code = 'ppm' AND r.result_comment LIKE 'SARIG method B/AAS:%%' AND s.drillhole_id IS NOT NULL""")
c.execute(f"""CREATE TEMP TABLE o AS SELECT r.sample_id, avg(CASE r.unit_code WHEN 'ppb' THEN r.value / 1000 WHEN '%%' THEN r.value * 10000 ELSE r.value END) AS ppm
 FROM {PART} r JOIN (SELECT DISTINCT sample_id FROM b) x USING (sample_id)
 WHERE r.analyte_name = 'Gold' AND r.is_active AND r.result_comment NOT LIKE 'SARIG method B/AAS:%%' AND r.qualifier_code IS NULL GROUP BY 1""")
c.execute("""CREATE TEMP TABLE hz AS SELECT b.drillhole_id FROM b JOIN o USING (sample_id) WHERE b.result_status = 'DETECTED' AND o.ppm > 0
 GROUP BY 1 HAVING count(*) >= 3 AND percentile_cont(0.5) WITHIN GROUP (ORDER BY b.value / o.ppm) > 100""")
c.execute("SELECT count(*), string_agg(DISTINCT h.company, '; ') FROM hz JOIN drilling.drillholes h USING (drillhole_id)"); print("holes", c.fetchone())
c.execute("CREATE TEMP TABLE fx AS SELECT b.result_id, b.unit_id AS old_unit FROM b JOIN hz USING (drillhole_id)")
print("results to relabel", c.rowcount)
stamp = time.strftime("%Y%m%d_%H%M%S")
logp = os.path.join(HERE, f"fix_sa_helix_au_units_{stamp}.csv")
with open(logp, "w", encoding="utf-8", newline="") as f:
    f.write("result_id,old_unit\n"); c.copy_expert("COPY fx TO STDOUT WITH (FORMAT csv)", f)
print("log", logp)
c.execute(f"UPDATE {PART} r SET unit_id = %s FROM fx WHERE r.result_id = fx.result_id", (PPB,))
print("relabelled", c.rowcount)
g.commit(); print("COMMITTED")
