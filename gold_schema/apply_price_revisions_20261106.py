"""2026-11-06 November price refresh, admin part (the app write role can only INSERT into markets.prices):
  1. apply the IMF's revisions of its August 2026 monthly averages (8 series, all under 0.4%) - old values saved to a rollback CSV first;
  2. set markets.price_series.last_period / n_observations from the rows actually stored, for every series that has prices.
Dry run by default; --apply to write. Rollback for 1: price_revisions_20261106_rollback.csv (price_id, old value)."""
import csv, os, sys, psycopg2

REVISIONS = [  # (source, source_series_code, period_start, value now published by the IMF) from refresh_prices.py's report
    ("IMF_PCPS", "PALUM", "2026-08-01", 3250.12142857142),
    ("IMF_PCPS", "PCOBA", "2026-08-01", 55854.3809523809),
    ("IMF_PCPS", "PGOLD", "2026-08-01", 4419.41571428571),
    ("IMF_PCPS", "PLEAD", "2026-08-01", 1855.72523809523),
    ("IMF_PCPS", "PNICK", "2026-08-01", 16748.1819047619),
    ("IMF_PCPS", "PSILVER", "2026-08-01", 65.3992857142857),
    ("IMF_PCPS", "PTIN", "2026-08-01", 55360.3095238095),
    ("IMF_PCPS", "PZINC", "2026-08-01", 3884.52619047619),
]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV.setdefault(k.strip(), v.strip())
conn = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                        user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
cur = conn.cursor()
APPLY = "--apply" in sys.argv

rows = []
for src, code, ps, new in REVISIONS:
    cur.execute("""SELECT p.price_id, p.value FROM markets.prices p JOIN markets.price_series s USING (series_id)
                   WHERE s.source = %s AND s.source_series_code = %s AND p.period_start = %s""", (src, code, ps))
    found = cur.fetchall()
    if len(found) != 1: sys.exit(f"expected 1 row for {src} {code} {ps}, found {len(found)}")
    pid, old = found[0]
    rows.append((pid, code, ps, float(old), new))
    print(f"{code:8s} {ps} {float(old):14.4f} -> {new:14.4f} ({(new / float(old) - 1) * 100:+.3f}%)")

cur.execute("""SELECT s.series_id, s.last_period, s.n_observations, max(p.period_end), count(p.*)
               FROM markets.price_series s JOIN markets.prices p USING (series_id)
               WHERE s.source IN ('IMF_PCPS', 'WORLD_BANK_PINK_SHEET') GROUP BY 1, 2, 3
               HAVING s.last_period IS DISTINCT FROM max(p.period_end) OR s.n_observations IS DISTINCT FROM count(p.*) ORDER BY 1""")
summ = cur.fetchall()
print(f"series summaries to update: {len(summ)}")
for sid, lp, n, mx, c in summ[:5]: print(f"  series {sid}: {lp} / {n} -> {mx} / {c}")

if APPLY:
    path = os.path.join(HERE, "price_revisions_20261106_rollback.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["price_id", "series_code", "period_start", "old_value", "new_value"]); w.writerows(rows)
    for pid, code, ps, old, new in rows:
        cur.execute("""UPDATE markets.prices SET value = %s,
                         note = concat_ws('; ', note, %s) WHERE price_id = %s""",
                    (new, f"revised 2026-11-06 to the IMF's published value (was {old})", pid))
    for sid, lp, n, mx, c in summ:
        cur.execute("UPDATE markets.price_series SET last_period = %s, n_observations = %s WHERE series_id = %s", (mx, c, sid))
    conn.commit(); print("committed; rollback CSV:", path)
conn.close()
