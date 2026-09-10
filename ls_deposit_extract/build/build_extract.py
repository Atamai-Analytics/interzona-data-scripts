# Build the LithoSurfer deposit extract from the SIGAM staging layer.
# Inputs : src_*.csv (psql dumps), xwalk_*.csv, ref_*.json  (all in this dir)
# Outputs: <OUT>/deposit.jsonl, deposit_style.jsonl, deposit_endowment.jsonl,
#          deposit_age.jsonl, deposit_op_status.jsonl, endowment_raw.csv,
#          crosswalk_*.csv, README.md
import csv, json, re, os, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = r"C:/Users/dean/claude_lithosurfer/lithosurfer-work/ls_deposit_extract"
os.makedirs(OUT, exist_ok=True)
def sp(n): return os.path.join(HERE, n)
def rows(n): return list(csv.DictReader(open(sp(n), encoding="utf-8")))
def ref(n): return {r["name"]: r["id"] for r in json.load(open(sp(f"ref_{n}.json"), encoding="utf-8"))}

LAT_PREC_M = 5000  # SEGEMAR 1:250k WFS points are ~nominal; blanket precision

# ---------- crosswalks ----------
xw_type = {int(r["db_deposit_type_id"]): (int(r["ls_deposit_type_id"]), r["ls_deposit_type_name"])
           for r in rows("xwalk_deposit_type.csv") if r["ls_deposit_type_id"]}
xw_comm_by_dbid = {int(r["db_commodity_id"]): (int(r["ls_commodity_id"]), r["ls_commodity_name"])
                   for r in rows("xwalk_commodity.csv") if r["ls_commodity_id"]}
xw_comm_by_name = {r["db_commodity_name"].lower(): (int(r["ls_commodity_id"]), r["ls_commodity_name"])
                   for r in rows("xwalk_commodity.csv") if r["ls_commodity_id"]}
xw_comm_by_sym = {r["db_symbol"].lower(): (int(r["ls_commodity_id"]), r["ls_commodity_name"])
                  for r in rows("xwalk_commodity.csv") if r["ls_commodity_id"] and r["db_symbol"]}

type_map = {r["sigam_code"]: (int(r["deposit_type_id"]) if r["deposit_type_id"] else None,
                              r["sigam_name"], r["mapping_confidence"])
            for r in rows("src_type_mapping.csv")}

L_METHOD = ref("LAgeMethod")
METHOD_MAP = {
    "K-Ar": L_METHOD["K/Ar"], "Ar-Ar": L_METHOD["Ar/Ar"], "Rb-Sr": L_METHOD["Rb/Sr"],
    "U-Pb": L_METHOD["U/Pb"], "U-Pb SHRIMP": L_METHOD["U/Pb"], "Sm-Nd": L_METHOD["Sm/Nd"],
    "Sm/Nd": L_METHOD["Sm/Nd"], "Pb-Pb": L_METHOD["Pb/Pb"],
}  # Termoluminiscencia -> none

L_AT = ref("LDepositAgeType")
def age_type_id(evento):
    e = (evento or "").lower()
    if "mineraliz" in e: return L_AT["Age of mineralisation"]
    if "alterac" in e: return L_AT["Age of alteration"]
    if "metamorf" in e: return L_AT["Metamorphism"]
    if "enfriam" in e or "cooling" in e: return L_AT["Cooling"]
    if "intrus" in e or "efusi" in e: return L_AT["Igneous crystallisation"]
    if "sediment" in e or "estrati" in e: return L_AT["Sedimentary age"]
    return L_AT["Unknown"]

