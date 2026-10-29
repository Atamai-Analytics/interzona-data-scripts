#!/usr/bin/env python3
r"""Plan for the GEUS '<' rows whose limit is the 10,000 placeholder (source -10000): relative operator ND, concentration blank, detection limit =
  1. the lowest '<' limit reported in the source data for the same dataset + method + element (placeholder excluded), else
  2. the Actlabs 2026 catalogue lower limit (INAA 1D / fusion ICP-MS 4B2-Std; see actlabs_catalogue_limits.py), else
  3. none.
Read-only; writes lt_conc_backups/placeholder_plan.csv  (result_id, dataset, kind, aliquotName, name, method_code, limit, basis)."""
import csv, os, subprocess, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
SP = Path("C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/1f36e5e8-d7fa-4410-8209-17c5fcae5797/scratchpad")
rows = []
for ds in ("rock", "hmc", "soil"):
    for kind, fn, namef in (("elem", f"elem_{ds}.tsv", "element_symbol"), ("oxide", f"oxide_{ds}.tsv", "element_oxide")):
        for r in csv.DictReader(open(HERE / fn, encoding="utf-8"), delimiter="\t"):
            if r["qualifier_code"] == "<" and float(r["Conc"]) == 10000:
                rows.append((r["result_id"], ds, kind, r["aliquotName"], r[namef]))
ids = pd.DataFrame(rows, columns=["result_id", "dataset", "kind", "aliquotName", "name"])
ids["result_id"] = ids.result_id.astype("int64")
print("placeholder '<' rows in the load files:", len(ids), ids.groupby(["dataset", "kind"]).size().to_dict())
ids[["result_id"]].to_csv(SP / "ph_result_ids.txt", index=False, header=False)
sql = f"""\set ON_ERROR_STOP on
create temp table ids(result_id bigint primary key);
\copy ids from '{(SP / 'ph_result_ids.txt').as_posix()}'
\copy (select i.result_id, ap.package_code, u.unitcode as source_unit from ids i join analytical_results ar on ar.result_id=i.result_id left join analytical_packages ap on ap.package_id=ar.package_id left join units u on u.unitid=ar.unitid) to '{(SP / 'ph_methods.csv').as_posix()}' csv header
"""
(SP / "ph_methods.sql").write_text(sql, encoding="utf-8")
env = dict(os.environ)
for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip().strip("\"'"))
env["PGPASSWORD"] = env["LITHODAT_DB_PASSWORD"]
out = subprocess.run([r"C:\Program Files\QGIS 4.0.1\bin\psql.exe", "-h", env["LITHODAT_DB_HOST"], "-p", env["LITHODAT_DB_PORT"], "-U", env["LITHODAT_DB_USER"],
                      "-d", env["LITHODAT_DB_NAME"], "-f", str(SP / "ph_methods.sql")], capture_output=True, text=True, env=env)
if out.returncode:
    sys.exit(out.stderr)
m = pd.read_csv(SP / "ph_methods.csv").rename(columns={"package_code": "method_code"})
ids = ids.merge(m, on="result_id", how="left")
print("rows with a method:", int(ids.method_code.notna().sum()), "of", len(ids))
# The placeholder is 10000 in ppm. A '<' row whose Conc is 10000 only after unit conversion is a genuine limit, not the placeholder
# (2026-10-29: GGU-CPH-PWD-XRF Cl is reported '< 1 %' = 10000 ppm) - keep those as they are.
not_ph = ids[ids.source_unit != "ppm"]
print("excluded - Conc 10000 only after unit conversion (genuine limits):", len(not_ph),
      not_ph.groupby(["method_code", "name", "source_unit"]).size().to_dict())
ids = ids[ids.source_unit == "ppm"]

g = pd.read_csv(HERE / "geus_method_detection_limits.csv")
g = g[g.kind == "elem"].rename(columns={"analyte_code": "name", "package_code": "method_code"})
g["data_limit"] = g.min_limit.where(g.min_limit != 10000)
g = g.groupby(["dataset", "name", "method_code"], as_index=False).data_limit.min()   # one row per group (units can repeat a group)
cat = pd.read_csv(HERE / "actlabs_catalogue_limits.csv").dropna(subset=["lower_limit_ppm"])
lk = cat.set_index(["element", "catalogue_code"]).lower_limit_ppm.to_dict()
MAP = {"ACTLABS-NON-INAA": "INAA 1D", "ACTLABS-FUS-ICP-MS": "4B2-Std (ICP-MS)"}
p = ids.merge(g, on=["dataset", "name", "method_code"], how="left")
p["code"] = p.method_code.map(MAP)
p["cat_limit"] = [lk.get((n, c)) if isinstance(c, str) else None for n, c in zip(p.name, p.code)]
p["limit"] = p.data_limit.where(p.data_limit.notna(), p.cat_limit)
p["basis"] = "none"
p.loc[p.cat_limit.notna(), "basis"] = "catalogue " + p.code.astype(str)
p.loc[p.data_limit.notna(), "basis"] = "data"
p = p[["result_id", "dataset", "kind", "aliquotName", "name", "method_code", "limit", "basis"]]
p.to_csv(HERE / "lt_conc_backups" / "placeholder_plan.csv", index=False)
print("\nplan rows:", len(p), "| aliquots:", p.aliquotName.nunique())
print(p.groupby(["dataset", p.basis.str.split(" ").str[0]]).size().to_string())
print(p.groupby(["method_code", "name", p.basis.str.split(" ").str[0]]).size().sort_values(ascending=False).head(12).to_string())
nd = pd.read_csv(HERE / "lt_conc_backups" / "nd_plan.csv")
both = set(zip(nd.aliquotName, nd.name)) & set(zip(p.aliquotName, p.name))
print("aliquot+element pairs that are in BOTH the ND plan and this plan:", len(both))
