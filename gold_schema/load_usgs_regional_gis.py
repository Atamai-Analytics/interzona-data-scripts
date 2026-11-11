"""USGS regional 'Compilation of Geospatial Data (GIS) for the Mineral Industries' releases (public domain) -> interzona_cm, one region per run,
following the USGS Africa load (load_usgs_africa.py, 2026-11-10). Each region's layers are first turned into the same standard records by a small
adapter (the releases use different field layouts), then loaded the same way:

  CHINA    doi:10.5066/P9HK2K8I (2023): facilities (MYB 2019, revised), exploration (WMED + sources, 2019-2023), deposits (PP1802 / OFR2005-1294)
  SWASIA   doi:10.5066/P9OCRYYO (2022): select countries of Southwest/South/Southeast Asia (India, Iran, Indonesia, North Korea, Thailand,
           Pakistan, Afghanistan, Laos ...): facilities (MYB 2018), exploration (WMED), deposits (OFR2005-1294)
  INDOPAC  doi:10.5066/P13YRCDU (2024): 19 Indo-Pacific countries: facilities (MYB 2019, revised), exploration and development projects (2020-2023)
  LAC      ScienceBase 5804d720e4b0824b2d1c19c6 (2017): Latin America and the Caribbean: facilities (MYB 2014) and exploration projects (2015)

Per record: an existing active occurrence within 5 km with a matching name -> ATTACH (external id + missing commodities as SECONDARY + capacity and
owners); else NEW occurrence. Facilities -> core.facility_capacity rows (one per published commodity row; units normalised: kmt / tmt / 'Thousand
metric tons' x1000 -> mt, 'million mt' x1e6, kg as is) and core.occurrence_ownership (operator + owners, share from '[x%]'). Fuel (oil, gas, coal,
refineries) left out, as for Africa. Status: active/assumed active -> PRODUCER; suspended/C&M -> CARE_AND_MAINTENANCE; closed -> CLOSED; development/
construction/pre-production -> DEVELOPMENT; feasibility -> FEASIBILITY; exploration/preliminary -> EXPLORATION; inactive/other -> UNKNOWN.
Location accuracy 'A' (approximate) -> position_accuracy AREA_CENTROID.
Idempotent per source id. Usage: python -P load_usgs_regional_gis.py <CHINA|SWASIA|INDOPAC|LAC> [--dry]
"""
import os, re, sys, time, csv, collections, difflib, warnings
import pandas as pd, pyogrio, psycopg2
from psycopg2.extras import execute_values
warnings.filterwarnings("ignore")

REGION = sys.argv[1].upper()
DRY = "--dry" in sys.argv
W = "D:/CriticalMineralsDB/World/usgs_facilities_20261110"
CFG = {
    "CHINA": ("USGS_CHINA_GIS", "Compilation of Geospatial Data (GIS) for the Mineral Industries and Related Infrastructure of the People's Republic of China (2023), mineral layers",
              "Neustaedter and others, 2023, USGS China GIS compilation, doi:10.5066/P9HK2K8I", "https://doi.org/10.5066/P9HK2K8I", f"{W}/china/CHN_GIS_metadata.xml"),
    "SWASIA": ("USGS_SWASIA_GIS", "Compilation of Geospatial Data (GIS) for the Mineral Industries and Related Infrastructure of Select Countries in Southwest Asia (2022), mineral layers",
               "Padilla and others, 2022, USGS Southwest Asia GIS compilation, doi:10.5066/P9OCRYYO", "https://doi.org/10.5066/P9OCRYYO", f"{W}/swasia/SWAsia_GIS_metadata.xml"),
    "INDOPAC": ("USGS_INDOPAC_GIS", "Compilation of Geospatial Data (GIS) for the Mineral Industries of Select Countries in the Indo-Pacific (2024), mineral layers",
                "Trimmer and others, 2024, USGS Indo-Pacific GIS compilation, doi:10.5066/P13YRCDU", "https://doi.org/10.5066/P13YRCDU", f"{W}/indopac/INDOPAC_GIS_metadata.xml"),
    "LAC": ("USGS_LAC_GIS", "Compilation of geospatial data for the mineral industries and related economic infrastructure of Latin America and the Caribbean (2017): facilities and exploration",
            "USGS (2017), Compilation of geospatial data for the mineral industries and related economic infrastructure of Latin America and the Caribbean, ScienceBase 5804d720e4b0824b2d1c19c6",
            "https://www.sciencebase.gov/catalog/item/5804d720e4b0824b2d1c19c6", f"{W}/lac"),
}
SRC, DATASET, CITE, URL, EVID = CFG[REGION]
TAG = f"migration_usgs_{REGION.lower()}_20261110"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a): print(time.strftime("%H:%M:%S"), REGION, *a, flush=True)


def s(v):
    v = ("" if v is None else str(v)).strip()
    return None if v in ("", "<null>", "NA", "N/A", "None", "nan", "-999", "-999.0") else v


