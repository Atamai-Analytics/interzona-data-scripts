#!/usr/bin/env python3
"""Build the plan to replace the estimated Victoria soil '<' limits with GSV's own method-level detection limits.

Source: gsiteanmethod.DETECTIONLIMIT / DETECTLIMITUNIT, reached through gsiteassaymethod (ASSAYID -> METHODSEQNO).
Every '<' result in LithoSurfer (the 94,737 in elem_victoria_soil.tsv) is matched to its source assay through the expected-rows table of
victoria_completeness.py (sampleid + package + analyte); the DL is converted to ppm (the unit LithoSurfer holds).
Read-only; writes victoria_dl_plan.csv (+ a review CSV of unmatched / ambiguous rows) to the scratchpad.
"""
import re
import numpy as np
import pandas as pd

pd.set_option("display.width", 200)
SP = "C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/68ebf155-9ef1-4f3d-9bc4-880fe468070d/scratchpad/"
SRC = "D:/CriticalMineralsDB/Victoria/G172012_GSV_geochemistry-data-collection-state-wide/"
HERE = "C:/Users/dean/claude_lithosurfer/lithosurfer-work/"


def rd(name):
    return pd.read_csv(SRC + name, sep="|", quotechar='"', dtype=str, keep_default_na=False, na_values=[], encoding="latin1", low_memory=False)


# quanttype -> analyte_id from the loader SQL
sql = open("D:/CriticalMineralsDB/Scripts/VictoriaAssays.sql", encoding="utf-8", errors="replace").read()
ins = sql[sql.index("insert into analytical_results"):]
qt2an = {q: int(a) for q, a in re.findall(r"when t1\.quanttype = '([^']+)' then (\d+)", ins)}
print("quanttype -> analyte mappings:", len(qt2an))

# DL per source assay (the method row that carries it; 0 assays have two different DLs)
m = rd("gsiteanmethod.txt"); gam = rd("gsiteassaymethod.txt")
mm = m[["METHODSEQNO", "DETECTIONLIMIT", "DETECTLIMITUNIT"]].copy()
mm["dl"] = pd.to_numeric(mm.DETECTIONLIMIT, errors="coerce")
j = gam[["ASSAYID", "METHODSEQNO"]].merge(mm, on="METHODSEQNO")
j = j[j.dl.notna()].drop_duplicates(["ASSAYID", "dl", "DETECTLIMITUNIT"])
multi = j.groupby("ASSAYID").size()
print("assays carrying >1 distinct (DL, unit):", int((multi > 1).sum()))
j = j.drop_duplicates("ASSAYID").rename(columns={"ASSAYID": "ID", "DETECTLIMITUNIT": "dl_unit"})[["ID", "dl", "dl_unit"]]

t4 = pd.read_pickle(SP + "vic_expected.pkl")
print("expected rows:", len(t4), "| columns:", [c for c in t4.columns if c not in ("lab", "code", "desc", "cls", "k")])
bdl = t4[t4.QUANTVAL == ""].copy()
print("expected rows that are below-detection (empty QUANTVAL):", len(bdl))
bdl = bdl.merge(j, on="ID", how="left")
bdl["analyte_id"] = bdl.QUANTTYPE.map(qt2an)
fac = {"ppm": 1.0, "ppb": 0.001, "%": 10000.0}
bdl["dl_ppm"] = bdl.dl * bdl.dl_unit.map(fac)
print("BDL expected rows with DL:", int(bdl.dl.notna().sum()), "| unit of DL:", dict(bdl.dl_unit.value_counts(dropna=False)))
bdl["sampleid"] = bdl.sampleid.astype(int)

db = pd.read_csv(SP + "vic_lt_db.csv")
print("DB '<' results:", len(db), "| active:", int(db.isactive.sum() if db.isactive.dtype != object else (db.isactive == "t").sum()))
key = ["sampleid", "package_code", "analyte_id"]
agg = bdl.groupby(key).agg(n_src=("ID", "size"), n_dl=("dl_ppm", lambda s: s.nunique(dropna=False)), dl_min=("dl_ppm", "min"), dl_max=("dl_ppm", "max")).reset_index()
d = db.merge(agg, on=key, how="left")
d["n_db"] = d.groupby(key).result_id.transform("size")
print("\nDB '<' rows matched to a source BDL assay:", int(d.n_src.notna().sum()), "of", len(d))
print("  unmatched:", int(d.n_src.isna().sum()))
ok = d[d.n_src.notna()]
print("  one source DL for the key (n_dl == 1):", int((ok.n_dl == 1).sum()), "| several different DLs for the key:", int((ok.n_dl > 1).sum()))
print("  DL missing (source assay without a method DL):", int(ok.dl_min.isna().sum()))
print("  DB rows per key vs source assays per key differ:", int((ok.n_db != ok.n_src).sum()))

# compare with the estimates currently stored
ld = pd.read_csv(HERE + "elem_victoria_soil.tsv", sep="\t", dtype=str)
ld = ld[ld.qualifier_code == "<"][["result_id", "datapointName", "aliquotName", "element_symbol", "Conc"]]
ld["result_id"] = ld.result_id.astype(int)
ld["old_est"] = pd.to_numeric(ld.Conc, errors="coerce")
d = d.merge(ld, on="result_id", how="left")
d["new_dl"] = np.where((d.n_dl == 1) & d.dl_min.notna(), d.dl_min, np.nan)
cmp_ = d[d.new_dl.notna() & d.old_est.notna()]
r = cmp_.old_est / cmp_.new_dl
print("\nwhere both exist (%d rows): old estimate / new GSV DL: equal (within 1%%) %d | estimate lower %d | estimate higher %d" % (
    len(cmp_), int(((r > 0.99) & (r < 1.01)).sum()), int((r <= 0.99).sum()), int((r >= 1.01).sum())))
print("  ratio quantiles:", {q: round(float(r.quantile(q)), 3) for q in (0.05, 0.25, 0.5, 0.75, 0.95)})
print("  rows with no old value that get a new DL:", int((d.new_dl.notna() & d.old_est.isna()).sum()))

plan = d[d.new_dl.notna()][["result_id", "aliquotName", "element_symbol", "old_est", "new_dl"]]
plan.to_csv(SP + "victoria_dl_plan.csv", index=False)
rest = d[d.new_dl.isna()][["result_id", "aliquotName", "element_symbol", "old_est", "n_src", "n_dl", "dl_min", "dl_max"]]
rest.to_csv(SP + "victoria_dl_plan_unresolved.csv", index=False)
print("\nplan rows:", len(plan), "| unresolved rows:", len(rest), "| plan aliquots:", plan.aliquotName.nunique())
print("unresolved by reason: no source match", int(d.n_src.isna().sum()), "| ambiguous DLs", int(((d.n_dl > 1) & d.n_src.notna()).sum()))
