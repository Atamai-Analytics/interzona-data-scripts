"""Outlier / unit audit of geochem.sample_chemistry_wide (READ-ONLY).

Per element column (<symbol>_t total, <symbol>_p partial; ppm) x source_system x sample_type_name (>= 30 values) it records n, median, p99, p99.9, max and the number of
impossible values (> 1,000,000 ppm); per oxide / wt% column it counts values > 100.  Output: audit_wide_outliers_<date>.csv (all groups) and a printed shortlist of
  A. impossible values;
  B. groups whose maximum or p99.9 is far above anything plausible for the element or far above the group's own bulk (max/p99.9, p99.9/median);
  C. cross-source unit shifts: for the same element and basis, a source whose median (rock-like or sediment/soil-like samples) is >= 50x or <= 1/50 of the others'.
Usage: python audit_wide_outliers.py
"""
import os, re, sys, time, datetime
import pandas as pd
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
OUT = os.path.join(HERE, f"audit_wide_outliers_{datetime.date.today():%Y%m%d}.csv")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 300000")
c.execute("""SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'geochem' AND table_name = 'sample_chemistry_wide'
             AND data_type IN ('numeric', 'double precision', 'real', 'integer', 'bigint') ORDER BY ordinal_position""")
cols = c.fetchall()
SKIP = {"sample_id", "occurrence_id", "lat", "lon", "n_values"}
elem = [n for n, t in cols if re.fullmatch(r"[a-z]{1,2}_[tp]", n)]
other = [n for n, t in cols if n not in elem and n not in SKIP]
log("element columns", len(elem), "| other numeric columns (oxides wt%, carbon, loi ...)", len(other), other[:40])

rows = []
for i, col in enumerate(elem + other):
    is_elem = col in elem
    c.execute(f"""SELECT source_system, sample_type_name, count({col}) AS n,
                  (percentile_cont(ARRAY[0.5, 0.99, 0.999]) WITHIN GROUP (ORDER BY {col}::float8)) AS pc, max({col}::float8) AS mx,
                  count(*) FILTER (WHERE {col} > {1000000 if is_elem else 100}) AS n_over
                  FROM geochem.sample_chemistry_wide WHERE {col} IS NOT NULL GROUP BY 1, 2 HAVING count({col}) >= 30""")
    for src, st, n, pc, mx, n_over in c.fetchall():
        rows.append(dict(column=col, kind="element_ppm" if is_elem else "wt_pct_or_other", source=src, sample_type=st, n=n, median=pc[0], p99=pc[1], p999=pc[2], max=mx, n_over_limit=n_over))
    if i % 25 == 24:
        log(f"{i + 1}/{len(elem) + len(other)} columns")
df = pd.DataFrame(rows)
df.to_csv(OUT, index=False)
log("groups recorded", len(df), "->", OUT)

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200); pd.set_option("display.max_colwidth", 40)
fmt = lambda d: d.assign(median=d["median"].round(3), p99=d["p99"].round(2), p999=d["p999"].round(1), max=d["max"].round(1))

print("\n=== A. IMPOSSIBLE VALUES (element > 1,000,000 ppm, or wt% column > 100) ===")
A = df[df.n_over_limit > 0].sort_values("n_over_limit", ascending=False)
print(fmt(A)[["column", "source", "sample_type", "n", "n_over_limit", "median", "max"]].head(40).to_string(index=False))

print("\n=== B. EXTREME TAILS (element columns; n >= 100): max > 100 x p99.9, or p99.9 > 1000 x median, with max > 100 ppm ===")
E = df[(df.kind == "element_ppm") & (df.n >= 100)].copy()
E["max_over_p999"] = E["max"] / E["p999"].replace(0, float("nan"))
E["p999_over_median"] = E["p999"] / E["median"].replace(0, float("nan"))
B = E[((E.max_over_p999 > 100) | (E.p999_over_median > 1000)) & (E["max"] > 100)].sort_values("max", ascending=False)
print(fmt(B)[["column", "source", "sample_type", "n", "median", "p999", "max", "max_over_p999"]].head(40).to_string(index=False))

print("\n=== C. CROSS-SOURCE UNIT SHIFTS (same column, rock-like and sediment/soil-like samples; source median vs median of the other sources' medians) ===")
def category(st):
    s = (st or "").lower()
    if any(k in s for k in ("rock", "core", "outcrop", "drill", "float", "channel")): return "rock-like"
    if any(k in s for k in ("sediment", "soil", "horizon", "auger", "till")): return "sediment/soil-like"
    return "other"
E["cat"] = E["sample_type"].map(category)
M = E[E.cat != "other"].groupby(["column", "cat", "source"]).apply(lambda d: pd.Series({"med": (d["median"] * d["n"]).sum() / d["n"].sum(), "n": d["n"].sum()})).reset_index()
rowsC = []
for (colname, cat), grp in M.groupby(["column", "cat"]):
    if len(grp) < 3: continue
    for r in grp.itertuples():
        others = grp[grp.source != r.source]["med"]
        others = others[others > 0]
        if r.med <= 0 or len(others) < 2: continue
        ref = others.median()
        ratio = r.med / ref
        if (ratio >= 50 or ratio <= 0.02) and r.n >= 200:
            rowsC.append(dict(column=colname, cat=cat, source=r.source, n=int(r.n), source_median=round(r.med, 4), others_median=round(ref, 4), ratio=round(ratio, 3)))
C = pd.DataFrame(rowsC)
print(C.sort_values("ratio", key=lambda s: (s.map(lambda x: abs(__import__("math").log10(x))))).tail(40).to_string(index=False) if len(C) else "none")
C.to_csv(OUT.replace(".csv", "_unit_shifts.csv"), index=False)
log("done")