def num(v):
    try:
        x = float(str(v).replace(",", ""))
        return None if (x != x or x < 0) else x          # x != x: NaN
    except (TypeError, ValueError):
        return None


FUEL = {"petroleum", "natural gas", "crude oil", "coal", "coke", "lng", "liquefied natural gas", "refined petroleum products", "petroleum products",
        "natural gas liquids", "condensate", "oil shale", "lignite", "anthracite", "bituminous coal", "coalbed methane", "fuel", "oil"}
STATUS = {"assumed active": "PRODUCER", "active": "PRODUCER", "production": "PRODUCER", "expansion": "PRODUCER", "a": "PRODUCER",
          "c&m": "CARE_AND_MAINTENANCE", "care and maintenance": "CARE_AND_MAINTENANCE", "suspended": "CARE_AND_MAINTENANCE", "s": "CARE_AND_MAINTENANCE", "cm": "CARE_AND_MAINTENANCE",
          "closed": "CLOSED", "c": "CLOSED", "construction": "DEVELOPMENT", "planned construction": "DEVELOPMENT", "development": "DEVELOPMENT", "uc": "DEVELOPMENT",
          "reserves development": "DEVELOPMENT", "pre-production": "DEVELOPMENT", "feasibility study": "FEASIBILITY", "feasibility": "FEASIBILITY", "f": "FEASIBILITY",
          "exploration": "EXPLORATION", "preliminary study": "EXPLORATION", "e": "EXPLORATION"}
DEPOSIT_STAGES = {"feasibility study", "feasibility", "reserves development", "pre-production", "production", "expansion", "construction", "f", "d"}
UNIT = {"metric tons": ("mt", 1), "thousand metric tons": ("mt", 1000), "kmt": ("mt", 1000), "tmt": ("mt", 1000), "million mt": ("mt", 1e6),
        "million metric tons": ("mt", 1e6), "mt": ("mt", 1), "kilograms": ("kg", 1), "kg": ("kg", 1), "thousand carats": ("carats", 1000), "carats": ("carats", 1),
        "thousand cubic meters": ("m3", 1000), "cubic meters": ("m3", 1), "thousand square meters": ("m2", 1000), "square meters": ("m2", 1),
        "tcm": ("m3", 1000), "mcm": ("m3", 1e6)}
ALIAS = {"aluminum": "Al", "antimony": "Sb", "arsenic": "As", "barite": "Baryte", "beryllium": "Be", "bismuth": "Bi", "bromine": "Br", "cesium": "Cs", "caesium": "Cs",
         "chromium": "Cr", "chromite": "Cr", "cobalt": "Co", "copper": "Cu", "diamond": "Diamond", "diamonds": "Diamond", "fluorspar": "Fluorite", "gallium": "Ga",
         "germanium": "Ge", "gold": "Au", "hafnium": "Hf", "indium": "In", "iridium": "Ir", "iron": "Fe", "iron ore": "Fe", "iron and steel": "Fe", "steel": "Fe",
         "lead": "Pb", "lithium": "Li", "magnesium": "Mg", "magnesite": "Mg", "manganese": "Mn", "mercury": "Hg", "molybdenum": "Mo", "nickel": "Ni",
         "niobium": "Nb", "niobium (columbium)": "Nb", "palladium": "Pd", "phosphate": "Phosphate Rock", "phosphate rock": "Phosphate Rock", "platinum": "Pt",
         "platinum-group elements (pge)": "PGE", "platinum-group metals": "PGE", "pgm": "PGE", "potash": "Potash", "potassium (potash)": "Potash",
         "rare earths": "REE", "rare-earth elements": "REE", "rare earth elements (ree)": "REE", "rhenium": "Re", "rhodium": "Rh", "ruthenium": "Ru",
         "selenium": "Se", "silver": "Ag", "silicon": "Si", "strontium": "Sr", "sulfur": "S", "tantalum": "Ta", "tellurium": "Te", "thorium": "Th", "tin": "Sn",
         "titanium": "Ti", "tungsten": "W", "uranium": "U", "vanadium": "V", "zinc": "Zn", "zirconium": "Zr", "halite": "Salt", "salt": "Salt",
         "soda ash": "Soda Ash", "silica": "Silica Sand", "sand and gravel": "Sand and Gravel", "stone": "Crushed Rock", "limestone": "Limestone",
         "dolomite": "Limestone", "marble": "Marble", "heavy minerals": "Heavy Mineral Sand", "ilmenite": "Ti", "rutile": "Ti", "zircon": "Zr",
         "bauxite": "Bauxite", "alumina": "Alumina", "graphite": "Graphite", "gypsum": "Gypsum", "kaolin": "Kaolin", "bentonite": "Bentonite",
         "ferroalloys": "Ferroalloys", "cement": None, "nitrogen": None, "clay": "Clay", "boron": "B", "iodine": "I", "helium": "He", "cadmium": "Cd",
         "gemstones": None, "gemstone": None, "other": None}

