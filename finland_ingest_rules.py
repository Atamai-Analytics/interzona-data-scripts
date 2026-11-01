#!/usr/bin/env python3
"""Rules that turn a FINRock.xlsx row (GTK Rock Geochemical Database of Finland) into the
criticialmineralsexp rows the original ingestion produced: samples, locations,
lithology_observations, age_stratigraphic, analytical_results.

The rules were reverse-engineered from the existing 6,169 GTK rock samples and are VALIDATED by
reproducing them (python finland_ingest_rules.py --validate <scratchpad dir>) before being used
for the 375 samples flagged DUPLICATE$='D' that were never ingested.
"""
import csv
import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

XLSX = Path("D:/CriticalMineralsDB/Finland/rock_geochemical_data_of_finland_etrs_tm35fin_msexcel_gdb (1)/FINRock.xlsx")
SAMTYPE_TO_SAMPLE_TYPE = {"P": 31, "R": 26, "L": 30}      # outcrop / block field (grab) / boulder (float)
METHOD_PACKAGE = {"XRF": "175X", "ICPAES": "511P", "ICPMS": "511P"}   # ICPMS columns were stored under 511P by the original ingestion


def read_source(limit_labnums=None):
    ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    hdr = list(next(it))
    rows = []
    for r in it:
        d = dict(zip(hdr, r))
        if limit_labnums is None or str(int(d["LABNUM"])) in limit_labnums:
            rows.append(d)
    analyte_cols = [h for h in hdr if h and (h.endswith(" %") or h.endswith(" ppm") or h.endswith(" ppb"))]
    return rows, analyte_cols


def parse_column(col):
    """'SIO2_XRF %' -> (element_token, package_code, unit) or None for columns that were not ingested (CO2)."""
    unit = col.split()[-1]
    stem = col[: -len(unit)].strip()
    if stem == "CO2":
        return None
    if stem == "F":
        return ("F", "707I", unit)
    el, _, method = stem.partition("_")
    if method == "TOT":
        return (el, "811L", unit)
    if method == "NONCARB":
        return (el, "816L", unit)
    if method == "GFAAS":
        return (el, "511U" if unit == "ppm" else "521U", unit)
    if method in METHOD_PACKAGE:
        return (el, METHOD_PACKAGE[method], unit)
    raise ValueError(f"unmapped column {col!r}")