L_OS = ref("LOperatingStatus")
OPSTATUS_DB = {  # deposits.deposit_status -> LOperatingStatus (None = no clean mapping)
    "PRODUCER": L_OS["Operating"], "PAST_PRODUCER": L_OS["Historic"],
    "FEASIBILITY": L_OS["Feasibility"], "DEVELOPMENT": L_OS["Under Development"],
    "UNKNOWN": None, "OCCURRENCE": None, "EXPLORATION": None, "PROSPECT": None,
}
def opstatus_from_ficha(estado):
    e = (estado or "").split(";")[0].strip().lower()
    if e.startswith("produc") and "pasad" not in e and "pasa" not in e: return L_OS["Operating"]
    if "pasad" in e or "pasa" in e: return L_OS["Historic"]
    if "cerrad" in e: return L_OS["Closed"]
    if "abandon" in e: return L_OS["Abandoned"]
    if "inactiv" in e: return L_OS["Not Operating"]
    if "mantenimiento" in e: return L_OS["Care and Maintenance"]
    return None
L_REL = ref("LAgeRelationship")

# ---------- helpers ----------
def num(s):
    if s is None: return None
    s = s.strip().replace(" ", "")
    if not s: return None
    # "1,030" -> 1030 ; "6.97" -> 6.97 ; "0,02812" -> 0.02812
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[1]) != 3:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+\.?\d*", s)
        return float(m.group()) if m else None

def unc(s):
    if not s: return None
    vals = [abs(float(x)) for x in re.findall(r"[+-]?\d+\.?\d*", s.replace(",", "."))]
    return max(vals) if vals else None

def rel_op(unit_note):
    u = (unit_note or "").lower()
    if "máx" in u or "max" in u or "menor" in u or "<" in u: return L_REL["Maximum"], "<="
    if "mín" in u or "min" in u or "mayor" in u or ">" in u: return L_REL["Minimum"], ">="
    return None, None

GRADE_UNIT_OK = {"%", "g/t", "ppm", "ppb", "kg/t", "oz/t"}
def norm_grade(v, unit):
    """Return (grade_number_or_None, kept_unit, note). Only normalise unambiguous grade units."""
    u = (unit or "").strip().lower()
    base = re.split(r"[ (]", u)[0]
    if base in ("%", "por"): return v, "%", None
    if base in ("g/t", "gr/t", "g/tn"): return v, "g/t", None
    if base in ("ppm",): return v, "ppm", None
    if base in ("kg/t",): return v * 0.1, "%", "from kg/t"
    return None, unit, "non-grade unit; value kept in comment only"

# ---------- load base ----------
base = rows("src_base.csv")
minerals = {int(r["depno"]): r["minerals"] for r in rows("src_mineralogy.csv")}
refs = {}
for r in rows("src_refs.csv"):
    refs[int(r["depno"])] = (r.get("refs") or "").strip()

comm_existing = collections.defaultdict(list)
for r in rows("src_commodities_existing.csv"):
    comm_existing[int(r["depno"])].append((r["commodity_name"], (r["commodity_role"] or "").strip()))

grades = collections.defaultdict(list)
for r in rows("src_grades.csv"):
    grades[int(r["depno"])].append(r)
ages = collections.defaultdict(list)
for r in rows("src_ages.csv"):
    ages[int(r["depno"])].append(r)

# ---------- element-symbol commodity resolver for NEW deposits ----------
SYM = {"pb":"Pb","cu":"Cu","ag":"Ag","au":"Au","zn":"Zn","w":"W","fe":"Fe","mn":"Mn","ba":"Ba",
 "li":"Li","mo":"Mo","sn":"Sn","u":"U","bi":"Bi","sb":"Sb","v":"V","ni":"Ni","f":"F","as":"As",
 "s":"S","cr":"Cr","nb":"Nb","th":"Th","ta":"Ta","k":"K","co":"Co","ti":"Ti","se":"Se","pt":"Pt",
 "zr":"Zr","b":"B","hg":"Hg","in":"In","al":"Al","cs":"Cs","be":"Be","ree":"REE","pge":"PGE"}