# ------------------------------------------------------------------ adapters -> standard records
FAC, EXP, DEP = [], [], []


def owners_from(r, cols):
    return [s(getattr(r, c, None)) for c in cols if s(getattr(r, c, None))]


def gdb_facilities(gdb, layer, year, v):          # v = field map version
    d = pyogrio.read_dataframe(gdb, layer=layer, read_geometry=False)
    for r in d.itertuples():
        if v == "swa":   # Africa/SWA layout
            comm, prod, desc, mc, mp, yr, cap, unit, notes, shared, loc = r.DsgAttr02, r.DsgAttr03, None, r.DsgAttr04, r.DsgAttr05, r.DsgAttr06, r.DsgAttr07, r.DsgAttr08, r.DsgAttr09, getattr(r, "DsgAttr10", None), r.MemoLoc
            group, conf, owners = r.DsgAttr01, r.LocConfid, owners_from(r, ["OwnerName1", "OwnerName2", "OwnerName3", "OwnerName4", "OwnerName5"])
        elif v == "chn":
            comm, prod, mc, mp, desc, cap, unit, notes, shared, loc = r.DsgAttr01, r.DsgAttr02, r.DsgAttr03, r.DsgAttr04, r.DsgAttr05, r.DsgAttr06, r.DsgAttr07, r.DsgAttr08, r.DsgAttr09, r.MemoLoc
            yr, group, conf, owners = year, None, r.LocConfid, owners_from(r, ["OwnerName1", "OwnerName2", "OwnerName3", "OwnerName4", "OwnerName5"])
        else:            # indopac
            comm, prod, desc, mc, mp, cap, unit, notes, shared, loc = r.DsgAttr01, r.DsgAttr02, r.DsgAttr03, r.DsgAttr04, r.DsgAttr05, r.DsgAttr06, r.DsgAttr07, r.DsgAttr08, r.DsgAttr9, r.DsgAttr10
            yr, group, conf, owners = year, None, r.LocConf, owners_from(r, ["OwnerName1", "OwnerName2", "OwnerName3", "OwnerName4", "OwnerName5", "OwnerName6"])
        FAC.append(dict(uid=str(r.FeatureUID).strip(), name=s(r.FeatureNam) or str(r.FeatureUID), country=str(r.Country).strip(), lat=r.Latitude, lon=r.Longitude,
                        conf=(s(conf) or "").upper(), ftype=s(r.FeatureTyp) or "", group=s(group), comm=s(comm), prod=s(prod), desc=s(desc),
                        mc=s(mc), mp=s(mp), year=int(float(yr)) if num(yr) else year, cap=num(cap), unit=s(unit), notes=s(notes), shared=s(shared),
                        status=s(r.LocOpStat) or "", loc=s(loc), adm1=s(getattr(r, "ADM1", None)), operator=s(getattr(r, "OperateNam", None)), owners=owners))


def gdb_exploration(gdb, layer, comm_cols, stage_col="LocOpStat", year_col=None, owner_cols=("OwnerName",), loc_cols=("MemoLoc",), kind="exploration", ftype_col=None):
    d = pyogrio.read_dataframe(gdb, layer=layer, read_geometry=False)
    for r in d.itertuples():
        EXP.append(dict(uid=str(r.FeatureUID).strip(), name=s(r.FeatureNam) or str(r.FeatureUID), namevar=s(getattr(r, "NameVar", None)), country=str(r.Country).strip(),
                        lat=r.Latitude, lon=r.Longitude, conf=(s(getattr(r, "LocConf", None) or getattr(r, "LocConfid", None)) or "").upper(),
                        comms=[s(getattr(r, c)) for c in comm_cols if s(getattr(r, c, None))], stage=s(getattr(r, stage_col, None)) or "",
                        year=int(float(getattr(r, year_col))) if year_col and num(getattr(r, year_col, None)) else None,
                        owners=[s(getattr(r, c, None)) for c in owner_cols if s(getattr(r, c, None))], loc="; ".join(x for x in (s(getattr(r, c, None)) for c in loc_cols) if x),
                        adm1=s(getattr(r, "ADM1", None) or getattr(r, "AMD1", None)), kind=kind, ftype=s(getattr(r, ftype_col, None)) if ftype_col else None))


def gdb_deposits(gdb, layer, comm_cols, type_col, lat="Latitude", lon="Longitude", country="Country"):
    d = pyogrio.read_dataframe(gdb, layer=layer, read_geometry=False)
    for r in d.itertuples():
        DEP.append(dict(uid=str(r.FeatureUID).strip(), name=s(r.FeatureNam) or str(r.FeatureUID), country=str(getattr(r, country)).strip(),
                        lat=num(getattr(r, lat)), lon=float(getattr(r, lon)), comms=[s(getattr(r, c)) for c in comm_cols if s(getattr(r, c, None))],
                        dtype=s(getattr(r, type_col, None)), adm1=s(getattr(r, "ADM1", None)), namevar=s(getattr(r, "NameVar", None))))


