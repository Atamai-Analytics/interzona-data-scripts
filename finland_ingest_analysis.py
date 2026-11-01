#!/usr/bin/env python3
"""Follow-up analysis of finland_ingest_rules.py --validate: explain the residual differences."""
import collections
import sys
from pathlib import Path

import finland_ingest_rules as R

sp = Path(sys.argv[1])
rows, acols = R.read_source()
src = {str(int(r["LABNUM"])): r for r in rows}
samples = {r["samplenumber"]: r for r in R.read_csv(sp / "ex_samples.csv")}
litho = {r["sampleid"]: r for r in R.read_csv(sp / "ex_litho.csv")}
res = collections.defaultdict(collections.Counter)
codes = {}
for r in R.read_csv(sp / "ex_results.csv"):
    q = r["qualifier_id"] or None
    res[r["samplenumber"]][(r["package_code"], r["analyte_code"], r["unitcode"], int(q) if q else None, R.sig6(float(r["value"])))] += 1
    codes[r["analyte_code"].upper()] = r["analyte_code"]
flagged = {k for k, d in src.items() if d["DUPLICATE$"] == "D"}
in_db = [k for k in src if k in samples]
print(f"flagged D rows: {len(flagged)} | in DB: {len(in_db)}")

# ---- A. residual result differences -------------------------------------------------------------
only_exp, only_db = collections.Counter(), collections.Counter()
dedupe_explained = unexplained = 0
nc_cells = collections.Counter()
for k in in_db:
    exp = collections.Counter()
    cells = {}
    for col in acols:
        pc = R.parse_column(col)
        if pc is None: continue
        el, pkg, unit = pc
        v = src[k][col]
        pv = R.parse_value(v)
        if pv[0] == "skip":
            if pv[1].startswith("str:"): nc_cells[pv[1]] += 1
            continue
        key = (pkg, codes[el.upper()], unit, pv[1], pv[2])
        exp[key] += 1
    d1, d2 = exp - res[k], res[k] - exp
    for key, n in d1.items(): only_exp[key[:3]] += n
    for key, n in d2.items(): only_db[key[:3]] += n
    for key, n in d1.items():
        # does the same (pkg, analyte, unit, qualifier, value) exist in the DB once while the source has it twice?
        if res[k].get(key, 0) == exp[key] - n and exp[key] > 1:
            dedupe_explained += n
        else:
            unexplained += n
print("expected-but-not-in-DB by (package, analyte, unit):", dict(only_exp.most_common(10)))
print("in-DB-but-not-expected:", dict(only_db.most_common(10)))
print(f"differences explained by 'duplicate identical rows collapsed': {dedupe_explained} | unexplained: {unexplained}")
print("non-numeric string cells in rows that ARE in the DB:", dict(nc_cells.most_common(5)))

# ---- B. NC / strings in the flagged rows vs the others ---------------------------------------------
def count_strings(keys):
    c = collections.Counter(); n_empty = 0
    for k in keys:
        for col in acols:
            v = src[k][col]
            if v in (None, ""): n_empty += 1
            elif isinstance(v, str) and not v.startswith("<"):
                try: float(v)
                except ValueError: c[v[:6]] += 1
    return c, n_empty
cf, ef = count_strings(flagged)
cn, en = count_strings(in_db)
print(f"non-numeric strings in FLAGGED rows: {dict(cf.most_common(5))} | empties {ef}")
print(f"non-numeric strings in rows already in DB: {dict(cn.most_common(5))} | empties {en}")

# ---- C. divisionid: function of MAP100$ ? ----------------------------------------------------------
by_sheet = collections.defaultdict(collections.Counter)
for k in in_db: by_sheet[src[k]["MAP100$"]][samples[k]["divisionid"]] += 1
multi = {s: dict(c) for s, c in by_sheet.items() if len(c) > 1}
print(f"MAP100 sheets: {len(by_sheet)}; sheets mapping to >1 division: {len(multi)}; e.g. {dict(list(multi.items())[:3])}")
flag_sheets = collections.Counter(src[k]["MAP100$"] for k in flagged)
print(f"flagged rows: sheets not seen among existing samples: {sum(1 for s in flag_sheets if s not in by_sheet)}")

# ---- D. lithology mismatch and coverage ------------------------------------------------------------
for k in in_db:
    l = litho[samples[k]["sampleid"]]
    if l["lithologylocal"] != str(src[k]["ROCKTYPE$"]): print("lithology mismatch:", k, repr(l["lithologylocal"]), repr(src[k]["ROCKTYPE$"]))
known_rock = {str(src[k]["ROCKTYPE$"]) for k in in_db}
known_age = {str(src[k]["AGEGROUP"]) for k in in_db}
print("flagged ROCKTYPE$ not seen in existing rows:", sorted({str(src[k]['ROCKTYPE$']) for k in flagged} - known_rock))
print("flagged AGEGROUP not seen in existing rows:", sorted({str(src[k]['AGEGROUP']) for k in flagged} - known_age))
print("flagged SAMTYPE$:", dict(collections.Counter(src[k]["SAMTYPE$"] for k in flagged)), "| SAMDATE$ blank:", sum(1 for k in flagged if not R.sample_date(src[k]["SAMDATE$"])))
