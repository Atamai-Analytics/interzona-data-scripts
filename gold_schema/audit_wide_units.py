"""Part C of the wide-table audit, from the saved audit CSV (no database access).
For each element column and category (rock-like / sediment-soil-like), compares a source's n-weighted median with the median of the other sources' medians.
A ratio >= 50 or <= 1/50 over >= 200 values, with at least 2 other sources, is a candidate unit shift or a population problem.
Also lists, per source, the columns whose sample types disagree most with each other (candidate mis-typed samples, as with Victoria's panned concentrates)."""
import glob, math, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
f = sorted(glob.glob(os.path.join(HERE, "audit_wide_outliers_2*.csv")))[-1]
df = pd.read_csv(f)
E = df[(df.kind == "element_ppm") & (df.n >= 100)].copy()


def category(st):
    s = (st or "").lower()
    if any(k in s for k in ("rock", "core", "outcrop", "drill", "float", "channel")): return "rock-like"
    if any(k in s for k in ("sediment", "soil", "horizon", "auger", "till")): return "sediment/soil-like"
    return "other"


E["cat"] = E["sample_type"].map(category)
E["wm"] = E["median"] * E["n"]
M = E[E.cat != "other"].groupby(["column", "cat", "source"], as_index=False).agg(wm=("wm", "sum"), n=("n", "sum"))
M["med"] = M["wm"] / M["n"]
rows = []
for (col, cat), grp in M.groupby(["column", "cat"]):
    if len(grp) < 3:
        continue
    for r in grp.itertuples():
        others = grp[grp.source != r.source]["med"]
        others = others[others > 0]
        if r.med <= 0 or len(others) < 2 or r.n < 200:
            continue
        ref = others.median()
        ratio = r.med / ref
        if ratio >= 50 or ratio <= 0.02:
            rows.append(dict(column=col, cat=cat, source=r.source, n=int(r.n), source_median=round(r.med, 4), others_median=round(ref, 4), ratio=round(ratio, 3)))
C = pd.DataFrame(rows)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
if len(C):
    C["abs_log"] = np.abs(np.log10(C.ratio.clip(lower=1e-6)))
    C = C.sort_values("abs_log", ascending=False)
    C.drop(columns="abs_log").to_csv(f.replace(".csv", "_unit_shifts.csv"), index=False)
    print(f"=== C. cross-source shifts: {len(C)} candidates (top 45 by size of shift) ===")
    print(C.drop(columns="abs_log").head(45).to_string(index=False))
    print("\ncandidates per source:", C.source.value_counts().to_dict())
else:
    print("no cross-source shifts found")

# D. within a source, a sample type whose median is wildly different from the other types of the same category (mixed populations)
D = []
for (src, col, cat), grp in E[E.cat != "other"].groupby(["source", "column", "cat"]):
    if len(grp) < 2:
        continue
    for r in grp.itertuples():
        others = grp[grp.sample_type != r.sample_type]
        others = others[others["median"] > 0]
        if r.median <= 0 or len(others) < 1 or r.n < 200:
            continue
        ref = others["median"].median()
        ratio = r.median / ref
        if (ratio >= 100 or ratio <= 0.01):
            D.append(dict(source=src, column=col, cat=cat, sample_type=r.sample_type, n=r.n, median=round(r.median, 3), other_types_median=round(ref, 3), ratio=round(ratio, 2)))
D = pd.DataFrame(D)
if len(D):
    D["abs_log"] = np.abs(np.log10(D.ratio.clip(lower=1e-6)))
    D = D.sort_values("abs_log", ascending=False)
    print(f"\n=== D. within-source sample-type outliers: {len(D)} (top 40) ===")
    print(D.drop(columns="abs_log").head(40).to_string(index=False))
    D.drop(columns="abs_log").to_csv(f.replace(".csv", "_type_outliers.csv"), index=False)
    print("\nby source / sample type:", D.groupby(["source", "sample_type"]).size().sort_values(ascending=False).head(15).to_dict())
