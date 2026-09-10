# Build the LithoSurfer deposit extract from the cleaned criticialmineralsexp master (v2).
# Inputs (this dir): v2_*.csv (from export_sources.sql), ref_*.json, ../crosswalk_*.csv
# Outputs (../): deposit.jsonl, deposit_style.jsonl, deposit_endowment.jsonl,
#                deposit_age.jsonl, deposit_op_status.jsonl, endowment_raw.csv,
#                review_needs_attention.csv, _coverage.json
import csv, json, re, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))
def p(n): return os.path.join(HERE, n)
def rows(n): return list(csv.DictReader(open(p(n), encoding="utf-8")))
def ref(n): return {r["name"]: r["id"] for r in json.load(open(p(f"ref_{n}.json"), encoding="utf-8"))}

LAT_PREC_M = 5000

xw_type = {int(r["db_deposit_type_id"]): (int(r["ls_deposit_type_id"]), r["ls_deposit_type_name"])
           for r in rows("../crosswalk_deposit_type.csv") if r["ls_deposit_type_id"]}
xw_comm = {int(r["db_commodity_id"]): (int(r["ls_commodity_id"]), r["ls_commodity_name"])
           for r in rows("../crosswalk_commodity.csv") if r["ls_commodity_id"]}

L_METHOD = ref("LAgeMethod")
METHOD_MAP = {
    "K-Ar": "K/Ar", "Ar-Ar": "Ar/Ar", "Rb-Sr": "Rb/Sr", "Sm-Nd": "Sm/Nd", "Pb-Pb": "Pb/Pb",
    "U-Pb": "U/Pb", "U-Pb Zircon": "U/Pb", "U-Pb SHRIMP": "U/Pb",
    "206Pb/238U": "U/Pb", "207Pb/235U": "U/Pb", "207Pb/206Pb": "Pb/Pb", "208Pb/232Th": "Th/Pb",
    "Fission Track": "Fission-track",
}  # C-14, Thermoluminescence, Unknown -> no LAgeMethod
def method_id(name):
    ls = METHOD_MAP.get((name or "").strip())
    return L_METHOD.get(ls) if ls else None

L_AGETYPE = ref("LDepositAgeType")   # DB age_type_reference names match this list 1:1
L_OS = ref("LOperatingStatus")
OPSTATUS = {"PRODUCER": "Operating", "PAST_PRODUCER": "Historic", "CLOSED": "Closed",
            "FEASIBILITY": "Feasibility", "DEVELOPMENT": "Under Development"}
L_REL = ref("LAgeRelationship")

def num(s):
    if s is None or s == "": return None
    try: return float(s)
    except ValueError:
        m = re.search(r"-?\d+\.?\d*", str(s)); return float(m.group()) if m else None

GRADE_UNITS = {"%": ("%", 1.0), "g/t": ("g/t", 1.0), "ppm": ("ppm", 1.0), "gr/t": ("g/t", 1.0),
               "kg/t": ("%", 0.1)}
def norm_grade(v, unit):
    base = re.split(r"[ (]", (unit or "").strip().lower())[0]
    if base in GRADE_UNITS and v is not None:
        u, k = GRADE_UNITS[base]; return v * k, u
    return None, None
def rel_op(unit):
    u = (unit or "").lower()
    if "máx" in u or "max" in u: return L_REL["Maximum"]
    if "mín" in u or "min" in u: return L_REL["Minimum"]
    return None

base = rows("v2_base.csv")
minerals = {int(r["depno"]): r["minerals"] for r in rows("v2_mineralogy.csv")}
comm = collections.defaultdict(list)
for r in rows("v2_commodities.csv"):
    comm[int(r["depno"])].append(r)
endow = collections.defaultdict(list)
for r in rows("v2_endowment.csv"):
    endow[int(r["depno"])].append(r)
ages = collections.defaultdict(list)
for r in rows("v2_ages.csv"):
    ages[int(r["depno"])].append(r)

