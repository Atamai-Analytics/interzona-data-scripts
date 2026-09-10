"""WA age LithoSurfer extract — Step B: build the load JSONL from age_export.csv.

Input  (this dir):  age_export.csv, ref_lookups.json
Outputs (../):      sample.jsonl, age_datapoint.jsonl, literature.jsonl,
                    crosswalk_method.csv, _coverage.json

Model (LithoSurfer, host api.lithosurfer.io, package 250875261):
  POST /api/core/sample-with-locations   -> SampleWithLocationDTO {sampleDTO, locationDTO}
  POST /api/age/age-datapoints           -> AgeDataPointExtendsDataPointDTO
        {dataPointDTO, ageDataPointDTO{analyte}, geoEventAtAgeExtendsStatementDTO
         {geoEventAtAgeDTO{age,ageError,errorTypeId,geoEventId}, statementDTO{description}}}
  POST /api/core/literature (+ literature-2-package, literature-2-data-points)

The generic /api/age/ model has no field for age_qualifier / decay_constant /
n_grains / analytical_notes — those are folded into the datapoint / statement
description text.  sourceId = "WA-AGE:<tbl>:<age_analysis_id>" everywhere; the
loader resolves _sampleSourceId -> the created sample/location ids.
"""
import csv, json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))
PKG = 250875261
csv.field_size_limit(10_000_000)

lk = json.load(open(os.path.join(HERE, "ref_lookups.json"), encoding="utf-8"))
def by_name(key):
    return {x["name"].strip().lower(): x["id"] for x in lk[key]}
AM   = by_name("analytical_methods")
GEV  = by_name("geo_events")
ERT  = by_name("error_types")
SK   = by_name("sample_kinds")
LK   = by_name("location_kinds")

ID_ERR_UNKNOWN = ERT["unknown"]                 # 59667
ID_GEV_UNKNOWN = GEV["unknown"]                 # 59904
ID_SK_ROCK     = SK["rock"]                     # 60963
ID_LK_OUTCROP  = LK["outcrop location"]         # 60556
ID_EARTH       = next(x["id"] for x in lk["celestials"] if x["name"] == "Earth")
ID_US          = next(x["id"] for x in lk["countries_us"] if x["name"] == "United States")

# ---- WA dating_method_reference id -> l-analytical-methods id -------------------
# FT (id 10) is resolved per-row by mineral; everything else is fixed here.
METHOD_MAP = {
    2:  AM["k-ar"],   20: AM["ar-ar"], 21: AM["ar-ar"], 3: AM["ar-ar"],
    11: AM["u-pb"],   12: AM["u-pb"],  13: AM["u-pb"],  14: AM["u-pb"],
    15: AM["u-pb"],   16: AM["u-pb"],  26: AM["u-pb"],  27: AM["u-pb"],
    22: AM["other"],                                    # Pb-alpha (legacy Larsen)
    5:  AM["rb-sr"],  17: AM["sm-nd"],
}
def ft_method(material):
    m = (material or "").lower()
    if "apatite" in m: return AM["aft"]
    if "zircon"  in m: return AM["zft"]
    if "sphene" in m or "titanite" in m: return AM["tft"]
    return AM["other"]

# ---- geo-event inference from free text ---------------------------------------
GEV_RULES = [
    (r"xenocryst|inherit",                         "inherited age"),
    (r"detrital|provenance|maximum depositional",   "maximum depositional age"),
    (r"minimum (depositional )?age",               "minimum depositional age"),
    (r"cooling",                                    "cooling"),
    (r"metamorph",                                  "metamorphism"),
    (r"deformation|shear",                          "deformation"),
    (r"mineraliz|mineralis",                        "mineralisation"),
    (r"hydrothermal",                               "hydrothermal"),
    (r"alteration",                                 "alteration"),
    (r"intrus",                                     "intrusive"),
    (r"extrus|erupt|volcani|ash|tuff",              "extrusive"),
    (r"crystalli[sz]ation|emplac|age of intrusion|igneous",  "crystallization"),
]
def geo_event(*texts):
    blob = " ".join(t for t in texts if t).lower()
    for pat, name in GEV_RULES:
        if re.search(pat, blob) and name in GEV:
            return GEV[name]
    return ID_GEV_UNKNOWN