if REGION == "CHINA":
    G = f"{W}/china/CHN_GIS.gdb"
    gdb_facilities(G, "CHN_Mineral_Facilities", 2019, "chn")
    gdb_exploration(G, "CHN_Mineral_Exploration", [f"DsgAttr0{i}" for i in range(1, 8)], year_col="DsgAttr09", owner_cols=("OwnerName",), loc_cols=("DsgAttr08", "MemoLoc"))
    gdb_deposits(G, "CHN_Mineral_Deposits", [f"DsgAttr0{i}" for i in range(1, 5)], "DsgAttr05", lat="LATITUDE", lon="LONGITUDE", country="COUNTRY")
elif REGION == "SWASIA":
    G = f"{W}/swasia/SWAsia_GIS.gdb"
    gdb_facilities(G, "SWA_Mineral_Facilties", 2018, "swa")
    gdb_exploration(G, "SWA_Mineral_Exploration", [f"DsgAttr0{i}" for i in range(1, 10)], owner_cols=(), loc_cols=("MemoLoc",))
    gdb_deposits(G, "SWA_Mineral_Deposits", [f"DsgAttr0{i}" for i in range(1, 10)] + ["DsgAttr10", "DsgAttr11"], "DsgAttr12")
elif REGION == "INDOPAC":
    G = f"{W}/indopac/INDOPAC_GIS.gdb"
    gdb_facilities(G, "INDOPAC_Mineral_Facilities", 2019, "idp")
    gdb_exploration(G, "INDOPAC_Mineral_Exploration", [f"DsgAttr0{i}" for i in range(1, 7)], year_col="DsgAttr09",
                    owner_cols=("OperateNam", "OwnerName1", "OwnerName2", "OwnerName3", "OwnerName4"), loc_cols=("DsgAttr07", "MemoLoc"))
    gdb_exploration(G, "INDOPAC_Mineral_Development", [f"DsgAttr0{i}" for i in range(1, 7)], year_col="DsgAttr09",
                    owner_cols=("OperateNam", "OwnerName1", "OwnerName2", "OwnerName3", "OwnerName4", "OwnerName5"), loc_cols=("DsgAttr08", "MemoLoc"),
                    kind="development", ftype_col="FeatureTyp")
elif REGION == "LAC":
    m = pd.read_csv(f"{W}/lac/MINFAC_LAC.csv", dtype=str, encoding="latin-1")
    for r in m.itertuples():
        if num(r.DDLAT) is None and str(r.DDLAT).strip() not in ("0", "0.0"):
            try: float(r.DDLAT)
            except (TypeError, ValueError): continue
        FAC.append(dict(uid=str(r.FACID).strip(), name=s(r.LOCNAME) or str(r.FACID), country=str(r.COUNTRY).strip(), lat=float(r.DDLAT), lon=float(r.DDLONG),
                        conf=(s(r.LOCACC) or "").upper(), ftype=s(r.FACTYPE) or "", group=s(r.COMMTYPE), comm=s(r.COMMODITY), prod=s(r.MIN_PROD), desc=None,
                        mc=s(r.MULTI_COMM), mp=s(r.MULTI_PROD), year=int(r.YEAR) if num(r.YEAR) else 2014, cap=num(r.ANNCAP), unit=s(r.UNITS),
                        notes=("estimated" if s(r.ECAP) else None), shared=s(r.COMBOCAP), status=s(r.STATUS) or "", loc=s(r.LOCDESC), adm1=s(r.ADM1),
                        operator=s(r.OPERATOR), owners=[x.strip() for x in re.split(r";", s(r.OWNER) or "") if x.strip()]))
    e = pd.read_csv(f"{W}/lac/EXPLORE_LAC.csv", dtype=str, encoding="latin-1")
    for r in e.itertuples():
        EXP.append(dict(uid=str(r.FACID).strip(), name=s(r.PROJNAME) or str(r.FACID), namevar=None, country=str(r.COUNTRY).strip(), lat=float(r.DDLAT), lon=float(r.DDLONG),
                        conf=(s(r.LOCACC) or "").upper(), comms=[x.strip() for x in (s(r.COMM) or "").split(",") if x.strip()], stage=s(r.PROJTYPE) or "",
                        year=int(r.YEAR) if num(r.YEAR) else None, owners=[x.strip() for x in re.split(r";", s(r.OWNER) or "") if x.strip()] or ([s(r.OPERATOR)] if s(r.OPERATOR) else []),
                        loc="", adm1=s(r.ADM1), kind="exploration", ftype=None))
log("standard records: facilities", len(FAC), "| exploration/development", len(EXP), "| deposits", len(DEP))