IND = {  # spanish industrial terms -> DB commodity_name in xwalk
 "bentonita":"Bentonite","caolín":"Kaolin","caolin":"Kaolin","caliza":"Limestone","arcilla":"Clay",
 "yeso":"Gypsum","sal":"Salt","arena":"Sand and Gravel","áridos":"Sand and Gravel","aridos":"Sand and Gravel",
 "granito":"Granite","mármol":"Marble","marmol":"Marble","gneis":"Gneiss","cuarzo":"Quartz",
 "feldespato":"Feldspar","travertino":"Limestone","serpentinita":"Serpentine","asbesto":"Serpentine",
 "vermiculita":"Vermiculite","talco":"Talc","diatomita":"Diatomite","perlita":"Perlite","fluorita":"Fluorite",
 "grava":"Sand and Gravel","dolomía":"Limestone","pizarra":"Slate","basalto":"Basalt"}
FORMULA = {"wo3": "w", "sno2": "sn", "tio2": "ti", "moo3": "mo", "v2o5": "v", "nb2o5": "nb",
           "ta2o5": "ta", "u3o8": "u", "tho2": "th", "li2o": "li", "bao": "ba", "sb2o3": "sb",
           "etr": "ree", "tr": "ree", "egp": "pge", "pd": "pge", "pt": "pt",
           "baritina": "ba", "barita": "ba", "feldesp": "feldspar", "feldespato": "feldspar"}
def resolve_commodity(token):
    t = token.strip().strip("()")
    tl = t.lower()
    tl = FORMULA.get(tl, tl)
    if tl in xw_comm_by_name: return xw_comm_by_name[tl]
    if tl in SYM and SYM[tl].lower() in xw_comm_by_sym: return xw_comm_by_sym[SYM[tl].lower()]
    if tl in xw_comm_by_sym: return xw_comm_by_sym[tl]
    for k, v in IND.items():
        if k in tl and v.lower() in xw_comm_by_name: return xw_comm_by_name[v.lower()]
    return None

def split_commodities(s):
    if not s: return []
    s = s.replace("(", " ").replace(")", " ")
    parts = re.split(r"[;,/+]| y |-(?=[A-Z(])", s)
    out = []
    for p in parts:
        p = p.strip()
        if p and p.lower() not in ("etc", "otros", "y"):
            out.append(p)
    return out

# ---------- build ----------
dep_out, style_out, endow_out, age_out, ops_out = [], [], [], [], []
endow_raw = []
cov = collections.Counter()
DISAGREE = []
ATTENTION = []
UNRESOLVED = collections.Counter()

