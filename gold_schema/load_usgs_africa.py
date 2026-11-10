"""USGS 'Compilation of Geospatial Data (GIS) for the Mineral Industries and Related Infrastructure of Africa' (2021, DOI 10.5066/P97EQWXP,
ScienceBase 607611a9d34e018b3201cbbf; USGS release, metadata use constraints 'None' = US public domain) -> interzona_cm (2026-11-10).

Three point layers of D:/CriticalMineralsDB/Africa/download_20261110/gdb/Africa_GIS.gdb, loaded in this order (later layers can attach to
records created by earlier ones, all in one transaction):
  1. AFR_Mineral_Deposits (1,190; from USGS PP1802 critical-minerals deposits): an existing active occurrence within 5 km with a matching name
     -> ATTACH (external id + the PP1802 commodities that occurrence lacks, as SECONDARY links; nothing else changed); else a NEW deposit
     (is_deposit, status UNKNOWN, mineralization_style = PP1802 deposit type).
  2. AFR_Mineral_Facilities (Minerals Yearbook 2018, Zambia 2017), fuel rows (oil, gas, refineries) LEFT OUT. Rows are grouped into facilities
     by (name, lat, lon); match as above -> ATTACH or NEW (is_deposit for mines/quarries/brine; workings_type 'Processing plant' for plants).
     Every row -> core.facility_capacity (units: Metric tons -> mt, Thousand metric tons -> mt x1000, Kilograms -> kg, Thousand carats ->
     carats x1000, others as published; capacity note 'g' -> GROSS_WEIGHT basis, 'e' -> 'estimated', 'c' -> shared capacity);
     operator + owners ('Name [40%]') -> core.occurrence_ownership (as_of_year = data year).
  3. AFR_Mineral_Exploration (USGS World Minerals Exploration Database, unpublished; projects last verified active 2004-2018):
     match -> ATTACH (external id + owner) else NEW (status from the stage AS LAST VERIFIED - year in comments).
Status: Assumed Active/Active/Production/Expansion -> PRODUCER; C&M/Care and Maintenance/Suspended -> CARE_AND_MAINTENANCE; Closed -> CLOSED;
Construction/Development/Reserves Development/Pre-Production -> DEVELOPMENT; Feasibility Study -> FEASIBILITY; Exploration -> EXPLORATION;
other (Inactive, Production - Inactive, Placer) -> UNKNOWN. Location accuracy 'A' (approximate) -> position_accuracy AREA_CENTROID.
Idempotent per source id (external ids already present are skipped).  Usage: python -P load_usgs_africa.py [--dry]  (--dry = load, verify, ROLLBACK)
"""
import os, re, sys, time, csv, collections, difflib, warnings
import pyogrio, psycopg2
from psycopg2.extras import execute_values
warnings.filterwarnings("ignore")

DRY = "--dry" in sys.argv
TAG = "migration_usgs_africa_20261110"
SRC = "USGS_AFRICA_GIS"
GDB = "D:/CriticalMineralsDB/Africa/download_20261110/gdb/Africa_GIS.gdb"
CITE = "Bermúdez-Lugo and others, 2021, USGS Africa GIS compilation, doi:10.5066/P97EQWXP"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def s(v):
    v = ("" if v is None else str(v)).strip()
    return None if v in ("", "<null>", "NA", "None", "nan") else v


STATUS = {"assumed active": "PRODUCER", "active": "PRODUCER", "production": "PRODUCER", "expansion": "PRODUCER",
          "c&m": "CARE_AND_MAINTENANCE", "care and maintenance": "CARE_AND_MAINTENANCE", "suspended": "CARE_AND_MAINTENANCE", "closed": "CLOSED",
          "construction": "DEVELOPMENT", "development": "DEVELOPMENT", "reserves development": "DEVELOPMENT", "pre-production": "DEVELOPMENT",
          "feasibility study": "FEASIBILITY", "exploration": "EXPLORATION"}