def db_round(x):
    """Reproduce the stored value: 6 significant figures (half-up on the shortest decimal repr), then 6 decimals (half-up)."""
    from decimal import Decimal, ROUND_HALF_UP
    d = Decimal(float(x))          # exact binary expansion (the database rounded this, not the printed decimal)
    if d == 0:
        return 0.0
    d = d.quantize(Decimal(1).scaleb(d.adjusted() - 5), rounding=ROUND_HALF_UP)
    return float(d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


sig6 = db_round   # kept as an alias for older call sites


def parse_value(v):
    """-> ('skip', reason) | ('ok', qualifier_id|None, value)"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return ("skip", "empty")
    if isinstance(v, (int, float)):
        return ("ok", None, sig6(float(v)))
    s = str(v).strip()
    if s.startswith("<"):
        try:
            return ("ok", 1, sig6(float(s[1:])))
        except ValueError:
            return ("skip", f"bad<:{s}")
    try:
        return ("ok", None, sig6(float(s)))
    except ValueError:
        return ("skip", f"str:{s}")


def sample_date(samdate):
    s = str(samdate or "").strip()
    if not re.fullmatch(r"\d{6}", s):
        return None
    d, m, y = int(s[:2]), int(s[2:4]), 1900 + int(s[4:])
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# -------------------------------------------------------------------------------------------------
def validate(sp):
    sp = Path(sp)
    rows, acols = read_source()
    src = {str(int(r["LABNUM"])): r for r in rows}
    samples = {r["samplenumber"]: r for r in read_csv(sp / "ex_samples.csv")}
    litho = {r["sampleid"]: r for r in read_csv(sp / "ex_litho.csv")}
    age = {r["sampleid"]: r for r in read_csv(sp / "ex_age.csv")}
    res = defaultdict(Counter)
    for r in read_csv(sp / "ex_results.csv"):
        q = r["qualifier_id"] or None
        res[r["samplenumber"]][(r["package_code"], r["analyte_code"], r["unitcode"], int(q) if q else None, float(r["value"]) if r["value"] else None)] += 1
    print(f"source rows {len(src)} | existing samples {len(samples)} | existing results {sum(sum(c.values()) for c in res.values())}")
    in_db = [k for k in src if k in samples]
    print(f"source rows present in the database as rock samples: {len(in_db)}")

    # ---- analyte-code / unit lookup learned from the existing results ----------------------------
    codes = {r["analyte_code"].upper(): r["analyte_code"] for r in read_csv(sp / "ex_results.csv")[:200000]}
    # (rebuilt below from the whole file for completeness)
    codes = {}
    for r in read_csv(sp / "ex_results.csv"):
        codes[r["analyte_code"].upper()] = r["analyte_code"]

    # ---- 1. samples + locations ---------------------------------------------------------------
    from pyproj import Transformer
    t_ykj = Transformer.from_crs(2393, 4326, always_xy=True)
    t_etrs = Transformer.from_crs(3067, 4326, always_xy=True)
    bad = defaultdict(list)
    ykj_best = etrs_best = 0
    for k in in_db:
        s, d = samples[k], src[k]
        if s["locationcode"] != f"rock_{k}": bad["locationcode"].append(k)
        if s["locationname"] != f"MAP100: {d['MAP100$']} & MAP20: {d['MAP20$']}": bad["locationname"].append(k)
        if float(s["projectedx"]) != float(d["YCOORD"]) or float(s["projectedy"]) != float(d["XCOORD"]): bad["projected_xy"].append(k)
        if s["srid_projected"] != "2393": bad["srid_projected"].append(k)
        if SAMTYPE_TO_SAMPLE_TYPE.get(d["SAMTYPE$"]) != int(s["sample_type_id"]): bad["sample_type"].append(k)
        for fld, exp in (("sample_context", "SURFACE"), ("locationtype", "SURFACE"), ("countryid", "83"), ("datasource", "Geological Survey of Finland"), ("datasource_url", "https://www.gtk.fi/en/"), ("srid_geographic", "4326")):
            if s[fld] != exp: bad[fld].append(k)
        sd = sample_date(d["SAMDATE$"])
        dbd = dt.date.fromisoformat(s["sampledate"]) if s["sampledate"] else None
        if sd is None and dbd is not None: bad["sampledate"].append((k, "none", str(dbd)))
        elif sd is not None and (dbd is None or sd - dbd != dt.timedelta(days=1)): bad["sampledate_not_exactly_1_day_early"].append((k, str(sd), str(dbd)))
        lon_y, lat_y = t_ykj.transform(float(d["YCOORD"]), float(d["XCOORD"]))
        err_y = max(abs(lat_y - float(s["latitude"])), abs(lon_y - float(s["longitude"])))
        if err_y > 1e-6: bad["latlon_from_YKJ_2393"].append((k, err_y))
    for fld, lst in bad.items():
        print(f"  SAMPLE/LOCATION mismatch [{fld}]: {len(lst)}/{len(in_db)}  e.g. {lst[:3]}")
    if not bad: print("  samples/locations: all fields reproduced")
    print("  divisionid values in DB:", Counter(samples[k]["divisionid"] for k in in_db).most_common(5))
    print("  legacy_id filled:", sum(1 for k in in_db if samples[k]["legacy_id"]), "| samplenumberalt filled:", sum(1 for k in in_db if samples[k]["samplenumberalt"]))

    # ---- 2. lithology: ROCKTYPE$ -> (lithology_id, mindat_id) must be a function ---------------------
    mp = defaultdict(set); badl = 0
    for k in in_db:
        l = litho[samples[k]["sampleid"]]
        if l["lithologylocal"] != str(src[k]["ROCKTYPE$"] or ""): badl += 1
        mp[src[k]["ROCKTYPE$"]].add((l["lithology_id"], l["mindat_id"]))
    amb = {k: v for k, v in mp.items() if len(v) > 1}
    print(f"  LITHOLOGY: lithologylocal==ROCKTYPE$ mismatches {badl}; rocktypes {len(mp)}; ambiguous mappings {len(amb)}")

    # ---- 3. age: AGEGROUP -> (stratigraphic_age_id, confidence_level) ---------------------------------
    ap = defaultdict(set)
    for k in in_db:
        a = age[samples[k]["sampleid"]]
        ap[str(src[k]["AGEGROUP"])].add((a["stratigraphic_age_id"], a["confidence_level"], a["observation_context"]))
    amb_a = {k: v for k, v in ap.items() if len(v) > 1}
    print(f"  AGE: agegroups {len(ap)}; ambiguous mappings {len(amb_a)}; example map {dict(list(ap.items())[:4])}")

    # ---- 4. results: rebuild from source and compare per sample --------------------------------------
    skipped = Counter(); mism = 0; examples = []; n_exp = 0; samples_exact = 0
    for k in in_db:
        exp = Counter()
        for col in acols:
            pc = parse_column(col)
            if pc is None: continue
            el, pkg, unit = pc
            code = codes.get(el.upper())
            if code is None:
                skipped[("no_analyte_code", el)] += 1; continue
            pv = parse_value(src[k][col])
            if pv[0] == "skip":
                skipped[pv[1] if not pv[1].startswith("str:") else "str:" + pv[1][4:6]] += 1; continue
            exp[(pkg, code, unit, pv[1], pv[2])] = 1      # identical rows collapse into one (original ingestion behaviour)
        n_exp += sum(exp.values())
        if exp == res[k]:
            samples_exact += 1
        else:
            mism += 1
            if len(examples) < 4:
                examples.append((k, list((exp - res[k]).items())[:3], list((res[k] - exp).items())[:3]))
    print(f"  RESULTS: samples reproduced exactly {samples_exact}/{len(in_db)} | samples differing {mism} | expected result rows {n_exp}")
    print("  skipped source cells:", dict(skipped.most_common(8)))
    for e in examples: print("   example diff:", e)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--validate":
        validate(sys.argv[2])
    else:
        print(__doc__)
