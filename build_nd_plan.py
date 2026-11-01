#!/usr/bin/env python3
"""Plan for GEUS ND rows (Rock / HMC / Soil, elements AND oxides): operator ND, concentration blank, detection limit =
  1. the lowest '<' limit reported in the source data for the same dataset + method + element/oxide (the 10,000 placeholders excluded), else
  2. the Actlabs 2026 catalogue lower limit (elements only; INAA 1D and fusion ICP-MS 4B2-Std, see actlabs_catalogue_limits.py), else
  3. none (the row still gets the ND operator).
Read-only; writes lt_conc_backups/nd_plan.csv  (result_id, dataset, kind, aliquotName, name, method_code, limit, basis).
"""
import csv, os, subprocess, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
SP = Path("C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/1f36e5e8-d7fa-4410-8209-17c5fcae5797/scratchpad")
SP.mkdir(parents=True, exist_ok=True)

# 1. every ND row of the six GEUS load files
rows = []
for ds in ("rock", "hmc", "soil"):
    for kind, fn, namef in (("elem", f"elem_{ds}.tsv", "element_symbol"), ("oxide", f"oxide_{ds}.tsv", "element_oxide")):
        for r in csv.DictReader(open(HERE / fn, encoding="utf-8"), delimiter="\t"):
            if r["qualifier_code"] == "ND":
                rows.append((r["result_id"], ds, kind, r["aliquotName"], r[namef]))
ids = pd.DataFrame(rows, columns=["result_id", "dataset", "kind", "aliquotName", "name"])
ids["result_id"] = ids.result_id.astype("int64")
print("ND rows in the load files:", len(ids), ids.groupby(["dataset", "kind"]).size().to_dict())
ids[["result_id"]].to_csv(SP / "nd_result_ids.txt", index=False, header=False)

# 2. method (package_code) of each result from the database
sql = f"""\\set ON_ERROR_STOP on
create temp table ids(result_id bigint primary key);
\\copy ids from '{(SP / 'nd_result_ids.txt').as_posix()}'
\\copy (select i.result_id, ap.package_code from ids i join analytical_results ar on ar.result_id=i.result_id left join analytical_packages ap on ap.package_id=ar.package_id) to '{(SP / 'nd_methods.csv').as_posix()}' csv header
"""
(SP / "nd_methods.sql").write_text(sql, encoding="utf-8")
env = dict(os.environ)
for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip().strip("\"'"))
env["PGPASSWORD"] = env["LITHODAT_DB_PASSWORD"]
out = subprocess.run([r"C:\Program Files\QGIS 4.0.1\bin\psql.exe", "-h", env["LITHODAT_DB_HOST"], "-p", env["LITHODAT_DB_PORT"], "-U", env["LITHODAT_DB_USER"],
                      "-d", env["LITHODAT_DB_NAME"], "-f", str(SP / "nd_methods.sql")], capture_output=True, text=True, env=env)
if out.returncode:
    sys.exit(out.stderr)
m = pd.read_csv(SP / "nd_methods.csv")
ids = ids.merge(m.rename(columns={"package_code": "method_code"}), on="result_id", how="left")
print("rows with a method:", int(ids.method_code.notna().sum()), "of", len(ids))

# 3. limits
el = pd.read_csv(HERE / "geus_nd_by_element_method_with_catalogue.csv")
el = el.rename(columns={"element": "name"})
el["data_limit"] = el.min_limit_excl_10000_placeholder
el["cat_limit"] = el.catalogue_lower_limit_ppm
el = el[["dataset", "name", "method_code", "data_limit", "cat_limit", "catalogue_code_used"]]
ox = pd.read_csv(HERE / "geus_method_detection_limits.csv")
ox = ox[ox.kind == "oxide"].rename(columns={"analyte_code": "name", "package_code": "method_code"})
ox["data_limit"] = ox.min_limit.where(ox.min_limit != 10000)
ox["cat_limit"] = float("nan")
ox["catalogue_code_used"] = None
ox = ox[["dataset", "name", "method_code", "data_limit", "cat_limit", "catalogue_code_used"]]
lim = pd.concat([el.assign(kind="elem"), ox.assign(kind="oxide")])
p = ids.merge(lim, on=["dataset", "kind", "name", "method_code"], how="left")
p["limit"] = p.data_limit.where(p.data_limit.notna(), p.cat_limit)
p["basis"] = "none"
p.loc[p.cat_limit.notna(), "basis"] = "catalogue"
p.loc[p.data_limit.notna(), "basis"] = "data"
p.loc[p.basis == "catalogue", "basis"] = "catalogue " + p.catalogue_code_used.astype(str)
p = p[["result_id", "dataset", "kind", "aliquotName", "name", "method_code", "limit", "basis"]]
(HERE / "lt_conc_backups").mkdir(exist_ok=True)
p.to_csv(HERE / "lt_conc_backups" / "nd_plan.csv", index=False)
print("\nplan rows:", len(p))
print(p.groupby(["kind", p.basis.str.split(" ").str[0]]).size().to_string())
print("rows with a limit:", int(p.limit.notna().sum()), f"({p.limit.notna().mean():.0%})", "| aliquots:", p.aliquotName.nunique())
print("limit range:", float(p.limit.min()), "-", float(p.limit.max()), "| rows with limit > 1000:", int((p.limit > 1000).sum()))
print(p[p.limit > 1000].groupby(["method_code", "name"]).size().sort_values(ascending=False).head(8).to_string())