DEPOSIT_STAGES = {"feasibility study", "reserves development", "pre-production", "production", "expansion", "production - inactive"}
COUNTRY = {"Congo (Kinshasa)": "CD", "Congo (Brazzaville)": "CG", "Reunion": "RE"}
ALIAS = {"aluminum": "Al", "antimony": "Sb", "arsenic": "As", "barite": "Baryte", "beryllium": "Be", "bismuth": "Bi", "bromine": "Br", "caesium": "Cs",
         "chromium": "Cr", "chromium (chromite)": "Cr", "clay (bentonite)": "Bentonite", "clay (kaolin)": "Kaolin", "cobalt": "Co", "colbalt": "Co",
         "copper": "Cu", "diamonds": "Diamond", "fluorspar": "Fluorite", "gallium": "Ga", "germanium": "Ge", "gold": "Au", "hafnium": "Hf",
         "heavy minerals": "Heavy Mineral Sand", "indium": "In", "iridium": "Ir", "iron": "Fe", "iron ore": "Fe", "iron and steel": "Fe", "lead": "Pb",
         "lithium": "Li", "magnesium": "Mg", "manganese": "Mn", "ferromanganese": "Mn", "mercury": "Hg", "molybdenum": "Mo", "nickel": "Ni",
         "niobium (columbium)": "Nb", "palladium": "Pd", "phosphate": "Phosphate Rock", "platinum": "Pt", "platinum-group elements (pge)": "PGE",
         "potassium (potash)": "Potash", "rare earth elements (ree)": "REE", "rhodium": "Rh", "ruthenium": "Ru", "selenium": "Se", "silver": "Ag",
         "silicon": "Si", "ferrosilicon": "Si", "strontium": "Sr", "sulfur": "S", "tantalum": "Ta", "tellurium": "Te", "thorium": "Th", "tin": "Sn",
         "titanium": "Ti", "tungsten": "W", "uranium": "U", "vanadium": "V", "zinc": "Zn", "zirconium": "Zr", "halite": "Salt", "soda": "Soda Ash",
         "silica": "Silica Sand", "glass sand": "Silica Sand", "sand": "Sand and Gravel", "gravel": "Sand and Gravel", "aggregates": "Primary Aggregate",
         "stone": "Crushed Rock", "limestone (dolomite)": "Limestone", "limestone (marble)": "Marble", "limestone (marble, dolomite)": "Marble",
         "dolomite": "Limestone", "calcium carbonate": "Limestone", "nitrogen": None, "cement": None, "clay": "Clay"}


def expand(name):
    """One published commodity string -> list of commodity names to look up (e.g. 'Gem (ruby, sapphire)' -> Ruby, Sapphire)."""
    n = re.sub(r"\s+", " ", name).strip()
    m = re.match(r"(?i)(gem|heavy minerals) \((.+)\)$", n)
    if m:
        parts = [p.strip() for p in m.group(2).split(",")]
        return parts if m.group(1).lower() == "gem" else ["Heavy minerals"] + parts
    m = re.match(r"(?i)(niobium \(columbium\) and tantalum|tantalum and niobium \(columbium\))$", n)
    if m: return ["Niobium (columbium)", "Tantalum"]
    return [n]


norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower().replace("mine", "").replace("deposit", "").replace("project", ""))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id, commodity_name FROM core.commodities")
GN = {a: (b, cn) for a, b, cn in c.fetchall()}
unmapped = collections.Counter()


def commodity_ids(name):
    out = []
    for n in expand(name):
        k = n.lower()
        tgt = ALIAS[k] if k in ALIAS else n
        if tgt and tgt.lower() in GN: out.append(GN[tgt.lower()][0])
        else: unmapped[n] += 1
    return out


c.execute("SELECT name, iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'")
JN, JI = {}, {}
for nm, iso, jid in c.fetchall(): JN[nm.lower()] = jid; JI[iso] = jid