# ---- lat/lon precision from the location comments ----------------------------
def precision_m(loc_comments):
    a = (loc_comments or "").lower()
    if "gps" in a: return 30
    if "quarter section" in a or "qtr" in a: return 400
    if "7.5-minute" in a or "7.5 minute" in a or "topographic map" in a: return 250
    if "1 minute" in a or "~1 mile" in a or "1 mile" in a: return 1600
    if re.search(r"multiple townships|district centroid", a): return 10000
    if re.search(r"multiple sections|township", a): return 2500
    if re.search(r"(^|[^a-z])section", a): return 800
    return 2000

def clip(s, n):
    s = " ".join((s or "").split())
    return s[:n] if s else None

rows = list(csv.DictReader(open(os.path.join(HERE, "age_export.csv"), encoding="utf-8")))

# ---- group age rows into samples --------------------------------------------
# A physical sample can carry several analyses (e.g. one rock -> 206Pb/238U +
# 207Pb/235U + 207Pb/206Pb).  Collapse rows that share (table, lab_sample_id,
# location) into one sample; rows with no lab_sample_id stay 1 sample : 1 age.
def sample_key(r):
    lid = (r["lab_sample_id"] or "").strip()
    if not lid:
        return ("_solo", r["source_token"])
    return (r["wa_table"], lid.lower(),
            round(float(r["latitude"]), 5), round(float(r["longitude"]), 5))

groups = collections.OrderedDict()
for r in rows:
    groups.setdefault(sample_key(r), []).append(r)

row2sample = {}                    # source_token -> sample sourceId
sample_meta = {}                   # sample sourceId -> representative row + members
for key, members in groups.items():
    rep = min(members, key=lambda r: int(r["age_measured_id"]))
    ssid = "WA-AGE-S:" + rep["wa_table"] + ":" + rep["age_measured_id"]
    sample_meta[ssid] = (rep, members)
    for m in members:
        row2sample[m["source_token"]] = ssid

samples, dps = [], []
cov = collections.Counter()
method_seen = collections.Counter()
gev_seen = collections.Counter()

# ---- one SampleWithLocationDTO per group ----
for ssid, (r, members) in sample_meta.items():
    lid = (r["lab_sample_id"] or "").strip()
    nm = (f"{lid} (WA {r['wa_table']} {r['age_measured_id']})" if lid
          else f"WA-AGE {r['wa_table']} {r['age_measured_id']}")
    units = sorted({m["dated_unit_name"] for m in members if m["dated_unit_name"]})
    samples.append({
        "_sourceId": ssid,
        "_nAnalyses": len(members),
        "sampleDTO": {
            "dataPackageId": PKG,
            "name": clip(nm, 200),
            "sampleID": clip(lid, 120),
            "sourceId": ssid,
            "sampleKindId": ID_SK_ROCK,
            "description": clip(" / ".join(units), 500),
        },
        "locationDTO": {
            "name": clip(r["locationname"], 200) or ssid,
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
            "latLonPrecision": precision_m(r["location_comments"]),
            "countryId": ID_US,
            "celestialId": ID_EARTH,
            "description": clip("; ".join(x for x in [
                r["location_comments"],
                (r["county"] + " County, Washington, USA") if r["county"] else "Washington, USA",
            ] if x), 1000),
        },
    })
    if len(members) > 1:
        cov["samples_multi_analysis"] += 1
cov["samples"] = len(samples)

