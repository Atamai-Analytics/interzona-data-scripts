"""Index and statistics maintenance for interzona_cm.

  python db_maintenance.py            report only: estimated btree bloat, invalid indexes, stale statistics
  python db_maintenance.py --apply    also REINDEX INDEX CONCURRENTLY each index with >= MIN_BLOAT_MB and >= MIN_BLOAT_PCT estimated bloat,
                                      then ANALYZE tables with many changes since their last analyze

REINDEX CONCURRENTLY keeps the table readable and writable; it needs room for one extra copy of the index while it runs and must run
outside a transaction (autocommit), which is why this is a script and not an MCP execute call. A failed rebuild leaves an invalid
'<name>_ccnew' index: the report lists invalid indexes so they can be dropped. Bloat is the standard pg_stats estimate (no pgstattuple
on the instance), so treat small percentages as noise. Re-run after big loads.
"""
import os, sys, time
import psycopg2

MIN_BLOAT_MB = 20
MIN_BLOAT_PCT = 20
ANALYZE_MIN_CHANGES = 10000
ANALYZE_MIN_FRACTION = 0.005

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:7.0f}s", *a, flush=True)


BLOAT_SQL = """
WITH b AS (
SELECT idxoid, nspname, idxname, bs*relpages::bigint AS real_size, bs*(relpages-est_pages_ff)::bigint AS bloat_size,
 100*(relpages-est_pages_ff)::float/nullif(relpages,0) AS bloat_pct
FROM (
 SELECT coalesce(1+ceil(reltuples/floor((bs-pageopqdata-pagehdr)*fillfactor/(100*(4+nulldatahdrwidth)::float))),0) AS est_pages_ff,
  bs, nspname, idxname, idxoid, relpages
 FROM (
  SELECT maxalign, bs, nspname, idxname, idxoid, reltuples, relpages, fillfactor, pagehdr, pageopqdata,
   (index_tuple_hdr_bm + maxalign - CASE WHEN index_tuple_hdr_bm%%maxalign=0 THEN maxalign ELSE index_tuple_hdr_bm%%maxalign END
    + nulldatawidth + maxalign - CASE WHEN nulldatawidth=0 THEN 0 WHEN nulldatawidth::integer%%maxalign=0 THEN maxalign ELSE nulldatawidth::integer%%maxalign END)::numeric AS nulldatahdrwidth
  FROM (
   SELECT n.nspname, i.idxname, i.idxoid, i.reltuples, i.relpages, i.fillfactor,
    current_setting('block_size')::numeric AS bs, 8 AS maxalign, 24 AS pagehdr, 16 AS pageopqdata,
    CASE WHEN max(coalesce(s.null_frac,0))=0 THEN 8 ELSE 8+((32+8-1)/8) END AS index_tuple_hdr_bm,
    sum((1-coalesce(s.null_frac,0))*coalesce(s.avg_width,1024)) AS nulldatawidth
   FROM pg_attribute a
   JOIN (SELECT idxname, reltuples, relpages, tbloid, idxoid, fillfactor,
          CASE WHEN indkey[i]=0 THEN idxoid ELSE tbloid END AS att_rel,
          CASE WHEN indkey[i]=0 THEN i ELSE indkey[i] END AS att_pos, tblname
         FROM (SELECT ci.relname idxname, ci.reltuples, ci.relpages, x.indrelid tbloid, x.indexrelid idxoid,
                 coalesce(substring(array_to_string(ci.reloptions,' ') from 'fillfactor=([0-9]+)')::smallint,90) fillfactor,
                 string_to_array(textin(int2vectorout(x.indkey)),' ')::int[] indkey, ct.relname tblname,
                 generate_series(1,x.indnatts) i
               FROM pg_index x JOIN pg_class ci ON ci.oid=x.indexrelid JOIN pg_class ct ON ct.oid=x.indrelid
               JOIN pg_am am ON am.oid=ci.relam
               WHERE am.amname='btree' AND ci.relpages>1000 AND x.indisvalid) idx_data) i
     ON a.attrelid=i.att_rel AND a.attnum=i.att_pos
   JOIN pg_class c ON c.oid=i.tbloid JOIN pg_namespace n ON n.oid=c.relnamespace
   JOIN pg_stats s ON s.schemaname=n.nspname AND s.tablename=i.tblname AND s.attname=a.attname
   GROUP BY 1,2,3,4,5,6) r1) r2) r3)
SELECT quote_ident(nspname)||'.'||quote_ident(idxname), real_size, bloat_size, bloat_pct FROM b
WHERE bloat_size >= %s AND bloat_pct >= %s ORDER BY bloat_size DESC
"""


