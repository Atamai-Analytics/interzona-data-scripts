"""SA SARIG drill holes: OZ Minerals fire-assay gold (SARIG method FA2) published as ppm that is really ppb.
Evidence (18 Nov 2026): in 124 OZ Minerals holes (2009-2011) every detected FA2 Au value is a whole number (median 3-4 'ppm', up to ~1,000),
the below-detection values are all '<1', and high 'ppm' gold sits on low-metal intervals (DD10NEP011 452-454 m: Au 19 'ppm' with Cu 534 ppm,
Ag 0.6 ppm), giving 140-370 m at 14-46 g/t composites. Other companies' FA2 gold has decimals (median ~0.04 ppm), and 54 later OZ holes
(2010-12) report FA2 gold in decimals (median ~0.01 ppm) - both left unchanged, as are 23 OZ holes with only '<1' values.
Rule: OZ Minerals holes whose FA2 Au has >= 1 detected value and no detected non-integer value -> all their FA2 Au rows ppm -> ppb
(unit_id only). Log: fix_sa_oz_fa2_au_units_<stamp>.csv (result_id, old unit_id). Undo: python fix_sa_oz_fa2_au_units.py --undo <log.csv>
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
c.execute(f"""CREATE TEMP TABLE oz AS SELECT r.result_id, r.unit_id, r.value, k.result_status, s.drillhole_id
 FROM {PART} r JOIN geochem.samples s USING (sample_id) JOIN drilling.drillholes h ON h.drillhole_id = s.drillhole_id
 LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system
 WHERE h.company = 'OZ MINERALS LTD.' AND r.analyte_name = 'Gold' AND r.is_active AND r.unit_code = 'ppm' AND r.result_comment LIKE 'SARIG method FA2:%%'""")
c.execute("""CREATE TEMP TABLE hz AS SELECT drillhole_id FROM oz GROUP BY 1
 HAVING count(*) FILTER (WHERE result_status = 'DETECTED') >= 1 AND count(*) FILTER (WHERE result_status = 'DETECTED' AND value <> trunc(value)) = 0""")
c.execute("SELECT count(*) FROM hz"); print("holes", c.fetchone()[0])
c.execute("CREATE TEMP TABLE fx AS SELECT oz.result_id, oz.unit_id AS old_unit FROM oz JOIN hz USING (drillhole_id)")
print("results to relabel", c.rowcount)
stamp = time.strftime("%Y%m%d_%H%M%S")
logp = os.path.join(HERE, f"fix_sa_oz_fa2_au_units_{stamp}.csv")
with open(logp, "w", encoding="utf-8", newline="") as f:
    f.write("result_id,old_unit\n"); c.copy_expert("COPY fx TO STDOUT WITH (FORMAT csv)", f)
print("log", logp)
c.execute(f"UPDATE {PART} r SET unit_id = %s FROM fx WHERE r.result_id = fx.result_id", (PPB,))
print("relabelled", c.rowcount)
g.commit(); print("COMMITTED")