def is_fuel(rec):
    t = " ".join(x for x in [rec.get("group"), rec.get("comm"), rec.get("ftype")] if x).lower()
    base = re.sub(r"\s*\(.*\)\s*$", "", (rec.get("comm") or "").lower()).strip()          # 'Coal (hard)' -> 'coal'
    return (rec.get("group") or "").lower() == "fuel" or "oil and gas" in t or (rec.get("comm") or "").lower() in FUEL or base in FUEL


fuel = [x for x in FAC if is_fuel(x)]
FAC = [x for x in FAC if not is_fuel(x)]
EXP = [x for x in EXP if not ((x["comms"] and all((c or "").lower() in FUEL for c in x["comms"])) or "oil and gas" in (x.get("ftype") or "").lower())]
log("after removing fuel: facility rows", len(FAC), "(fuel rows left out", len(fuel), ") | exploration/development", len(EXP))

# ------------------------------------------------------------------ database helpers (as in the Africa load)
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
unmapped = collections.Counter()


def _one(n):
    """one commodity name -> commodity_id or None; tries the name, then 'Inner' and 'Base' of 'Base (Inner)'."""
    k = n.lower().strip()
    tries = [k]
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", k)
    if m: tries += [m.group(2).strip(), m.group(1).strip()]
    for t in tries:
        if t in ALIAS:
            if ALIAS[t] is None: return "SKIP"
            if ALIAS[t].lower() in GN: return GN[ALIAS[t].lower()]
        if t in GN: return GN[t]
    return None


def commodity_ids(name):
    out = []
    if not name: return out
    hit = _one(name)
    parts = [name] if hit else [p for p in re.split(r"\s*(?:,|;|\band\b)\s*", name) if p.strip()]
    for n in parts:
        h = hit if n == name else _one(n)
        if h == "SKIP": continue
        if h: out.append(h)
        else: unmapped[n.strip()] += 1
    return out


c.execute("SELECT name, iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'")
JN, JI = {}, {}
for nm, iso, jid in c.fetchall(): JN[nm.lower()] = jid; JI[iso] = jid
CISO = {"korea, north": "KP", "north korea": "KP", "south korea": "KR", "korea, south": "KR", "burma": "MM", "laos": "LA", "iran": "IR", "taiwan": "TW", "vietnam": "VN", "russia": "RU",
        "bolivia": "BO", "venezuela": "VE", "brunei": "BN", "timor-leste": "TL", "east timor": "TL", "syria": "SY", "turkey": "TR", "china": "CN",
        "bahamas, the": "BS", "trinidad and tobago": "TT", "dominican republic": "DO", "new caledonia": "NC", "micronesia": "FM", "cuba": "CU"}
nojur = collections.Counter()


def jur(country):
    k = (country or "").strip().lower()
    if k in CISO and CISO[k] in JI: return JI[CISO[k]]
    return JN.get(k)


c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,))
DONE = {x[0] for x in c.fetchall()}
log("source ids already loaded (skipped)", len(DONE))
STOP = r"\b(mine|mines|deposit|project|plant|plants|smelter|refinery|quarry|complex|operation)\b"
norm = lambda x: re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", (x or "").lower()))


def match(name, lon, lat):
    lon, lat = float(lon), float(lat)
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND created_by <> %s AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 5000) ORDER BY d LIMIT 8""",
              (lon, lat, TAG, lon, lat))
    near = c.fetchall(); nm = norm(name)
    plantish = lambda v: bool(re.search(r"(?i)\b(plants?|refiner(y|ies)|smelters?|facilit(y|ies)|works|factor(y|ies))\b", v or ""))
    for oid, n2, d in near:
        if not nm: break
        if difflib.SequenceMatcher(None, nm, norm(n2)).ratio() > 0.8: return oid, n2, round(d)
        if len(nm) > 4 and len(norm(n2)) > 4 and (nm in norm(n2) or norm(n2) in nm) and plantish(name) == plantish(n2):
            return oid, n2, round(d)
    return None, (near[0][1] if near else None), (round(near[0][2]) if near else None)


def insert_occ(name, is_dep, jid, lon, lat, status, work, comment, posacc, style=None):
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, mineralization_style, comments,
                 is_active, created_by, created_date, position_accuracy) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,%s,%s,true,%s,now(),%s)
                 RETURNING occurrence_id""", (name[:300], is_dep, jid, float(lon), float(lat), status, work, style, comment, TAG, posacc))
    return c.fetchone()[0]


def link_commodities(oid, names, only_missing):
    c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,))
    have = {x[0] for x in c.fetchall()}; n = 0
    for i, nm in enumerate(names):
        for cid in commodity_ids(nm):
            if cid in have: continue
            have.add(cid); n += 1
            c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                      (oid, cid, "SECONDARY" if only_missing or i > 0 else "PRIMARY", TAG))
    return n