def main():
    apply = "--apply" in sys.argv
    g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                         password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
    g.autocommit = True
    c = g.cursor()
    c.execute("SET statement_timeout = 0")
    c.execute("SET maintenance_work_mem = '1GB'")
    c.execute("SELECT pg_size_pretty(pg_database_size(current_database())), pg_size_pretty(sum(pg_relation_size(indexrelid))) FROM pg_stat_user_indexes")
    log("database / all indexes:", *c.fetchone())

    c.execute("SELECT indexrelid::regclass::text FROM pg_index WHERE NOT indisvalid")
    bad = [r[0] for r in c.fetchall()]
    log("invalid indexes:", bad or "none")

    c.execute(BLOAT_SQL, (MIN_BLOAT_MB * 1024 * 1024, MIN_BLOAT_PCT))
    targets = c.fetchall()
    log(f"{len(targets)} indexes with >= {MIN_BLOAT_MB} MB and >= {MIN_BLOAT_PCT}% estimated bloat, "
        f"{sum(t[2] for t in targets) / 1048576:,.0f} MB in total")
    for name, size, bloat, pct in targets:
        log(f"  {name}: {size / 1048576:,.0f} MB, ~{bloat / 1048576:,.0f} MB ({pct:.0f}%) bloat")

    c.execute("""SELECT quote_ident(schemaname)||'.'||quote_ident(relname), n_mod_since_analyze, n_live_tup FROM pg_stat_user_tables
                 WHERE n_mod_since_analyze >= %s AND n_mod_since_analyze >= %s * greatest(n_live_tup, 1) ORDER BY n_mod_since_analyze DESC""",
              (ANALYZE_MIN_CHANGES, ANALYZE_MIN_FRACTION))
    stale = c.fetchall()
    log(f"{len(stale)} tables to analyze:", ", ".join(f"{t} ({m:,} changes)" for t, m, _ in stale) or "none")

    if not apply:
        log("report only; run with --apply to rebuild and analyze")
        return

    saved = 0
    for name, size, _, _ in targets:
        s = time.time()
        try:
            c.execute(f"REINDEX INDEX CONCURRENTLY {name}")
        except Exception as e:
            log(f"  FAILED {name}: {e}")
            continue
        c.execute("SELECT pg_relation_size(%s::regclass)", (name,))
        after = c.fetchone()[0]
        saved += size - after
        log(f"  rebuilt {name}: {size / 1048576:,.0f} -> {after / 1048576:,.0f} MB in {time.time() - s:.0f}s")
    log(f"index space freed: {saved / 1048576:,.0f} MB")

    for t, _, _ in stale:
        s = time.time()
        c.execute(f"ANALYZE {t}")
        log(f"  analyzed {t} in {time.time() - s:.0f}s")

    c.execute("SELECT indexrelid::regclass::text FROM pg_index WHERE NOT indisvalid")
    log("invalid indexes after:", [r[0] for r in c.fetchall()] or "none")
    c.execute("SELECT pg_size_pretty(pg_database_size(current_database())), pg_size_pretty(sum(pg_relation_size(indexrelid))) FROM pg_stat_user_indexes")
    log("database / all indexes after:", *c.fetchone())


if __name__ == "__main__":
    main()
