"""Per-hole assay summary for the drill-intercepts tool and page (app src/lib/intercepts.ts, drill-extract.ts). Re-run after any drill load or
wide rebuild of a drill source.

drilling.hole_grade_max    (drillhole_id, source_system, col, max_value, n_assayed): for every wide analyte column (<el>_t / <el>_p / oxides /
                           c_noncarb_pct) the highest value over the hole's downhole intervals (depth_to_m > depth_from_m) and how many intervals
                           were assayed for it (a value, or the column in bdl_codes = assayed but below detection; max_value is NULL if all were).
drilling.hole_sample_count (drillhole_id, source_system, n_intervals): downhole intervals per hole.
The tool uses the column maxima as an UPPER BOUND to pick candidate holes for a cut-off (max of a coalesce over columns, or of a metal equivalent,
can never exceed the sum / max of the column maxima), then runs the exact query only on those holes - so results are unchanged, just faster.
Usage: python build_hole_grade_summary.py [SOURCE ...]   (default: every source with downhole intervals in the wide table)
"""
import os, sys, time
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'"); g.commit()
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


c.execute("""CREATE TABLE IF NOT EXISTS drilling.hole_grade_max (drillhole_id bigint NOT NULL, source_system text NOT NULL, col text NOT NULL,
             max_value double precision, n_assayed integer NOT NULL, PRIMARY KEY (drillhole_id, col, source_system))""")
c.execute("""CREATE TABLE IF NOT EXISTS drilling.hole_sample_count (drillhole_id bigint NOT NULL, source_system text NOT NULL, n_intervals integer NOT NULL,
             PRIMARY KEY (drillhole_id, source_system))""")
c.execute("CREATE INDEX IF NOT EXISTS hole_grade_max_col_val ON drilling.hole_grade_max (col, max_value DESC)")
c.execute("COMMENT ON TABLE drilling.hole_grade_max IS 'Per drill hole and wide analyte column: highest value over downhole intervals and number of intervals assayed. Built by build_hole_grade_summary.py; upper bound for the intercept tool.'")
g.commit()

c.execute("""SELECT column_name FROM information_schema.columns WHERE table_schema = 'geochem' AND table_name = 'sample_chemistry_wide'
             AND data_type IN ('double precision', 'numeric', 'real') AND (column_name ~ '_(t|p)$' OR column_name = 'c_noncarb_pct')
             AND column_name NOT IN ('depth_from_m', 'depth_to_m') ORDER BY 1""")
cols = [x[0] for x in c.fetchall()]
log("analyte columns", len(cols))
if len(sys.argv) > 1:
    sources = sys.argv[1:]
else:
    c.execute("SELECT DISTINCT source_system FROM geochem.sample_chemistry_wide WHERE drillhole_id IS NOT NULL AND depth_to_m > depth_from_m")
    sources = [x[0] for x in c.fetchall()]
values = ", ".join(f"('{k}', w.{k}::double precision)" for k in cols)
for src in sources:
    c.execute("DELETE FROM drilling.hole_grade_max WHERE source_system = %s", (src,))
    c.execute("DELETE FROM drilling.hole_sample_count WHERE source_system = %s", (src,))
    c.execute(f"""
    INSERT INTO drilling.hole_grade_max (drillhole_id, source_system, col, max_value, n_assayed)
    SELECT drillhole_id, %s, col, max(v), count(*) FROM (
      SELECT w.drillhole_id, x.col, x.v FROM geochem.sample_chemistry_wide w CROSS JOIN LATERAL (VALUES {values}) x(col, v)
      WHERE w.source_system = %s AND w.drillhole_id IS NOT NULL AND w.depth_to_m > w.depth_from_m AND x.v IS NOT NULL
      UNION ALL
      SELECT w.drillhole_id, b.col, NULL FROM geochem.sample_chemistry_wide w CROSS JOIN LATERAL unnest(w.bdl_codes) b(col)
      WHERE w.source_system = %s AND w.drillhole_id IS NOT NULL AND w.depth_to_m > w.depth_from_m
    ) z GROUP BY drillhole_id, col""", (src, src, src))
    n = c.rowcount
    c.execute("""INSERT INTO drilling.hole_sample_count (drillhole_id, source_system, n_intervals)
                 SELECT drillhole_id, %s, count(*) FROM geochem.sample_chemistry_wide
                 WHERE source_system = %s AND drillhole_id IS NOT NULL AND depth_to_m > depth_from_m GROUP BY 1""", (src, src))
    g.commit(); log(src, "hole x column rows", n, "holes", c.rowcount)
c.execute("ANALYZE drilling.hole_grade_max"); c.execute("ANALYZE drilling.hole_sample_count"); g.commit()
log("DONE")
