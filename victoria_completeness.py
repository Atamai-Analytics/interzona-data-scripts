import re, collections
import pandas as pd
pd.set_option("display.width", 220)
SRC = "D:/CriticalMineralsDB/Victoria/G172012_GSV_geochemistry-data-collection-state-wide/"
SP = "C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/68ebf155-9ef1-4f3d-9bc4-880fe468070d/scratchpad/"
SCRIPT = open("D:/CriticalMineralsDB/Scripts/VictoriaAssays.sql", encoding="utf-8", errors="replace").read()

def rd(name):
    return pd.read_csv(SRC + name, sep="|", quotechar='"', dtype=str, keep_default_na=False, na_values=[], encoding="latin1", low_memory=False)

# ---- quanttype list and analyte CASE from the loader script (only the INSERT block)
ins = SCRIPT[SCRIPT.index("insert into analytical_results"):]
case_types = set(re.findall(r"when t1\.quanttype = '([^']+)' then", ins))
wh = ins[ins.index("where quanttype in ("):]
wh = wh[:wh.index(")")]
where_types = set(re.findall(r"^\s*'([^']+)'", wh, flags=re.M))
unit_ok = set(re.findall(r"when t1\.unitcd = '([^']+)' then", ins))
print(f"quanttypes in CASE: {len(case_types)}, in WHERE list: {len(where_types)}, both: {len(case_types & where_types)}; units handled: {sorted(unit_ok)}")
types_ok = case_types & where_types

ga = rd("gsiteassay.txt"); gam = rd("gsiteassaymethod.txt"); m = rd("gsiteanmethod.txt"); mc = rd("gsiteanmethodclass.txt"); gcs = rd("gsitegcsample.txt")
print("source rows: assay", len(ga), "| assay-method", len(gam), "| methods", len(m), "| method-class", len(mc), "| gc samples", len(gcs))
print("assay columns:", list(ga.columns))
ga = ga[~ga.REPEATCD.isin(["R1", "R2", "R3"])]
print("after repeat filter:", len(ga), "| repeat codes in source:", dict(rd("gsiteassay.txt").REPEATCD.value_counts().head(6)))
# ---- inner joins as in the loader
j = ga.merge(gam[["ASSAYID", "METHODSEQNO"]], left_on="ID", right_on="ASSAYID")            # on assay id alone, as written
j = j.merge(m[["METHODSEQNO", "LABCD", "METHODCD", "METHODDESC"]], on="METHODSEQNO")
j = j.merge(mc[[c for c in mc.columns if c in ("METHODSEQNO", "METHODCLASS")]].drop_duplicates(), on="METHODSEQNO", how="left")
key = ["SITEID", "ID", "GCSAMPLEID", "QUANTVAL", "QUANTTYPE", "UNITCD"]
def agg(col, absent):
    def f(s):
        v = frozenset(x for x in s.dropna().unique() if x != "")
        return v if v else frozenset([absent])
    return f
t1 = j.groupby(key, sort=False).agg(lab=("LABCD", agg("LABCD", "Not Recorded")), code=("METHODCD", agg("METHODCD", "Not Recorded")),
                                    desc=("METHODDESC", agg("METHODDESC", "Not Recorded")), cls=("METHODCLASS", agg("METHODCLASS", "Not Recorded"))).reset_index()
print("distinct (assay) rows after method joins & group:", len(t1))
# ---- mapping workbook (Sheet2): sets of values
vm = pd.read_excel("D:/CriticalMineralsDB/Victoria/AssayMapping.xlsx", sheet_name="Sheet2", dtype=str).fillna("")
def sset(x, sep):
    v = frozenset(p.strip() for p in str(x).split(sep) if p.strip() != "")
    return v if v else frozenset(["Not Recorded"])
vm["lab"] = vm.laboratory_names.map(lambda x: sset(x, ", ")); vm["code"] = vm.method_codes.map(lambda x: sset(x, ", "))
vm["desc"] = vm.method_descriptions.map(lambda x: sset(x, " | ")); vm["cls"] = vm.method_classes.map(lambda x: sset(x, ", "))
vm = vm[vm.package_code != ""]
vm["k"] = list(zip(vm.lab, vm.code, vm.desc, vm.cls)); t1["k"] = list(zip(t1.lab, t1.code, t1.desc, t1.cls))
mp = vm[["k", "package_code"]].drop_duplicates()
print("mapping rows:", len(vm), "| distinct keys:", mp.k.nunique())
t2 = t1.merge(mp, on="k")
print("assays matching a mapping row:", len(t2), "of", len(t1), f"({len(t1)-len(t2)} unmapped)")
t2 = t2[t2.QUANTTYPE.isin(types_ok) & t2.UNITCD.isin(unit_ok)]
print("after quanttype/unit filters:", len(t2))
t3 = t2.merge(gcs[["SITEID", "ID", "ORIGID"]].rename(columns={"ID": "GCSAMPLEID"}), on=["SITEID", "GCSAMPLEID"])
print("with a gc sample record:", len(t3))
dbs = pd.read_csv(SP + "vic_db_samples.csv", dtype=str)
dbs = dbs[(dbs.countryid == "26") & (dbs.divisionid == "82")]
print("DB Victoria samples (country 26 / division 82):", len(dbs))
t4 = t3.merge(dbs, left_on=["GCSAMPLEID", "ORIGID"], right_on=["samplenumber", "fieldid"])
print("EXPECTED result rows (one per assay x matching DB sample):", len(t4))
exp_pkg = t4.groupby("package_code").size().rename("expected")
db = pd.read_csv(SP + "vic_db_by_package.csv").set_index("package_code")
db["db_minus_my_dedupe"] = db.total_rows - db.deduped_by_me
cmp = pd.concat([exp_pkg, db[["total_rows", "deduped_by_me", "db_minus_my_dedupe"]]], axis=1).fillna(0).astype(int)
cmp["diff_db_minus_expected"] = cmp.db_minus_my_dedupe - cmp.expected
print("\nTOTAL expected", int(cmp.expected.sum()), "| DB total", int(cmp.total_rows.sum()), "| DB minus the 20,000 I deactivated", int(cmp.db_minus_my_dedupe.sum()), "| difference", int(cmp.diff_db_minus_expected.sum()))
print("packages where DB != expected:", int((cmp.diff_db_minus_expected != 0).sum()), "of", len(cmp))
print(cmp[cmp.diff_db_minus_expected != 0].sort_values("diff_db_minus_expected").to_string())
t4.to_pickle(SP + "vic_expected.pkl")