for r in rows:
    tok = r["source_token"]                       # WA-AGE:<tbl>:<id>
    tbl = r["wa_table"]
    cov["rows"] += 1

    dmid = int(r["datingmethodid"])
    amid = ft_method(r["material_dated"]) if dmid == 10 else METHOD_MAP.get(dmid, AM["other"])
    method_seen[(dmid, r["method_name"], amid)] += 1

    gev = geo_event(r["comments"], r["dated_unit_name"])
    gev_seen[gev] += 1

    age = float(r["age_ma"])
    err = float(r["age_error_ma"]) if r["age_error_ma"] not in ("", None) else None
    ngr = int(r["n_grains"]) if r["n_grains"] not in ("", None) else None

    # ---- datapoint description: everything the generic age model can't type ----
    dp_bits = [f"WA {r['method_name']}"]
    if r["age_qualifier"]:   dp_bits.append(f"reported age {r['age_qualifier']} {age} Ma")
    if ngr is not None:      dp_bits.append(f"{ngr} grains")
    if r["decay_constant"]:  dp_bits.append("decay constant: " + r["decay_constant"])
    if r["analytical_notes"] and r["analytical_notes"] not in ("null", ""):
        dp_bits.append("analytical: " + r["analytical_notes"])
    dp_desc = clip(" | ".join(dp_bits), 2000)

    # ---- statement description: the interpretive comments + provenance ----
    st_bits = []
    cm = re.sub(r"^\[WA-AGE:[^\]]+\]\s*\|?\s*", "", r["comments"] or "").strip()
    if cm: st_bits.append(cm)
    if r["ref_source_name"]: st_bits.append("Source: " + r["ref_source_name"])
    st_bits.append(f"criticialmineralsexp age_measured_id={r['age_measured_id']} ({tok})")
    st_desc = clip(" | ".join(st_bits), 2000)

    dps.append({
        "_sampleSourceId": row2sample[tok],
        "_datapointSourceId": tok,
        "_wa_table": tbl,
        "dataPointDTO": {
            "dataPackageId": PKG,
            "name": tok,
            "sourceId": tok,
            "analyticalMethodId": amid,
            "dataStructure": "AGE",
            "description": dp_desc,
        },
        "ageDataPointDTO": {"analyte": clip(r["material_dated"], 120)},
        "geoEventAtAgeExtendsStatementDTO": {
            "geoEventAtAgeDTO": {
                "age": age,
                "ageError": err,
                "errorTypeId": ID_ERR_UNKNOWN,
                "geoEventId": gev,
            },
            "statementDTO": {"description": st_desc},
        },
    })
    cov[f"method:{r['method_name']}"] += 1
    if err is None: cov["no_error"] += 1

# ---- literature (2 sources) --------------------------------------------------
lit = [
    {"sourceId": "WA-AGE-REF:ngdb",
     "author": "U.S. Geological Survey",
     "title": "National Geochronological Database (NGDB)",
     "litType": "MISC", "pubYear": "2010",
     "url": "https://mrdata.usgs.gov/geochron/",
     "note": "Compilation of published radiometric ages; via WA DGER geochronology tables."},
    {"sourceId": "WA-AGE-REF:dger100k",
     "author": "Washington Division of Geology and Earth Resources",
     "title": "Surface geology, 1:100,000-scale GIS data (geochronology tables)",
     "litType": "MISC", "pubYear": "2016",
     "url": "https://www.dnr.wa.gov/geologyportal",
     "note": "Washington State DGER 1:100,000 geologic database, age analysis tables."},
]

def dump(name, arr):
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        for o in arr:
            f.write(json.dumps({k: v for k, v in o.items() if v is not None}, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(arr)}")

dump("sample.jsonl", samples)
dump("age_datapoint.jsonl", dps)
dump("literature.jsonl", lit)

with open(os.path.join(OUT, "crosswalk_method.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["wa_dating_method_id", "wa_method_name", "ls_analytical_method_id", "n_rows"])
    id2name = {x["id"]: x["name"] for x in lk["analytical_methods"]}
    for (dmid, mn, amid), n in sorted(method_seen.items(), key=lambda x: -x[1]):
        w.writerow([dmid, mn, amid, n])
    print("  crosswalk_method.csv:", len(method_seen), "combos")

id2gev = {x["id"]: x["name"] for x in lk["geo_events"]}
cov["_geo_events"] = {id2gev.get(k, k): v for k, v in gev_seen.most_common()}
json.dump({k: (dict(v) if isinstance(v, dict) else v) for k, v in cov.items()},
          open(os.path.join(OUT, "_coverage.json"), "w"), indent=2)
print("\ncoverage:")
for k, v in sorted(cov.items()):
    if not k.startswith("_"): print(f"  {k}: {v}")
print("  geo_events:", cov["_geo_events"])
