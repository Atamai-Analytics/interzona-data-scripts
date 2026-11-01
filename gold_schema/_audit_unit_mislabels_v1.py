"""Unit-label audit on the LONG table (geochem.analytical_results; READ-ONLY).

For every source x element x lab package x unit group with >= 30 active, positive values it takes the median. Within a source and element, groups whose median is far from the
n-weighted median of ALL the other groups of that element (ratio >= 30 or <= 1/30) are candidates; if the ratio is close (within x3) to a power of ten
(1e3 / 1e4 / 1e6 and inverses) the likely cause is a unit label that does not match the numbers (for example % entered as ppm, ppb entered as ppm).
Output: audit_unit_mislabels_<date>.csv + a printed shortlist per source.  Usage: python audit_unit_mislabels.py
"""
import datetime, math, os, re, time
import numpy as np
import pandas as pd
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
OUT = os.path.join(HERE, f"audit_unit_mislabels_{datetime.date.today():%Y%m%d}.csv")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 1800000"); c.execute("SET work_mem = '256MB'")
t = time.time()
c.execute("""SELECT r.source_system, r.analyte_symbol, r.package_id, r.unit_code, count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value) AS med,
             percentile_cont(0.99) WITHIN GROUP (ORDER BY r.value) AS p99
             FROM geochem.analytical_results r
             WHERE r.is_active AND r.value > 0 AND r.unit_code IN ('ppm', 'ppb', '%', 'mg/kg') AND r.analyte_symbol ~ '^[A-Z][a-z]?$'
             GROUP BY 1, 2, 3, 4 HAVING count(*) >= 30""")
rows = c.fetchall()
print(f"[{round(time.time() - t)}s] groups:", len(rows), flush=True)
df = pd.DataFrame(rows, columns=["source", "analyte", "package_id", "unit", "n", "med", "p99"]).astype({"n": int, "med": float, "p99": float})
c.execute("SELECT package_id, package_code FROM geochem.analytical_packages")
pk = dict(c.fetchall())
df["package"] = df.package_id.map(pk)
# normalise to ppm for comparing medians; keep the label
f = {"ppm": 1.0, "mg/kg": 1.0, "ppb": 1e-3, "%": 1e4}
df["med_ppm_as_labelled"] = df["med"] * df["unit"].map(f)       # what the wide table uses
out = []
for (src, an), grp in df.groupby(["source", "analyte"]):
    if len(grp) < 3:
        continue
    for r in grp.itertuples():
        oth = grp[(grp.package_id != r.package_id) | (grp.unit != r.unit)]
        if oth.n.sum() < 200:
            continue
        # n-weighted median of the other groups' medians (as labelled)
        o = oth.sort_values("med_ppm_as_labelled"); cum = o.n.cumsum() / o.n.sum()
        ref = float(o.med_ppm_as_labelled[cum >= 0.5].iloc[0])
        if ref <= 0 or r.med_ppm_as_labelled <= 0:
            continue
        ratio = r.med_ppm_as_labelled / ref
        if ratio >= 30 or ratio <= 1 / 30:
            k = math.log10(ratio)
            near = [p for p in (-6, -4, -3, 3, 4, 6) if abs(k - p) <= 0.5]
            out.append(dict(source=r.source, analyte=r.analyte, package=r.package, unit=r.unit, n=r.n, median_as_labelled_ppm=round(r.med_ppm_as_labelled, 4), others_median_ppm=round(ref, 4),
                            ratio=round(ratio, 4), log10_ratio=round(k, 2), power_of_ten_fix=(f"x1e{-near[0]} would fit" if near else "")))
O = pd.DataFrame(out)
O.to_csv(OUT, index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300); pd.set_option("display.max_colwidth", 28)
print("candidates:", len(O), "| by source:", O.source.value_counts().to_dict() if len(O) else {})
print("with a power-of-ten explanation:", int((O.power_of_ten_fix != "").sum()) if len(O) else 0)
if len(O):
    O["abs"] = O.log10_ratio.abs()
    for src, d in O[O.power_of_ten_fix != ""].sort_values("n", ascending=False).groupby("source"):
        print(f"\n=== {src}: power-of-ten candidates (largest groups first) ===")
        print(d.head(25).drop(columns="abs").to_string(index=False))
print("\nsaved", OUT)