def stage_of(ftype, prod, comm):
    if re.search(r"(?i)mines? and quarr|brine", ftype or ""): return "Mine"
    p = (prod or "").lower() + " " + (comm or "").lower()
    if any(k in p for k in ("refin", "cathode", "electrowon")): return "Refinery"
    if any(k in p for k in ("smelt", "blister", "matte", "anode", "ferro", "alloy")): return "Smelter"
    if "concentrat" in p: return "Concentrator"
    if re.fullmatch(r"(?i)\s*(m|mine|mines)\s*", ftype or ""): return "Mine"      # LAC codes; never 'Mineral Processing Plant'
    return None


def own_parse(text):
    m = re.match(r"(.+?)\s*[\[,]\s*(\d+(?:\.\d+)?)\s*%\]?\s*$", text)
    if m and float(m.group(2)) <= 100: return m.group(1).strip(), float(m.group(2))
    return text.strip(), None


ext, own, cap, logrows, stats = [], [], [], [], collections.Counter()
posacc = lambda conf: "AREA_CENTROID" if conf.startswith("A") else None

# ---- deposits
for r in DEP:
    sid = "dep:" + r["uid"]
    if sid in DONE or r["lat"] is None: continue
    oid, near, dist = match(r["name"], r["lon"], r["lat"])
    if oid:
        stats["deposits attached"] += 1; stats["deposit commodities added"] += link_commodities(oid, r["comms"], True)
        ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH", TAG)); logrows.append(("deposit", "ATTACH", r["uid"], r["name"], oid, near, dist)); continue
    jid = jur(r["country"]); nojur[r["country"]] += not jid
    com = " | ".join(x for x in [f"USGS deposit {r['uid']} in the {CITE}", f"Other names: {r['namevar']}" if r.get("namevar") else None,
                                 f"Commodities (as published): {', '.join(r['comms'])}", f"Deposit type: {r['dtype']}" if r["dtype"] else None,
                                 f"Province/region: {r['adm1']}" if r["adm1"] else None,
                                 f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
                                 "Status not given by the source", f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if x)
    oid = insert_occ(r["name"], True, jid, r["lon"], r["lat"], "UNKNOWN", None, com, None, r["dtype"])
    link_commodities(oid, r["comms"], False); stats["deposits new"] += 1
    ext.append(("OCCURRENCE", oid, SRC, sid, "EXACT", TAG)); logrows.append(("deposit", "NEW", r["uid"], r["name"], oid, near, dist))

# ---- facilities: group rows into facilities by (name, lat, lon)
fdf = pd.DataFrame(FAC)
for col in fdf.columns:                      # pandas turns None into NaN: put None back so 'missing' stays missing
    if col not in ("lat", "lon", "owners"):
        fdf[col] = fdf[col].astype(object).where(fdf[col].notna(), None)
used = set()
rowno = collections.Counter()
for (name, lat, lon), grp in fdf.groupby(["name", "lat", "lon"], sort=False):
    uids = list(dict.fromkeys(grp.uid)); sid = "fac:" + "+".join(uids)
    k = 1
    while sid in used: k += 1; sid = "fac:" + "+".join(uids) + f"#{k}"
    used.add(sid)
    if sid in DONE: continue
    r0 = grp.iloc[0]
    comms = list(dict.fromkeys(x for x in grp.comm if x))
    oid, near, dist = match(name, lon, lat)
    if oid:
        stats["facilities attached"] += 1; act = "ATTACH"; link_commodities(oid, comms, True)
    else:
        jid = jur(r0.country); nojur[r0.country] += not jid
        stat = r0.status
        com = " | ".join(x for x in [f"USGS Minerals Yearbook facility {', '.join(uids)} (data year {r0.year}) in the {CITE}",
                                     f"Feature type: {', '.join(sorted(set(x for x in grp.ftype if x)))}" if any(grp.ftype) else None,
                                     f"Commodities (as published): {', '.join(comms)}",
                                     f"Products: {', '.join(sorted(set(x for x in grp['prod'] if x)))}" if any(x for x in grp['prod'] if x) else None,
                                     f"Facility status (as published, {r0.year}): {stat}" + (" - assumed (not verified) by USGS" if stat.lower().startswith("assumed") or stat == "A" else ""),
                                     f"Location: {r0.loc}" if r0.loc else None, f"Province/region: {r0.adm1}" if r0.adm1 else None,
                                     "POSITION IS APPROXIMATE (USGS location accuracy 'A')" if r0.conf.startswith("A") else None,
                                     f"Operator: {r0.operator}" if r0.operator else None, f"Owners: {'; '.join(r0.owners)}" if r0.owners else None,
                                     f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
                                     f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if x)
        types = " ".join(x for x in grp.ftype if x).lower()
        is_dep = any(stage_of(x, None, None) == "Mine" for x in grp.ftype)
        work = "Processing plant" if ("processing plant" in types and not is_dep) else None
        oid = insert_occ(name, is_dep, jid, lon, lat, STATUS.get(stat.strip().lower(), "UNKNOWN"), work, com, posacc(r0.conf))
        link_commodities(oid, comms, False); stats["facilities new"] += 1; act = "NEW"
    ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH" if act == "ATTACH" else "EXACT", TAG)); logrows.append(("facility", act, ",".join(uids), name, oid, near, dist))
    seen_own = set()
    for r in grp.itertuples():
        uk = (r.unit or "").strip().lower()
        unit, mult = UNIT.get(uk, (r.unit, 1))
        capv = r.cap * mult if r.cap is not None else None
        notsand = "sand" not in (r.comm or "").lower()
        implausible = capv is not None and unit == "mt" and (capv >= 1e9 or (notsand and capv >= 1.5e8) or
                                                             (capv >= 5e7 and "million" in (r.unit or "").lower() and notsand))
        if implausible:     # e.g. 3,000 million t/yr of barite, 100 Mt/yr raw steel at one plant: source errors, not annual capacities
            r = r._replace(notes=f"{r.notes + '; ' if r.notes else ''}published capacity {r.cap:g} {r.unit} is implausible as an annual capacity (probably a resource figure) - not loaded")
            capv = None
        long_unit = isinstance(unit, str) and len(unit) > 20
        if long_unit: unit = unit[:20]
        nt = "; ".join(x for x in [r.notes and f"notes: {r.notes}", f"published unit: {r.unit}" if (mult != 1 or long_unit) else None,
                                   f"descriptor: {r.desc}" if r.desc else None] if x) or None
        shared = [x.strip() for x in (r.shared or "").split(",") if x.strip()]
        cids = commodity_ids(r.comm) if r.comm else []
        rowno[r.uid] += 1
        t40 = lambda v: v[:40] if isinstance(v, str) else v     # varchar(40) columns (feature type, status ...)
        cap.append((oid, cids[0] if cids else None, r.comm, t40(r.group), t40(r.ftype), stage_of(r.ftype, r.prod, r.comm), None, r.prod, r.desc,
                    capv, unit if capv is not None else None,
                    "GROSS_WEIGHT" if "G" in (r.notes or "").upper().replace(" ", "").split(",") else None, nt, shared or None, (r.status or "")[:30] or None,
                    (r.mc or "").upper().startswith("Y") if r.mc else None, (r.mp or "").upper().startswith("Y") if r.mp else None, r.year, SRC,
                    f"{r.uid}-{rowno[r.uid]}", None, None, TAG))
        ents = [("OPERATOR", r.operator, None)] if r.operator else []
        for o in r.owners:
            nm_, sh = own_parse(o); ents.append(("EQUITY_OWNER", nm_, sh))
        for role, nm_, sh in ents:
            if (role, nm_) in seen_own or not nm_: continue
            seen_own.add((role, nm_)); own.append((oid, nm_[:300], role, sh, r.year, SRC, None, TAG))
log("deposits + facilities", dict(stats), "| capacity rows", len(cap))

# ---- exploration / development projects
for r in EXP:
    sid = ("dev:" if r["kind"] == "development" else "exp:") + r["uid"]
    if sid in DONE: continue
    oid, near, dist = match(r["name"], r["lon"], r["lat"])
    st = r["stage"].strip()
    if oid:
        stats[f"{r['kind']} attached"] += 1; act = "ATTACH"; link_commodities(oid, r["comms"], True)
    else:
        jid = jur(r["country"]); nojur[r["country"]] += not jid
        com = " | ".join(x for x in [f"USGS {r['kind']} project {r['uid']} in the {CITE}", f"Other names: {r['namevar']}" if r["namevar"] else None,
                                     f"Commodities (as published): {', '.join(r['comms'])}",
                                     f"Stage {st} AS LAST VERIFIED" + (f" IN {r['year']}" if r["year"] else "") + " - may be out of date",
                                     f"Location: {r['loc']}" if r["loc"] else None, f"Province/region: {r['adm1']}" if r["adm1"] else None,
                                     "POSITION IS APPROXIMATE (USGS location accuracy 'A')" if r["conf"].startswith("A") else None,
                                     f"Owners/operator: {'; '.join(r['owners'])}" if r["owners"] else None,
                                     f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
                                     f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if x)
        oid = insert_occ(r["name"], st.lower() in DEPOSIT_STAGES, jid, r["lon"], r["lat"], STATUS.get(st.lower(), "UNKNOWN"),
                         "Processing plant" if "processing plant" in (r.get("ftype") or "").lower() else None, com, posacc(r["conf"]))
        link_commodities(oid, r["comms"], False); stats[f"{r['kind']} new"] += 1; act = "NEW"
    ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH" if act == "ATTACH" else "EXACT", TAG)); logrows.append((r["kind"], act, r["uid"], r["name"], oid, near, dist))
    for i, o in enumerate(r["owners"]):
        nm_, sh = own_parse(o)
        role = "OPERATOR" if (REGION == "INDOPAC" and i == 0) else "EQUITY_OWNER"
        if nm_ and nm_ != "NA": own.append((oid, nm_[:300], role, sh, r["year"], SRC, None, TAG))
log("exploration/development", {k: v for k, v in stats.items() if "explor" in k or "develop" in k})

execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s", ext, page_size=2000)
execute_values(c, """INSERT INTO core.facility_capacity (occurrence_id, commodity_id, commodity_name, commodity_group, feature_type, facility_stage, phase, product_form,
                     product_descriptor, annual_capacity, capacity_unit, capacity_basis, capacity_notes, shared_with_rows, facility_status, multiple_commodities,
                     multiple_products, data_year, source_system, source_row_id, footnote, source_urls, created_by) VALUES %s""", cap, page_size=1000)
c.execute("SELECT company_id, name, short_name FROM core.companies WHERE is_active")
SUFFIX = r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|plc|company|co|holdings|group|the|lp|sa|nv|ag|pty|spa|s a)\b"
nz = lambda v: re.sub(r"\s+", " ", re.sub(SUFFIX, " ", re.sub(r"[^a-z0-9 ]+", " ", (v or "").lower()))).strip()
comp = {}
for cid, nm, sn in c.fetchall():
    for v in (nm, sn):
        if nz(v) and len(nz(v)) > 3: comp[nz(v)] = cid
_seen, _own = set(), []
for row in own:
    if (row[0], row[2], row[1]) not in _seen: _seen.add((row[0], row[2], row[1])); _own.append(row)
execute_values(c, "INSERT INTO core.occurrence_ownership (occurrence_id, owner_name, company_id, ownership_role, share_pct, as_of_year, source_system, footnote, created_by) VALUES %s",
               [(o, n, comp.get(nz(n)), role, sh, yr, src, fn, tg) for o, n, role, sh, yr, src, fn, tg in _own], page_size=1000)
log("external ids", len(ext), "| ownership rows", len(_own), "| unmapped commodity names (top 20)", dict(unmapped.most_common(20)),
    "| countries without a jurisdiction", {k: v for k, v in nojur.items() if v})
with open(os.path.join(HERE, f"usgs_{REGION.lower()}_load_log_20261110{'_DRY' if DRY else ''}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["layer", "action", "usgs_id", "name", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)
years = sorted({x["year"] for x in FAC if x["year"]})
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'U.S. Geological Survey',%s,'U.S. Government work (public domain)',%s,true,%s,true,%s,%s,%s,'2026-11-10',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, DATASET, URL, f"Source: U.S. Geological Survey, {CITE}.",
           "Cleared: USGS data release (public domain; ScienceBase lists no use constraints) - checked 2026-11-10. Loaded 2026-11-10.",
           f"Facilities = USGS Minerals Yearbook country chapters, data year {', '.join(map(str, years))}; status 'Assumed Active' is USGS's assumption, not verified; "
           "capacities are often ore or gross tonnage and some are shared between facilities. Fuel (oil, gas, coal, refineries) not loaded. Exploration / development "
           "projects give the stage when last verified (year in comments) - often out of date. Many positions approximate (AREA_CENTROID).", EVID, TAG))


def one(sql, p=None):
    c.execute(sql, p); return c.fetchall()


log("new occurrences: n / deposits / with commodities / no jurisdiction", one("""SELECT count(*), count(*) FILTER (WHERE is_deposit), count(*) FILTER (WHERE array_length(commodities,1) > 0),
    count(*) FILTER (WHERE jurisdiction_id IS NULL) FROM core.occurrences WHERE created_by = %s""", (TAG,)))
log("new by status", one("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)))
log("new by country (top 12)", one("SELECT country_name, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC LIMIT 12", (TAG,)))
log("country mismatch (USGS country vs point's jurisdiction): sample", one("""SELECT o.name, o.country_name FROM core.occurrences o WHERE created_by = %s AND jurisdiction_id IS NULL LIMIT 5""", (TAG,)))
log("capacity rows: n / with value / mapped commodity / by stage", one("SELECT count(*), count(annual_capacity), count(commodity_id) FROM core.facility_capacity WHERE source_system = %s", (SRC,)),
    one("SELECT facility_stage, count(*) FROM core.facility_capacity WHERE source_system = %s GROUP BY 1 ORDER BY 2 DESC", (SRC,)))
log("largest capacities (sanity)", one("""SELECT o.name, fc.commodity_name, fc.product_form, fc.annual_capacity, fc.capacity_unit, fc.data_year FROM core.facility_capacity fc JOIN core.occurrences o USING (occurrence_id)
    WHERE fc.source_system = %s AND fc.capacity_unit = 'mt' ORDER BY fc.annual_capacity DESC NULLS LAST LIMIT 6""", (SRC,)))
log("units", one("SELECT capacity_unit, count(*) FROM core.facility_capacity WHERE source_system = %s GROUP BY 1 ORDER BY 2 DESC", (SRC,)))
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