for r in base:
    depno = int(r["depno"])
    sid = f"SIGAM:{depno}"
    origin = r["origin"]
    lat, lon = num(r["lat"]), num(r["lon"])
    cov["deposits"] += 1
    cov[f"origin_{origin}"] += 1

    # description synthesis
    bits = []
    for label, key in [("Province", "geological_province"), ("District", "geological_district"),
                       ("Tectonic setting", "tectonic_setting"), ("Mineralisation style", "mineralization_style"),
                       ("Form", "deposit_form"), ("Alteration", "alteration"),
                       ("Metallogenic association", "metallogenic_association"),
                       ("Associated igneous", "associated_igneous")]:
        v = (r.get(key) or "").strip()
        if v: bits.append(f"{label}: {v}")
    if minerals.get(depno): bits.append(f"Mineralogy: {minerals[depno]}")
    if r.get("ficha_type_label"): bits.append(f"SIGAM type: {r['ficha_type_label']}")
    bits.append(f"Source: SEGEMAR SIGAM fact sheet dp{depno} ({r.get('fecha_actualizacion') or 'n.d.'}) {r['url']}")
    desc = " | ".join(bits)

    coord_ok = lat is not None and lon is not None and not (abs(lat) < 0.001 or abs(lon) < 0.001)
    name = (r["name"] or "").strip() or f"SIGAM deposit {depno}"
    if not (r["name"] or "").strip(): ATTENTION.append((depno, "no name in fact sheet", r["url"]))
    if not coord_ok:
        cov["coord_missing_or_zero"] += 1
        ATTENTION.append((depno, f"missing/zero coordinate (lat={lat} lon={lon})", r["url"]))
    dep_out.append({
        "name": name, "lat": lat if coord_ok else None, "lon": lon if coord_ok else None,
        "latLonPrecision": LAT_PREC_M if coord_ok else None,
        "description": desc, "sourceId": sid,
    })

    # ---- style (deposit type) ----
    # Staging-layer first: SIGAM fact-sheet type code -> mapping -> Hofstra id.
    # Fall back to the curated deposits.deposit_type_id only where the ficha code is missing/unmapped.
    raw_label = re.split(r";\s*(Referencia|Comentario)", r.get("ficha_type_label") or "")[0].strip() \
                or (r.get("deposit_type_local") or "")
    dt_id = None; conf = ""
    fcode = r.get("ficha_type_code")
    curated_id = int(r["db_deposit_type_id"]) if r.get("db_deposit_type_id") else None
    if fcode and fcode in type_map and type_map[fcode][0]:
        dt_id = type_map[fcode][0]; conf = f"SIGAM {fcode}, {type_map[fcode][2]} mapping"
        if curated_id and curated_id != dt_id:
            cov["style_ficha_vs_curated_disagree"] += 1
            DISAGREE.append((depno, fcode, dt_id, curated_id, raw_label))
    elif curated_id:
        dt_id = curated_id; conf = "curated"
    ls = xw_type.get(dt_id) if dt_id else None
    if ls:
        style_out.append({
            "depositTypeId": ls[0], "depositTypeName": ls[1],
            "comment": f"SIGAM: {raw_label}" + (f" [{conf}]" if conf else ""),
            "sourceId": sid,
        })
        cov["style"] += 1
    else:
        cov["style_unmapped"] += 1

    # ---- endowment: commodity presence ----
    seen = set()
    if origin == "existing":
        clist = comm_existing.get(depno, [])
    else:
        clist = [(t, "") for t in split_commodities(r.get("ficha_commodities"))]
    for cname, role in clist:
        res = (xw_comm_by_name.get(cname.lower()) or resolve_commodity(cname))
        if not res or res[0] in seen:
            if not res:
                cov["commodity_token_unresolved"] += 1
                UNRESOLVED[f"presence:{cname}"] += 1
            continue
        seen.add(res[0])
        endow_out.append({
            "commodityId": res[0], "commodityName": res[1],
            "comment": (f"role: {role}" if role else "commodity present (SIGAM)"),
            "sourceId": sid,
        })
    if seen: cov["deposits_with_commodity"] += 1

    # ---- endowment: grade / tonnage (merge staging rows per commodity+kind) ----
    by_ck = collections.defaultdict(lambda: {"grade": [], "amount": []})
    for g in grades.get(depno, []):
        by_ck[(g["commodity"], g["kind"])][g["slot"]].append(g)
        endow_raw.append({"depno": depno, **g})
    for (cname, kind), slots in by_ck.items():
        res = xw_comm_by_name.get((cname or "").lower()) or resolve_commodity(cname or "")
        grade_val = None; relid = None
        parts = []
        for gr in slots["grade"]:
            parts.append(f"grade {gr['value']} {gr['unit_note']}")
            # Only trust RESOURCE grades in %, g/t or ppm as the numeric DepositEndowment.grade.
            # Production grades are often concentrate / mill-head figures -> comment only.
            if kind == "recurso" and grade_val is None:
                ng, gu, note = norm_grade(num(gr["value"]), gr["unit_note"])
                if ng is not None:
                    grade_val = ng
                    relid, _ = rel_op(gr["unit_note"])
        for am in slots["amount"]:
            parts.append(f"amount {am['value']} {am['unit_note']}")
        flags = []
        if slots["grade"] and grade_val is None: flags.append("grade not normalised (non-standard unit or production figure)")
        if slots["amount"]: flags.append("tonnage/contained-metal not normalised - see endowment_raw.csv")
        endow_out.append({
            "commodityId": res[0] if res else None,
            "commodityName": res[1] if res else cname,
            "grade": grade_val, "gradeRelativeOperatorId": relid,
            "tonnage": None,
            "comment": f"{kind}: " + "; ".join(parts) + (("  [" + "; ".join(flags) + "]") if flags else ""),
            "sourceId": sid,
        })
        cov["endowment_grade_rows"] += 1
        if grade_val is not None: cov["endowment_grade_numeric"] += 1
        if not res:
            cov["endowment_commodity_unresolved"] += 1
            UNRESOLVED[f"grade:{cname}"] += 1

    # ---- ages ----
    for a in ages.get(depno, []):
        agev = num(a["age_ma"])
        if agev is None: cov["age_no_numeric"] += 1; continue
        mid = METHOD_MAP.get((a["method"] or "").strip())
        d_bits = [x for x in [
            f"dated object: {a['objeto_datado']}" if a["objeto_datado"] else None,
            f"concentrate: {a['concentrado']}" if a["concentrado"] else None,
            f"rock: {a['origen_roca']}" if a["origen_roca"] else None,
            f"unit: {a['nombre_formal']}" if a["nombre_formal"] else None,
            f"event: {a['evento']}" if a["evento"] else None,
            f"method(raw): {a['method']}" if a["method"] and not mid else None,
            f"ref: {a['referencia']}" if a["referencia"] else None,
        ] if x]
        age_out.append({
            "age": agev, "ageUncertainty": unc(a["uncertainty"]),
            "ageMethodId": mid, "ageTypeId": age_type_id(a["evento"]),
            "ageRelationshipId": L_REL["Absolute"],
            "description": " | ".join(d_bits),
            "sourceId": f"{sid}#{a['seq']}",
        })
        cov["age_rows"] += 1
        if not mid: cov["age_method_unmapped"] += 1

    # ---- op status ----
    osid = None; note = ""
    if origin == "existing" and r.get("deposit_status"):
        osid = OPSTATUS_DB.get(r["deposit_status"])
        note = f"SIGAM status: {r['deposit_status']}"
    if osid is None:
        f2 = opstatus_from_ficha(r.get("ficha_estado"))
        if f2: osid = f2; note = f"SIGAM: {r.get('ficha_estado')}"
    if osid:
        ops_out.append({"operatingStatusId": osid, "comment": note, "sourceId": sid})
        cov["op_status"] += 1

# ---------- write ----------
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
    w = csv.DictWriter(f, fieldnames=["depno", "seq", "kind", "slot", "commodity", "value", "unit_note"])
    w.writeheader()
    for r in endow_raw: w.writerow(r)
for src, dst in [("xwalk_deposit_type.csv", "crosswalk_deposit_type.csv"),
                 ("xwalk_commodity.csv", "crosswalk_commodity.csv")]:
    open(os.path.join(OUT, dst), "w", encoding="utf-8").write(open(sp(src), encoding="utf-8").read())

with open(os.path.join(OUT, "review_type_disagreements.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["depno", "ficha_code", "ficha_hofstra_id", "curated_hofstra_id", "ficha_label"])
    w.writerows(sorted(DISAGREE))
with open(os.path.join(OUT, "review_needs_attention.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["depno", "issue", "url"])
    w.writerows(sorted(ATTENTION))

print("\ncoverage:")
for k, v in sorted(cov.items()):
    print(f"  {k}: {v}")
print("\nunresolved commodity tokens:")
for k, v in UNRESOLVED.most_common():
    print(f"  {k}  x{v}")
json.dump(dict(cov), open(os.path.join(OUT, "_coverage.json"), "w"), indent=2)