def jur(country):
    country = country.replace("\x92", "").replace("\ufffd", "ô")
    if country in COUNTRY: return JI[COUNTRY[country]]
    if country.startswith("C") and "Ivoire" in country: return JI["CI"]
    return JN.get(country.lower()) or JN.get({"Cabo Verde": "cabo verde"}.get(country, ""))


c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,))
DONE = {x[0] for x in c.fetchall()}
log("source ids already loaded (skipped)", len(DONE))


def match(name, lon, lat):
    lon, lat = float(lon), float(lat)
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 5000) ORDER BY d LIMIT 8""", (lon, lat, lon, lat))
    near = c.fetchall(); nm = norm(name)
    plantish = lambda v: bool(re.search(r"(?i)\b(plants?|refiner(y|ies)|smelters?|facilit(y|ies)|works|factor(y|ies))\b", v or ""))
    for oid, n2, d in near:
        if not nm: break
        if difflib.SequenceMatcher(None, nm, norm(n2)).ratio() > 0.8: return oid, n2, round(d)
        # one name contains the other: only when both are plants or both are not (a plant next to a mine stays a separate record)
        if len(nm) > 4 and len(norm(n2)) > 4 and (nm in norm(n2) or norm(n2) in nm) and plantish(name) == plantish(n2):
            return oid, n2, round(d)
    return None, (near[0][1] if near else None), (round(near[0][2]) if near else None)


def insert_occ(name, is_dep, jid, lon, lat, status, work, comment, posacc, style=None):
    lon, lat = float(lon), float(lat)
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, mineralization_style, comments,
                 is_active, created_by, created_date, position_accuracy) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,%s,%s,true,%s,now(),%s)
                 RETURNING occurrence_id""", (name[:300], is_dep, jid, lon, lat, status, work, style, comment, TAG, posacc))
    return c.fetchone()[0]


def link_commodities(oid, names, only_missing):
    c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,))
    have = {x[0] for x in c.fetchall()}; n = 0
    for i, nm in enumerate(names):
        for cid in commodity_ids(nm):
            if cid in have: continue
            have.add(cid); n += 1
            role = "SECONDARY" if only_missing or i > 0 else "PRIMARY"
            c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)", (oid, cid, role, TAG))
    return n


ext, own, logrows, stats = [], [], [], collections.Counter()
nojur = collections.Counter()

