"""Verification after the UNK-CV deactivation + USGS wide rebuild (READ-ONLY)."""
import csv, os, time
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 600000")


def q(label, sql, p=None):
    t = time.time(); c.execute(sql, p); r = c.fetchall(); print(f"\n[{round(time.time() - t, 1)}s] {label}")
    for x in r: print("  ", x)
    return r


ids = [int(r["sample_id"]) for r in csv.DictReader(open(os.path.join(HERE, "_unk_cv_deactivated_ids.csv"), encoding="utf-8"))]
sids = sorted(set(ids))
q("affected samples (6,470): wide values for the old UNK-CV analytes, now", """SELECT count(*) samples, count(ni_p) ni_p, count(co_p) co_p, count(zn_p) zn_p, count(as_p) as_p, count(sb_p) sb_p, count(w_p) w_p, count(cr_p) cr_p,
   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ni_p)::numeric, 1) med_ni_p, round(max(ni_p)::numeric) max_ni_p, round(max(w_p)::numeric) max_w_p, round(max(cr_p)::numeric) max_cr_p
   FROM geochem.sample_chemistry_wide WHERE sample_id = ANY(%s)""", (sids,))
q("USGS W_p by sample type (was: drill core median 50,000 ppm)", """SELECT sample_type_name, count(w_p) n, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY w_p)::numeric, 1) med, round(max(w_p)::numeric) mx
   FROM geochem.sample_chemistry_wide WHERE source_system = 'USA_USGS_NGDB' AND w_p IS NOT NULL GROUP BY 1 HAVING count(w_p) >= 100 ORDER BY 2 DESC LIMIT 6""")
q("USGS max of the formerly inflated _p columns, overall (was cr_p 300,000+, ni_p 400,000, sb_p 400,000)", """SELECT round(max(cr_p)::numeric) cr_p, round(max(ni_p)::numeric) ni_p, round(max(sb_p)::numeric) sb_p, round(max(co_p)::numeric) co_p, round(max(w_p)::numeric) w_p, round(max(as_p)::numeric) as_p, round(max(zn_p)::numeric) zn_p
   FROM geochem.sample_chemistry_wide WHERE source_system = 'USA_USGS_NGDB'""")
q("USGS p99.9 of those columns for rock-like samples", """SELECT round(percentile_cont(0.999) WITHIN GROUP (ORDER BY ni_p)::numeric) ni_p, round(percentile_cont(0.999) WITHIN GROUP (ORDER BY cr_p)::numeric) cr_p, round(percentile_cont(0.999) WITHIN GROUP (ORDER BY w_p)::numeric) w_p
   FROM geochem.sample_chemistry_wide WHERE source_system = 'USA_USGS_NGDB' AND sample_type_name ILIKE '%rock%'""")
q("Other sources untouched (row counts)", """SELECT source_system, count(*) FROM geochem.sample_chemistry_wide GROUP BY 1 ORDER BY 2 DESC""")
q("active UNK-CV results left (must be 0) / log rows", """SELECT (SELECT count(*) FROM geochem.analytical_results WHERE source_system = 'USA_USGS_NGDB' AND package_id = 138 AND is_active),
   (SELECT count(*) FROM geochem.result_active_reconcile_log WHERE reason LIKE 'claude_unk_cv_20261030%')""")