dep_out, style_out, endow_out, age_out, ops_out = [], [], [], [], []
endow_raw, attention = [], []
desc_full = {}
cov = collections.Counter()

for r in base:
    depno = int(r["depno"]); sid = f"SIGAM:{depno}"
    r["url"] = f"https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp{depno}.html"
    cov["deposits"] += 1
    lat, lon = num(r["lat"]), num(r["lon"])
    coord_ok = lat is not None and lon is not None and abs(lat) > 1e-4 and abs(lon) > 1e-4
    name = (r["name"] or "").strip() or f"SIGAM deposit {depno}"
    if not (r["name"] or "").strip(): attention.append((depno, "no name", r["url"]))
    if not coord_ok: attention.append((depno, f"bad coordinate lat={lat} lon={lon}", r["url"])); cov["coord_bad"] += 1

    bits = []
    for label, k in [("Province", "geological_province"), ("District", "geological_district"),
                     ("Tectonic setting", "tectonic_setting"), ("Mineralisation style", "mineralization_style"),
                     ("Form", "deposit_form"), ("Alteration", "alteration"),
                     ("Metallogenic association", "metallogenic_association"),
                     ("Associated igneous", "associated_igneous"), ("Size", "size_category")]:
        v = (r.get(k) or "").strip()
        if v and v != "UNKNOWN": bits.append(f"{label}: {v}")
    if minerals.get(depno): bits.append(f"Mineralogy: {minerals[depno]}")
    if r.get("deposit_type_local"): bits.append(f"SIGAM type: {r['deposit_type_local']}")
    full_desc = " | ".join(bits) + f" | Source: SEGEMAR SIGAM fact sheet dp{depno}" + \
        (f" ({r['fecha_actualizacion']})" if r.get("fecha_actualizacion") else "") + \
        (f" {r['url']}" if r.get("url") else "")
    desc_full[depno] = full_desc
    # Deposit.description is capped at 255 by the API -> compact form, URL first so it always survives.
    short = " · ".join(x for x in [
        r.get("url"),
        (r.get("deposit_type_local") or "").strip() or None,
        (r.get("geological_province") or "").strip() or None,
    ] if x)
    dep_out.append({"name": name, "lat": lat if coord_ok else None, "lon": lon if coord_ok else None,
                    "latLonPrecision": LAT_PREC_M if coord_ok else None,
                    "description": short[:255], "sourceId": sid})

    # style
    dtid = int(r["deposit_type_id"]) if r["deposit_type_id"] else None
    ls = xw_type.get(dtid) if dtid else None
    if ls:
        style_out.append({"depositTypeId": ls[0], "depositTypeName": ls[1],
                          "comment": f"SIGAM: {r.get('deposit_type_local') or r.get('deposit_type_name')}",
                          "sourceId": sid})
        cov["style"] += 1
    elif dtid:
        cov["style_type_not_in_crosswalk"] += 1
    else:
        cov["style_untyped"] += 1

    # endowment: commodity presence
    seen = set()
    for c in comm.get(depno, []):
        cid = int(c["commodity_id"])
        res = xw_comm.get(cid)
        if not res or res[0] in seen:
            if not res: cov["commodity_not_in_crosswalk"] += 1
            continue
        seen.add(res[0])
        endow_out.append({"commodityId": res[0], "commodityName": res[1],
                          "comment": f"role: {c['commodity_role']}" if c["commodity_role"] else "commodity present (SIGAM)",
                          "sourceId": sid})
    if seen: cov["deposits_with_commodity"] += 1

    # endowment: grade / tonnage (merge deposit_endowment rows per commodity_raw + data_type)
    by_ck = collections.defaultdict(lambda: {"GRADE": [], "AMOUNT": []})
    for e in endow.get(depno, []):
        by_ck[(e["commodity_raw"], e["data_type"])][e["measure"]].append(e)
        endow_raw.append({"depno": depno, **{k: e[k] for k in
                          ("commodity_id","commodity_raw","data_type","measure","value_num","value_text","unit","seq")}})
    for (craw, dtype), slots in by_ck.items():
        res = None
        for e in slots["GRADE"] + slots["AMOUNT"]:
            if e["commodity_id"]:
                res = xw_comm.get(int(e["commodity_id"])); break
        gval = relid = None; parts = []
        for g in slots["GRADE"]:
            parts.append(f"grade {g['value_text'] or g['value_num']} {g['unit']}")
            if dtype == "RESOURCE" and gval is None:
                ng, _ = norm_grade(num(g["value_num"]), g["unit"])
                if ng is not None: gval = ng; relid = rel_op(g["unit"])
        for a in slots["AMOUNT"]:
            parts.append(f"amount {a['value_text'] or a['value_num']} {a['unit']}")
        flags = []
        if slots["GRADE"] and gval is None: flags.append("grade not normalised")
        if slots["AMOUNT"]: flags.append("tonnage/contained-metal not normalised - see endowment_raw.csv")
        endow_out.append({
            "commodityId": res[0] if res else None,
            "commodityName": res[1] if res else craw,
            "grade": gval, "gradeRelativeOperatorId": relid, "tonnage": None,
            "comment": f"{dtype.lower()}: " + "; ".join(parts) + (("  [" + "; ".join(flags) + "]") if flags else ""),
            "sourceId": sid})
        cov["endowment_grade_rows"] += 1
        if gval is not None: cov["endowment_grade_numeric"] += 1

    # ages
    for i, a in enumerate(ages.get(depno, [])):
        av = num(a["age_ma"])
        if av is None: continue
        mid = method_id(a["method"])
        atid = L_AGETYPE.get((a.get("age_type_name") or "").strip())
        d_bits = [x for x in [
            f"material: {a['material_dated']}" if a["material_dated"] else None,
            f"mineral: {a['mineral']}" if a["mineral"] else None,
            f"context: {a['age_interpretation']}" if a["age_interpretation"] else None,
            f"method(raw): {a['method']}" if a["method"] and not mid else None,
            f"ref: {a['reference']}" if a["reference"] else None] if x]
        age_out.append({"age": av, "ageUncertainty": num(a["age_error_ma"]),
                        "ageMethodId": mid, "ageTypeId": atid, "ageRelationshipId": L_REL["Absolute"],
                        "description": " | ".join(d_bits), "sourceId": f"{sid}#{i}"})
        cov["age_rows"] += 1
        if not mid: cov["age_method_unmapped"] += 1

    # op status
    st = (r.get("deposit_status") or "").strip()
    if st in OPSTATUS:
        ops_out.append({"operatingStatusId": L_OS[OPSTATUS[st]], "comment": f"SIGAM status: {st}", "sourceId": sid})
        cov["op_status"] += 1

def dump(name, arr):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for o in arr:
            f.write(json.dumps({k: v for k, v in o.items() if v is not None}, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(arr)}")

dump("deposit.jsonl", dep_out)
dump("deposit_style.jsonl", style_out)
dump("deposit_endowment.jsonl", endow_out)
dump("deposit_age.jsonl", age_out)
dump("deposit_op_status.jsonl", ops_out)
with open(os.path.join(OUT, "endowment_raw.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["depno","commodity_id","commodity_raw","data_type","measure","value_num","value_text","unit","seq"])
    w.writeheader(); w.writerows(endow_raw)
with open(os.path.join(OUT, "review_needs_attention.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["depno", "issue", "url"]); w.writerows(sorted(attention))
with open(os.path.join(OUT, "deposit_description_full.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["depno", "description_full"])
    for dn in sorted(desc_full): w.writerow([dn, desc_full[dn]])
json.dump(dict(cov), open(os.path.join(OUT, "_coverage.json"), "w"), indent=2)
print("\ncoverage:")
for k, v in sorted(cov.items()): print(f"  {k}: {v}")