# ------------------------------------------------------------------ 1. deposits (PP1802)
d = pyogrio.read_dataframe(GDB, layer="AFR_Mineral_Deposits", read_geometry=False)
for r in d.itertuples():
    sid = "dep:" + r.FeatureUID
    if sid in DONE: continue
    comms = [s(getattr(r, f"DsgAttr0{i}")) for i in range(1, 9)]; comms = [x for x in comms if x]
    oid, near, dist = match(r.FeatureNam, r.Longitude, r.Latitude)
    if oid:
        stats["deposits attached"] += 1; stats["deposit commodity links added to existing"] += link_commodities(oid, comms, True)
        ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH", TAG)); logrows.append(("deposit", "ATTACH", r.FeatureUID, r.FeatureNam, oid, near, dist)); continue
    jid = jur(r.Country)
    if not jid: nojur[r.Country] += 1
    com = " | ".join(x for x in [f"USGS PP1802 critical-minerals deposit {r.FeatureUID} (MRData id {r.DsgAttr10}) in the {CITE}",
                                 f"Other names: {s(r.NameVar)}" if s(r.NameVar) else None, f"Commodities (as published): {', '.join(comms)}",
                                 f"Deposit type: {s(r.DsgAttr09)}" if s(r.DsgAttr09) else None, f"Province/region: {s(r.ADM1)}" if s(r.ADM1) else None,
                                 f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
                                 "Status not given by the source", f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if x)
    oid = insert_occ(r.FeatureNam, True, jid, r.Longitude, r.Latitude, "UNKNOWN", None, com, None, s(r.DsgAttr09))
    link_commodities(oid, comms, False); stats["deposits new"] += 1
    ext.append(("OCCURRENCE", oid, SRC, sid, "EXACT", TAG)); logrows.append(("deposit", "NEW", r.FeatureUID, r.FeatureNam, oid, near, dist))
log("deposits", dict(stats))

# ------------------------------------------------------------------ 2. facilities (Minerals Yearbook)
f = pyogrio.read_dataframe(GDB, layer="AFR_Mineral_Facilities", read_geometry=False)
log("facility rows", len(f), "| fuel rows left out", int((f.DsgAttr01 == "Fuel").sum()))
f = f[f.DsgAttr01 != "Fuel"]
UNIT = {"Metric tons": ("mt", 1), "Thousand metric tons": ("mt", 1000), "Kilograms": ("kg", 1), "Thousand carats": ("carats", 1000)}
cap, rowno, used_sid = [], {}, set()


def stage(ftype, product):
    """facility_stage like the US load: Mine for mines; for plants from the published product (Refined/Refinery/Cathode -> Refinery,
    Smelter/Blister/Matte/Anode/Ferro... -> Smelter, Concentrate -> Concentrator), else NULL."""
    if ftype in ("Mines and Quarries", "Brine"): return "Mine"
    p = (product or "").lower()
    if any(k in p for k in ("refin", "cathode", "electrowon")): return "Refinery"
    if any(k in p for k in ("smelt", "blister", "matte", "anode", "ferro", "alloy")): return "Smelter"
    if "concentrat" in p: return "Concentrator"
    return None


for (name, lat, lon), grp in f.groupby(["FeatureNam", "Latitude", "Longitude"], sort=False):
    uids = list(grp.FeatureUID)
    sid = "fac:" + "+".join(dict.fromkeys(uids))       # one facility id can cover several places (shared entries) -> all ids of the group
    k = 1
    while sid in used_sid: k += 1; sid = "fac:" + "+".join(dict.fromkeys(uids)) + f"#{k}"
    used_sid.add(sid)
    if sid in DONE: continue
    r0 = grp.iloc[0]
    types = sorted(set(grp.FeatureTyp)); comms = list(dict.fromkeys(x for x in grp.DsgAttr02 if s(x)))
    oid, near, dist = match(name, lon, lat)
    if oid:
        stats["facilities attached"] += 1; act = "ATTACH"
    else:
        jid = jur(r0.Country)
        if not jid: nojur[r0.Country] += 1
        stat = s(r0.LocOpStat) or ""
        owners = [s(r0[f"OwnerName{i}"]) for i in range(1, 5)]
        com = " | ".join(x for x in [f"USGS Minerals Yearbook facility {', '.join(uids)} (data year {r0.DsgAttr06}) in the {CITE}",
                                     f"Feature type: {', '.join(types)}", f"Commodities (as published): {', '.join(comms)}",
                                     f"Products: {', '.join(sorted(set(x for x in grp.DsgAttr03 if s(x))))}" if any(s(x) for x in grp.DsgAttr03) else None,
                                     f"Facility status (as published, {r0.DsgAttr06}): {stat}" + (" - assumed (not verified) by USGS" if stat == "Assumed Active" else ""),
                                     f"Location: {s(r0.MemoLoc)}" if s(r0.MemoLoc) else None, f"Province/region: {s(r0.ADM1)}" if s(r0.ADM1) else None,
                                     "POSITION IS APPROXIMATE (USGS location accuracy 'A')" if r0.LocConfid == "A" else None,
                                     f"Operator: {s(r0.OperateNam)}" if s(r0.OperateNam) else None,
                                     f"Owners: {'; '.join(o for o in owners if o)}" if any(owners) else None,
                                     f"Note: {s(r0.MemoOther)}" if s(r0.MemoOther) else None,
                                     f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
                                     f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if x)
        is_dep = any(t in ("Mines and Quarries", "Brine") for t in types)
        work = "Processing plant" if types == ["Mineral Processing Plants"] else None
        oid = insert_occ(name, is_dep, jid, lon, lat, STATUS.get(stat.lower(), "UNKNOWN"), work, com, "AREA_CENTROID" if r0.LocConfid == "A" else None)
        link_commodities(oid, comms, False); stats["facilities new"] += 1; act = "NEW"
    ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH" if act == "ATTACH" else "EXACT", TAG)); logrows.append(("facility", act, ",".join(uids), name, oid, near, dist))
    seen_own = set()
    for _, r in grp.iterrows():
        unit, mult = UNIT.get(s(r.DsgAttr08) or "", (s(r.DsgAttr08), 1))
        val = r.DsgAttr07 if r.DsgAttr07 is not None and r.DsgAttr07 == r.DsgAttr07 and r.DsgAttr07 >= 0 else None
        notes = s(r.DsgAttr09) or ""
        nt = "; ".join(x for x in ["estimated" if "e" in notes else None, "capacity shared with other facilities" if "c" in notes else None,
                                   f"published unit: {r.DsgAttr08}" if mult != 1 else None] if x) or None
        shared = [x.strip() for x in (s(r.DsgAttr10) or "").split(",") if x.strip()]
        cids = commodity_ids(r.DsgAttr02) if s(r.DsgAttr02) else []
        rowno[r.FeatureUID] = rowno.get(r.FeatureUID, 0) + 1; rid = f"{r.FeatureUID}-{rowno[r.FeatureUID]}"
        cap.append((oid, cids[0] if cids else None, s(r.DsgAttr02), s(r.DsgAttr01), r.FeatureTyp.replace("Oil and Gas Refineries and (or) Petrochemical Complexes", "Refinery or petrochemical complex"), stage(r.FeatureTyp, s(r.DsgAttr03)),
                    None, s(r.DsgAttr03), None, float(val) * mult if val is not None else None, unit if val is not None else None,
                    "GROSS_WEIGHT" if "g" in notes else None, nt, shared or None, s(r.LocOpStat), s(r.DsgAttr04) == "Y" if s(r.DsgAttr04) else None,
                    s(r.DsgAttr05) == "Y" if s(r.DsgAttr05) else None, int(r.DsgAttr06) if r.DsgAttr06 else None, SRC, rid, s(r.MemoOther), None, TAG))
        ents = [("OPERATOR", s(r.OperateNam), None)] if s(r.OperateNam) else []
        for i in range(1, 5):
            o = s(r[f"OwnerName{i}"])
            if not o: continue
            m = re.match(r"(.+?)\s*\[(\d+(?:\.\d+)?)%?\]\s*$", o)
            ents.append(("EQUITY_OWNER", m.group(1).strip() if m else o, float(m.group(2)) if m and float(m.group(2)) <= 100 else None))
        for role, nm, sh in ents:
            if (role, nm) in seen_own: continue
            seen_own.add((role, nm)); own.append((oid, nm[:300], role, sh, int(r.DsgAttr06) if r.DsgAttr06 else None, SRC, None, TAG))
execute_values(c, """INSERT INTO core.facility_capacity (occurrence_id, commodity_id, commodity_name, commodity_group, feature_type, facility_stage, phase, product_form,
                     product_descriptor, annual_capacity, capacity_unit, capacity_basis, capacity_notes, shared_with_rows, facility_status, multiple_commodities,
                     multiple_products, data_year, source_system, source_row_id, footnote, source_urls, created_by) VALUES %s""", cap, page_size=1000)
log("facilities", {k: v for k, v in stats.items() if "facilit" in k}, "| capacity rows", len(cap))

# ------------------------------------------------------------------ 3. exploration (WMED)
x = pyogrio.read_dataframe(GDB, layer="AFR_Mineral_Exploration", read_geometry=False)
for r in x.itertuples():
    sid = "exp:" + r.FeatureUID
    if sid in DONE: continue
    comms = [s(getattr(r, f"DsgAttr0{i}")) for i in range(1, 9)]; comms = [y for y in comms if y]
    stage = s(r.LocOpStat) or ""; yr = int(r.DsgAttr11) if r.DsgAttr11 else None
    oid, near, dist = match(r.FeatureNam, r.Longitude, r.Latitude)
    if oid:
        stats["exploration attached"] += 1; act = "ATTACH"
    else:
        jid = jur(r.Country)
        if not jid: nojur[r.Country] += 1
        com = " | ".join(y for y in [f"USGS World Minerals Exploration Database project {s(r.DsgAttr12) or ''} ({r.FeatureUID}) in the {CITE}",
                                     f"Other names: {s(r.NameVar)}" if s(r.NameVar) else None, f"Commodities (as published): {', '.join(comms)}",
                                     f"Stage {stage} AS LAST VERIFIED ACTIVE IN {yr} - may be out of date", f"Location: {s(r.MemoLoc)}" if s(r.MemoLoc) else None,
                                     f"Province/region: {s(r.ADM1)}" if s(r.ADM1) else None,
                                     f"Owner ({yr}): {s(r.OwnerName)}" + (f", {s(r.DsgAttr09)}" if s(r.DsgAttr09) else "") + (f", {s(r.DsgAttr10)}" if s(r.DsgAttr10) else "") if s(r.OwnerName) else None,
                                     f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
                                     f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if y)
        oid = insert_occ(r.FeatureNam, stage.lower() in DEPOSIT_STAGES, jid, r.Longitude, r.Latitude, STATUS.get(stage.lower(), "UNKNOWN"), None, com, None)
        link_commodities(oid, comms, False); stats["exploration new"] += 1; act = "NEW"
    ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH" if act == "ATTACH" else "EXACT", TAG)); logrows.append(("exploration", act, r.FeatureUID, r.FeatureNam, oid, near, dist))
    if s(r.OwnerName):
        t = (s(r.DsgAttr09) or "").lower(); sh = None
        try: sh = float(str(r.DsgAttr10).replace("%", "")) if s(r.DsgAttr10) else None
        except ValueError: pass
        own.append((oid, s(r.OwnerName)[:300], "OPERATOR" if "operator" in t else "EQUITY_OWNER", sh if sh is not None and 0 <= sh <= 100 else None, yr, SRC,
                    s(r.DsgAttr09), TAG))
log("exploration", {k: v for k, v in stats.items() if "explor" in k})

execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s", ext, page_size=2000)
c.execute("SELECT company_id, name, short_name FROM core.companies WHERE is_active")
SUFFIX = r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|plc|company|co|holdings|group|the|lp|sa|nv|ag|pty|spa|s a)\b"
nz = lambda v: re.sub(r"\s+", " ", re.sub(SUFFIX, " ", re.sub(r"[^a-z0-9 ]+", " ", (v or "").lower()))).strip()
comp = {}
for cid, nm, sn in c.fetchall():
    for v in (nm, sn):
        if nz(v) and len(nz(v)) > 3: comp[nz(v)] = cid
_seen, _own = set(), []
for row in own:                                     # several facilities / projects can land on one occurrence -> one row per (occurrence, role, owner)
    if (row[0], row[2], row[1]) not in _seen: _seen.add((row[0], row[2], row[1])); _own.append(row)
log("ownership rows", len(own), "-> after de-duplication", len(_own)); own = _own
execute_values(c, "INSERT INTO core.occurrence_ownership (occurrence_id, owner_name, company_id, ownership_role, share_pct, as_of_year, source_system, footnote, created_by) VALUES %s",
               [(o, n, comp.get(nz(n)), role, sh, yr, src, fn, tg) for o, n, role, sh, yr, src, fn, tg in own], page_size=1000)
log("external ids", len(ext), "| ownership rows", len(own), "| unmapped commodity names", dict(unmapped), "| countries without a jurisdiction", dict(nojur))
path = os.path.join(HERE, f"usgs_africa_load_log_20261110{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["layer", "action", "usgs_id", "name", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-10',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "U.S. Geological Survey", "Compilation of Geospatial Data (GIS) for the Mineral Industries and Related Infrastructure of Africa (2021), mineral layers",
           "U.S. Government work (public domain); metadata use constraints: None", "https://doi.org/10.5066/P97EQWXP",
           "Source: U.S. Geological Survey, Compilation of Geospatial Data (GIS) for the Mineral Industries and Related Infrastructure of Africa, doi:10.5066/P97EQWXP.",
           "Cleared: USGS data release, FGDC metadata access and use constraints 'None' (checked 2026-11-10). Loaded 2026-11-10.",
           "Facilities = USGS Minerals Yearbook 2018 (Zambia 2017); status 'Assumed Active' is USGS's assumption, not verified; most positions approximate. "
           "Oil, gas and refinery facilities not loaded. Exploration projects (USGS WMED, unpublished) give the stage when last verified active, 2004-2018 - "
           "often out of date. Deposits = USGS PP1802 critical-minerals deposits (mostly already present via MRDS; only missing commodities added there). "
           "Assessment-tract polygons and infrastructure layers not loaded.",
           "D:/CriticalMineralsDB/Africa/download_20261110/Africa_GIS_Metadata.xml", TAG))


def one(sql, p=None):
    c.execute(sql, p); return c.fetchall()


log("new occurrences: n / deposits / with commodities / no jurisdiction", one("""SELECT count(*), count(*) FILTER (WHERE is_deposit), count(*) FILTER (WHERE array_length(commodities,1) > 0),
    count(*) FILTER (WHERE jurisdiction_id IS NULL) FROM core.occurrences WHERE created_by = %s""", (TAG,)))
log("new by status", one("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)))
log("new by country (top 12)", one("SELECT country_name, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (TAG,)))
log("country vs USGS country mismatch check: new points outside 25W-65E / 40S-38N", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND NOT (lon BETWEEN -26 AND 65 AND lat BETWEEN -48 AND 38)", (TAG,))[0][0])
log("external ids by prefix", one("SELECT split_part(source_id, ':', 1), match_confidence, count(*) FROM core.external_ids WHERE source_system = %s GROUP BY 1, 2 ORDER BY 1, 2", (SRC,)))
log("capacity rows: n / with value / mapped commodity", one("SELECT count(*), count(annual_capacity), count(commodity_id) FROM core.facility_capacity WHERE source_system = %s", (SRC,)))
log("Zambia: new occurrences / capacity rows", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND country_name = 'Zambia'", (TAG,))[0][0],
    one("SELECT count(*) FROM core.facility_capacity fc JOIN core.occurrences o USING (occurrence_id) WHERE fc.source_system = %s AND o.country_name = 'Zambia'", (SRC,))[0][0])
log("Zambian copper/cobalt capacity (top 8)", one("""SELECT o.name, fc.commodity_name, fc.facility_stage, fc.product_form, fc.annual_capacity, fc.capacity_unit, fc.facility_status FROM core.facility_capacity fc
    JOIN core.occurrences o USING (occurrence_id) WHERE fc.source_system = %s AND o.country_name = 'Zambia' AND fc.commodity_name IN ('Copper','Cobalt')
    ORDER BY fc.annual_capacity DESC NULLS LAST LIMIT 8""", (SRC,)))
log("capacity rows by stage", one("SELECT facility_stage, count(*) FROM core.facility_capacity WHERE source_system = %s GROUP BY 1 ORDER BY 2 DESC", (SRC,)))
log("ownership roles", one("SELECT ownership_role, count(*), count(share_pct), count(company_id) FROM core.occurrence_ownership WHERE source_system = %s GROUP BY 1", (SRC,)))
if DRY:
    g.rollback(); log("DRY RUN - rolled back"); log("after rollback tagged occurrences (must be 0)", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s", (TAG,))[0][0])
else:
    g.commit(); log("COMMITTED")
g.close()
