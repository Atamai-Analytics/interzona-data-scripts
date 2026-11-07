"""2026-11-06: USGS DS140 nickel unit-value series 267 (nominal $/t) and 268 (1998 $/t) said n_observations 121 but hold 120 rows (1900-2019).
The source file ds140-nickel-2019.xlsx lists 2019 TWICE with different values (11,900 / 7,570 and 13,800 / 8,670; the second row has lower
production and consumption and may really be 2020, but the file does not say so and we cannot confirm it). The load kept the first row.
This sets n_observations from the stored rows and notes the duplicate on both 2019 rows. Dry run by default; --apply to write.
Rollback: UPDATE markets.price_series SET n_observations = 121 WHERE series_id IN (267, 268); and remove the note."""
import os, sys, psycopg2

NOTES = {
    267: "The USGS DS140 nickel file (May 2024) lists 2019 twice: 11,900 (kept here) and 13,800 $/t; the second row has lower production and consumption and may be 2020, unconfirmed.",
    268: "The USGS DS140 nickel file (May 2024) lists 2019 twice: 7,570 (kept here) and 8,670 1998$/t; the second row has lower production and consumption and may be 2020, unconfirmed.",
}
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV.setdefault(k.strip(), v.strip())
conn = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                        user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
cur = conn.cursor()
for sid, note in NOTES.items():
    cur.execute("SELECT n_observations, (SELECT count(*) FROM markets.prices WHERE series_id = %s) FROM markets.price_series WHERE series_id = %s", (sid, sid))
    n_summary, n_rows = cur.fetchone()
    cur.execute("SELECT price_id, value, note FROM markets.prices WHERE series_id = %s AND period_start = '2019-01-01'", (sid,))
    p = cur.fetchall()
    print(f"series {sid}: summary {n_summary}, rows {n_rows}; 2019 rows {p}")
    if len(p) != 1: sys.exit("expected exactly one 2019 row")
    if "--apply" in sys.argv:
        cur.execute("UPDATE markets.price_series SET n_observations = %s WHERE series_id = %s", (n_rows, sid))
        if not (p[0][2] or "").startswith("The USGS DS140 nickel file"):
            cur.execute("UPDATE markets.prices SET note = concat_ws('; ', %s, note) WHERE price_id = %s", (note, p[0][0]))
if "--apply" in sys.argv:
    conn.commit(); print("committed")
conn.close()
