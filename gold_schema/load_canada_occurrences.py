"""Canadian provincial mineral-occurrence inventories -> interzona_cm core.occurrences (+ commodities, external ids, provinces).

Sources (licences checked 2026-11-03, evidence in D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_*):
  QUEBEC_SIGEOM   MRNF Québec, 'Indices, gîtes, mines et carrières' (CC BY 4.0): metallic substances CSV (one row per mineralised body,
                  aggregated here to one occurrence per gîte, NUMR_GITE) and non-metallic substances CSV (one row per occurrence, NUMR_GISM).
  SASK_SMDI       Saskatchewan Geological Survey, Saskatchewan Mineral Deposit Index (Government of Saskatchewan Standard Unrestricted Use Data
                  Licence v2.0), all 6,070 records from the GeoAtlas map service; ANOMALY records (917, geochemical/geophysical anomalies, not
                  mineral occurrences) are not loaded.
Rules
  * status: QC MA -> PRODUCER, MF -> PAST_PRODUCER, G (gîte, with an estimate) -> PROSPECT, P / I (worked / unworked showing) -> OCCURRENCE;
    SK Deposit: Production -> PRODUCER, Post-Production -> PAST_PRODUCER, Development -> DEVELOPMENT, Prefeasibility -> FEASIBILITY,
    Advanced Exploration -> EXPLORATION, Prospect -> PROSPECT, Occurrence / Mineral Location -> OCCURRENCE. is_deposit for producer, past
    producer, development, feasibility, exploration-stage deposits and QC gîtes.
  * deposit type: SK DEPOSITCLASS by exact core.occurrence_types name; QC TYPL by a short explicit French -> type map; otherwise NULL (the
    source text is kept in comments / mineralization_style).
  * province: the 13 Canadian provinces and territories are added to core.jurisdictions (STATE_PROVINCE under Canada) if missing.
  * duplicates of the old USGS MRDS Canadian records (same place: within 200 m, or within 1 km sharing a name word) are MERGED: everything that
    points at the MRDS occurrence (sample links, projects, resource estimates, documents, samples, ownership, mineralogy, endowment, its
    external id) is re-pointed to the provincial occurrence and the MRDS row is set is_active = false. A provincial record that matches a
    non-MRDS occurrence is not created; its external id is attached to the existing occurrence instead.
  * every merge / re-point is written to canada_merge_log_<timestamp>.csv (rollback list).
Usage: python load_canada_occurrences.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import csv, os, re, sys, json, glob, time, datetime, collections
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree

DRY = "--dry" in sys.argv
TAG = "migration_canada_occ_20261103"
HERE = os.path.dirname(os.path.abspath(__file__))
CAN = "D:/CriticalMineralsDB/Canada"
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def num(s):
    try: return float(str(s).strip())
    except (TypeError, ValueError): return None


PROVINCES = [("Alberta", "CA-AB"), ("British Columbia", "CA-BC"), ("Manitoba", "CA-MB"), ("New Brunswick", "CA-NB"),
             ("Newfoundland and Labrador", "CA-NL"), ("Nova Scotia", "CA-NS"), ("Ontario", "CA-ON"), ("Prince Edward Island", "CA-PE"),
             ("Quebec", "CA-QC"), ("Saskatchewan", "CA-SK"), ("Northwest Territories", "CA-NT"), ("Nunavut", "CA-NU"), ("Yukon", "CA-YT")]

# ------------------------------------------------------------------ commodity vocabularies -> core.commodities names
QC_SYM = {"ETR": "REE", "ETRL": "LREE", "ETRL_": "LREE", "ETRH": "HREE", "EGP": "PGE", "U3O8": "U", "TiO2": "Ti", "Fe2O3": "Fe"}
QC_MIN = {"GP": "Graphite", "MI": "Mica", "CS": "Chrysotile", "AP": "Apatite", "FP": "Feldspar", "QZ": "Quartz", "SM": "Sillimanite", "TC": "Talc",
          "GR": "Garnet", "DD": "Diamond", "OC": "Ochre", "MN": "MgCO3", "BL": "Beryl", "FL": "Fluorite", "WL": "Wollastonite", "BR": "Baryte",
          "BC": "Mg", "NP": "Nepheline Syenite", "SO": "Spodumene", "CC": "Calcite", "KY": "Kyanite", "VM": "Vermiculite", "SE": "Serpentine",
          "DM": "Limestone", "SL": "Silica Sand", "SI": "SiO2", "GY": "Gypsum", "KA": "Kaolin", "ZE": "Zeolite", "OL": "Olivine", "PE": "Perlite",
          "CO": "Corundum", "ZR": "Zircon", "AN": "Andalusite", "DI": "Diatomite", "PH": "Phosphate Rock", "SA": "Salt", "AS": "Asbestos",
          "TO": "Tourmaline", "MG": "Magnetite", "IL": "Ilmenite", "RU": "Rutile", "MO": "Molybdenite", "PY": "Pyrite", "BE": "Beryl"}
ELEMENTS = {"uranium": "U", "gold": "Au", "copper": "Cu", "iron": "Fe", "zinc": "Zn", "nickel": "Ni", "thorium": "Th", "lead": "Pb",
            "molybdenum": "Mo", "silver": "Ag", "cobalt": "Co", "phosphorus": "P", "lithium": "Li", "magnesium": "Mg", "tungsten": "W",
            "boron": "B", "bromine": "Br", "cerium": "Ce", "zirconium": "Zr", "titanium": "Ti", "iodine": "I", "vanadium": "V", "platinum": "Pt",
            "palladium": "Pd", "chromium": "Cr", "manganese": "Mn", "niobium": "Nb", "tantalum": "Ta", "beryllium": "Be", "tin": "Sn",
            "bismuth": "Bi", "arsenic": "As", "antimony": "Sb", "cadmium": "Cd", "selenium": "Se", "tellurium": "Te", "gallium": "Ga",
            "germanium": "Ge", "indium": "In", "yttrium": "Y", "scandium": "Sc", "lanthanum": "La", "neodymium": "Nd", "dysprosium": "Dy",
            "rhodium": "Rh", "osmium": "Os", "iridium": "Ir", "ruthenium": "Ru", "cesium": "Cs", "caesium": "Cs", "rubidium": "Rb",
            "strontium": "Sr", "barium": "Ba", "potassium": "K", "aluminum": "Al", "aluminium": "Al", "sulphur": "S", "sulfur": "S",
            "fluorine": "F", "mercury": "Hg", "silicon": "Si", "hafnium": "Hf", "rhenium": "Re", "thallium": "Tl"}
SK_NAMES = {"coal (non-metallurgical)": "Coal", "coal (metallurgical)": "Coal", "coal": "Coal", "rare earth element (unspecified)": "REE",
            "rare earth elements": "REE", "light rare earth element (unspecified)": "LREE", "heavy rare earth element (unspecified)": "HREE", "praseodymium": "Pr", "diamond": "Diamond", "sodium sulphate": "Thenardite", "kaolin": "Kaolin", "graphite": "Graphite",
            "oil shale": "Oil Shale", "potash": "Potash", "aggregate (unspecified)": "Primary Aggregate", "dimension stone (unspecified)":
            "Miscellaneous Dimension Stones", "limestone": "Limestone", "fluorspar": "Fluorite", "silica sand": "Silica Sand", "beryl": "Beryl",
            "bentonite": "Bentonite", "salt": "Salt", "sodium": "Salt", "chlorine": "Salt", "gypsum": "Gypsum", "clay": "Clay", "garnet": "Garnet",
            "feldspar": "Feldspar", "quartz": "Quartz", "talc": "Talc", "mica": "Mica", "apatite": "Apatite", "magnesite": "MgCO3",
            "pegmatite": None, "helium": None, "calcium": None, "sand and gravel": "Sand and Gravel", "peat": "Peat", "monazite": "Monazite",
            "spodumene": "Spodumene", "zircon": "Zircon", "ilmenite": "Ilmenite", "magnetite": "Magnetite", "hematite": "Hematite"}

# QC TYPL (French) -> core.occurrence_types name, only where the French type is unambiguous
QC_TYPE = {
    "Veine aurifère mésothermale, à gangue de quartz et de carbonates": "Mesozonal orogenic gold",
    "Formation de fer de type Lac Supérieur": "Superior-type banded iron formation",
    "Minéralisation de fer et titane dans des anorthosites": "Anorthosite massif titanium",
    "Minéralisation magmatique, Ni-Cu dominant (±Co ±EGP)": "U-M intrusion nickel-copper-PGE",
    "Minéralisation magmatique, Ni-Cu dominant (±Co ±EGP) associée aux intrusions mafiques à ultramafiques diverses": "U-M intrusion nickel-copper-PGE",
    "Minéralisation de métaux rares, associée aux roches hyperalcalines": "Peralkaline igneous HFSE-REE",
    "Formation de fer de type Algoma": "Algoma-type banded iron formation",
    "Minéralisation de type porphyrique à Cu-Mo": "Porphyry copper-molybdenum",
    "Minéralisation de type porphyrique à Cu-Au": "Porphyry copper-gold",
    "Gîte d'uranium associé à une discordance": "Unconformity-related uranium",
    "Carbonatite": "Carbonatite REE",
}
GENERIC = {"mine", "mines", "lake", "lac", "deposit", "showing", "showings", "property", "prospect", "occurrence", "indice", "zone", "river",
           "riviere", "creek", "mount", "mont", "north", "south", "east", "west", "nord", "sud", "est", "ouest", "gold", "copper", "uranium",
           "the", "and", "canton", "lot", "rang", "site", "claim", "claims", "group", "main", "number", "petit", "grand", "pointe", "baie"}


def words(name):
    t = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().translate(str.maketrans("éèêëàâäîïôöùûüç", "eeeeaaaiioouuuc")))
    return {w for w in t.split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


def note(*pairs):
    return "; ".join(f"{k}: {v}" for k, v in pairs if v not in (None, "", "N/A"))


# ------------------------------------------------------------------ read Québec
def qc_rows(path):
    return list(csv.DictReader(open(path, encoding="cp1252").read().splitlines()))


recs = []   # dict: src, sid, name, lon, lat, status, is_deposit, prim[], sec[], type_name, form, style, comments, province, raw_status
QC_STATUS = {"MA": ("PRODUCER", True), "MF": ("PAST_PRODUCER", True), "G": ("PROSPECT", True), "P": ("OCCURRENCE", False), "I": ("OCCURRENCE", False)}
RANK = {"MA": 5, "MF": 4, "G": 3, "P": 2, "I": 1}
bodies = collections.defaultdict(list)
for r in qc_rows(f"{CAN}/Quebec_SIGEOM_occurrences/Substances_metalliques.csv"):
    bodies[r["NUMR_GITE"]].append(r)
for gite, bs in bodies.items():
    best = max(bs, key=lambda r: (RANK.get(r["CODE_ETAT"], 0), r["IDNT_CORPS"] == "1"))
    prim, sec = [], []
    for r in bs:
        prim += [r["SUBST_PRIN"]] + [r[f"SUBST_P{i}"] for i in range(2, 13)]
        sec += [r["SUBST_SECN"]] + [r[f"SUBST_S{i}"] for i in range(2, 13)]
    st, dep = QC_STATUS.get(best["CODE_ETAT"], ("UNKNOWN", False))
    lith = sorted({r[f"ROCHE_LIT{i}"] for r in bs for i in range(1, 9) if r[f"ROCHE_LIT{i}"]})
    minr = sorted({r[f"MINR{i}"] for r in bs for i in range(1, 26) if r[f"MINR{i}"]})
    recs.append(dict(src="QUEBEC_SIGEOM", sid=f"GITE:{gite}", name=best["NOM_GITE"].strip() or f"SIGÉOM gîte {gite}",
                     lon=num(best["Coord_X"]), lat=num(best["Coord_Y"]), status=st, is_deposit=dep, prim=prim, sec=sec, kind="sym",
                     type_name=QC_TYPE.get(best["TYPL"]), form=best["DESCR_FORM"] or None, style=best["TYPL"] or None, province="Quebec",
                     raw_status=best["ETAT_CORPS"],
                     comments=note(("Source", "MRNF Québec SIGÉOM metallic substances (CC BY 4.0)"), ("SIGÉOM gîte", gite),
                                   ("Status (SIGÉOM)", best["ETAT_CORPS"]), ("Mineralised bodies", len(bs) if len(bs) > 1 else None),
                                   ("Type (SIGÉOM)", best["TYPL"]), ("Distribution", best["DESCR_DIST"]), ("Structural setting", best["DESCR_TYPE"]),
                                   ("Importance", best["DESCR_IMPR"]), ("Resource estimate on record", "yes" if any(r["RESS_ESTIM"] == "O" for r in bs) else None),
                                   ("Host rock codes", ", ".join(sorted({r[f"CODE_LIT{i}"] for r in bs for i in range(1, 9) if r[f"CODE_LIT{i}"]})) or None),
                                   ("Mineral codes", ", ".join(minr) or None), ("Discovery year", best["DECV_AN"]), ("NTS sheet", best["NUMR_SNRC"]),
                                   ("Fiche", best["LIEN_FICHE"]))))
for r in qc_rows(f"{CAN}/Quebec_SIGEOM_occurrences/Indice_ou_gite_non_metallique.csv"):
    code = r["ETAT_GISM"].split(" ")[0] if r["ETAT_GISM"] else ""
    st, dep = QC_STATUS.get(code, ("UNKNOWN", False))
    mins = [r[f"MINR{i}"] for i in range(1, 6) if r[f"MINR{i}"]]
    recs.append(dict(src="QUEBEC_SIGEOM", sid=f"GISM:{r['NUMR_GISM']}", name=r["NOM_GISM"].strip() or f"SIGÉOM non-metallic {r['NUMR_GISM']}",
                     lon=num(r["Coord_X"]), lat=num(r["Coord_Y"]), status=st, is_deposit=dep,
                     prim=[m.split(" ")[0] for m in mins[:1]], sec=[m.split(" ")[0] for m in mins[1:]], kind="qcmin",
                     type_name=None, form=(r["FORM_MORP1"] or "").partition(" ")[2] or None, style=None, province="Quebec", raw_status=r["ETAT_GISM"],
                     comments=note(("Source", "MRNF Québec SIGÉOM non-metallic substances (CC BY 4.0)"), ("SIGÉOM gisement", r["NUMR_GISM"]),
                                   ("Status (SIGÉOM)", r["ETAT_GISM"]), ("Minerals", ", ".join(mins)), ("Discovery", r["COMN_DEC"]),
                                   ("Production / reserves", r["NOTE_PROD"]), ("Lithology", r["NOTE_LITH"]), ("Grade notes", r["NOTE_MINR"]),
                                   ("Location", r["NOTE_LOCL"]), ("NTS sheet", r["NUMR_SNRC"]))))
log("Québec occurrences", sum(1 for r in recs if r["src"] == "QUEBEC_SIGEOM"), "(metallic gîtes", len(bodies), ")")

# ------------------------------------------------------------------ read Saskatchewan
SK_STATUS = [("Deposit: Production", "PRODUCER", True), ("Deposit: Post-Production", "PAST_PRODUCER", True), ("Deposit: Development", "DEVELOPMENT", True),
             ("Deposit: Prefeasibility", "FEASIBILITY", True), ("Deposit: Feasibility", "FEASIBILITY", True), ("Deposit: Advanced Exploration", "EXPLORATION", True),
             ("Prospect", "PROSPECT", False), ("Occurrence", "OCCURRENCE", False), ("Mineral Location", "OCCURRENCE", False)]
n_anom = 0
for f in sorted(glob.glob(f"{CAN}/Saskatchewan_SMDI/*.geojson")):
    for ft in json.load(open(f, encoding="utf-8"))["features"]:
        p = ft["properties"]; s = p["STATUS"] or ""
        if s.startswith("Anomaly"): n_anom += 1; continue
        st, dep = next(((a, b) for k, a, b in SK_STATUS if s.startswith(k)), ("UNKNOWN", False))
        lon, lat = (ft["geometry"] or {}).get("coordinates", [None, None])[:2]
        upd = p["DATE_LASTUPDATED"]
        upd = datetime.datetime.fromtimestamp(int(upd) / 1000, datetime.timezone.utc).date().isoformat() if upd and str(upd).isdigit() else None
        recs.append(dict(src="SASK_SMDI", sid=str(p["SMDI"]), name=(p["NAME"] or "").strip() or f"SMDI {p['SMDI']}", lon=lon, lat=lat,
                         status=st, is_deposit=dep, prim=(p["PRIMARYCOMMODITIES"] or "").split(","), sec=(p["ASSOCIATEDCOMMODITIES"] or "").split(","),
                         kind="name", type_name=p["DEPOSITCLASS"], form=None, style=None, province="Saskatchewan", raw_status=s,
                         comments=note(("Source", "Saskatchewan Mineral Deposit Index (Government of Saskatchewan Standard Unrestricted Use Data Licence v2.0)"),
                                       ("SMDI", p["SMDI"]), ("Status (SMDI)", s), ("Grouping", p["GROUPING"]), ("Discovery", p["DISCOVERYTYPE"]),
                                       ("Production", p["PRODUCTION"]), ("Reserves or resources reported", p["RESERVESRESOURCES"]),
                                       ("Company (SMDI)", p["COMPANYNAME"]), ("Project (SMDI)", p["PROJECTNAME"]), ("Host rock", p["HOSTROCK"]),
                                       ("Host mineral", p["HOSTMINERAL"]), ("Deposit class", p["DEPOSITCLASS"]), ("Historic names", p["HISTORICNAMES"]
                                       if p["HISTORICNAMES"] != p["NAME"] else None), ("Assessment files", (p["ASSESSMENTFILES"] or "").strip(", ") or None),
                                       ("Record updated", upd), ("SMDI page", p["WEBLINK"]))))
log("Saskatchewan occurrences", sum(1 for r in recs if r["src"] == "SASK_SMDI"), "| anomalies not loaded", n_anom)
bad = [r for r in recs if r["lat"] is None or r["lon"] is None or not (40 < r["lat"] < 84 and -142 < r["lon"] < -50)]
recs = [r for r in recs if r not in bad]
log("records without a usable location (skipped)", len(bad))

# ------------------------------------------------------------------ gold
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system IN ('QUEBEC_SIGEOM','SASK_SMDI')")
assert c.fetchone()[0] == 0, "already loaded"

c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = 'Canada'"); CANADA = c.fetchone()[0]
for name, iso in PROVINCES:
    c.execute("""INSERT INTO core.jurisdictions (parent_jurisdiction_id, level, name, official_name, iso_code, is_active, created_by, created_date)
                 SELECT %s, 'STATE_PROVINCE', %s, %s, %s, true, %s, now() WHERE NOT EXISTS (SELECT 1 FROM core.jurisdictions WHERE iso_code = %s)""",
              (CANADA, name, name, iso, TAG, iso))
c.execute("SELECT name, jurisdiction_id FROM core.jurisdictions WHERE parent_jurisdiction_id = %s", (CANADA,)); PROV = dict(c.fetchall())
log("Canadian provinces/territories in jurisdictions", len(PROV))

c.execute("SELECT commodity_name, commodity_id, commodity_symbol FROM core.commodities")
COM = {}
for name, cid, sym in c.fetchall():
    COM[name.lower()] = cid
    if sym: COM[sym.lower()] = cid
c.execute("SELECT type_name, occurrence_type_id FROM core.occurrence_types"); OTYPE = {k.lower(): v for k, v in c.fetchall()}
unmapped = collections.Counter()


def cid_for(tok, kind):
    t = (tok or "").strip()
    if not t: return None
    if kind == "sym": key = QC_SYM.get(t, t)
    elif kind == "qcmin": key = QC_MIN.get(t.upper(), t)
    else:
        tl = t.lower()
        key = SK_NAMES[tl] if tl in SK_NAMES else ELEMENTS.get(tl, t)
        if key is None: unmapped[t] += 1; return None
    v = COM.get(str(key).lower())
    if v is None: unmapped[t] += 1
    return v


# existing occurrences in Canada (for duplicate detection)
c.execute("SELECT occurrence_id, name, lat, lon, created_by FROM core.occurrences WHERE is_active AND country_name = 'Canada' AND lat IS NOT NULL")
ex = c.fetchall()
lat0 = np.radians(55)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
tree = cKDTree(xy([e[2] for e in ex], [e[3] for e in ex]))
P = xy([r["lat"] for r in recs], [r["lon"] for r in recs])
merge, attach, used = [], [], set()
for i, r in enumerate(recs):
    best = None
    for j in tree.query_ball_point(P[i], 1000):
        if j in used: continue
        d = float(np.hypot(*(P[i] - tree.data[j])))
        if d <= 200 or (words(r["name"]) & words(ex[j][1])):
            if best is None or d < best[1]: best = (j, d)
    if best:
        j = best[0]; used.add(j)
        (merge if ex[j][4] == "migration_mrds_20261014" else attach).append((i, ex[j][0], round(best[1])))
log("matches: MRDS to merge", len(merge), "| non-MRDS (attach id, no new row)", len(attach))
attach_idx = {i for i, _, _ in attach}

# insert new occurrences
rows, keep = [], []
for i, r in enumerate(recs):
    if i in attach_idx: continue
    keep.append(i)
    rows.append((r["name"][:250], r["is_deposit"], PROV[r["province"]], f"SRID=4326;POINT({r['lon']} {r['lat']})", r["status"],
                 OTYPE.get((r["type_name"] or "").lower()), r["form"], r["style"], r["comments"], True, TAG))
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, occurrence_type_id, deposit_form,
                           mineralization_style, comments, is_active, created_by, created_date)
                           VALUES %s RETURNING occurrence_id""",
                     [x for x in rows], template="(%s,%s,%s,ST_GeomFromEWKT(%s),%s,%s,%s,%s,%s,%s,%s,now())", fetch=True, page_size=2000)
newid = {i: x[0] for i, x in zip(keep, ids)}
for i, oid, _ in attach: newid[i] = oid
log("new occurrences", len(ids))

execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("OCCURRENCE", newid[i], r["src"], r["sid"], TAG) for i, r in enumerate(recs)], page_size=5000)
links, seen = [], set()
for i, r in enumerate(recs):
    if i in attach_idx: continue
    for role, toks in (("PRIMARY", r["prim"]), ("SECONDARY", r["sec"])):
        for t in toks:
            v = cid_for(t, r["kind"])
            if v and (newid[i], v) not in seen:
                seen.add((newid[i], v)); links.append((newid[i], v, role, True, TAG))
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links, page_size=5000)
log("commodity links", len(links), "| unmapped tokens", sum(unmapped.values()), unmapped.most_common(15))
# (core.occurrences.commodities is refreshed by the trg_refresh_occurrence_commodities trigger)

# merge MRDS duplicates into the provincial occurrence (re-point references, deactivate the MRDS row), logged
REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
           ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
           ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id")]
logrows = []
for i, old, d in merge:
    new = newid[i]
    for tbl, col in REPOINT:
        c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new, old))
        if c.rowcount: logrows.append(("repoint", tbl, old, new, c.rowcount, d))
    c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (new, old))
    if c.rowcount: logrows.append(("repoint", "core.external_ids(USGS_MRDS)", old, new, c.rowcount, d))
    c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (TAG, old))
    logrows.append(("deactivate", "core.occurrences", old, new, 1, d))
for i, oid, d in attach: logrows.append(("attach_external_id", recs[i]["src"] + ":" + recs[i]["sid"], oid, oid, 1, d))
path = os.path.join(HERE, f"canada_merge_log_{STAMP}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["action", "table", "old_occurrence_id", "new_occurrence_id", "rows", "distance_m"]); w.writerows(logrows)
log("merge log", path, "| entries", len(logrows))

# data sources
for src, pub, ds, lic, url, attr, ev in [
    ("QUEBEC_SIGEOM", "Gouvernement du Québec, Ministère des Ressources naturelles et des Forêts (MRNF), Géologie Québec (SIGÉOM)",
     "Indices, gîtes, mines et carrières: metallic substances and non-metallic substances (CSV, updated 2025-10-08)", "CC BY 4.0",
     "https://creativecommons.org/licenses/by/4.0/", "Ministère des Ressources naturelles et des Forêts, Québec. Indices, gîtes, mines et carrières (SIGÉOM), Données Québec, 2025. CC BY 4.0.",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_QUEBEC_SIGEOM/"),
    ("SASK_SMDI", "Government of Saskatchewan, Saskatchewan Geological Survey", "Saskatchewan Mineral Deposit Index (SMDI), GeoAtlas map service, retrieved 2026-11-03",
     "Government of Saskatchewan Standard Unrestricted Use Data Licence v2.0", None,
     "Saskatchewan Mining and Petroleum GeoAtlas, Saskatchewan Mineral Deposit Index, retrieved 3 November 2026. Contains information licensed under the Government of Saskatchewan Standard Unrestricted Use Data Licence (Version 2.0).",
     "D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_SASKATCHEWAN_SMDI/")]:
    c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
                 licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
                 VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-03',true,%s,now()) ON CONFLICT DO NOTHING""",
              (src, pub, ds, lic, url, attr, f"Cleared: {lic} stated on the publisher's metadata (checked 2026-11-03). Loaded 2026-11-03.",
               "Occurrence inventory compiled by the provincial survey from government and assessment-report data; status and resource flags as recorded by the survey.", ev, TAG))

# verification
c.execute("""SELECT j.name, count(*), count(*) FILTER (WHERE o.is_deposit), count(o.occurrence_type_id), count(*) FILTER (WHERE array_length(o.commodities,1) > 0)
             FROM core.occurrences o JOIN core.jurisdictions j USING (jurisdiction_id) WHERE o.created_by = %s GROUP BY 1""", (TAG,))
log("by province (n, deposits, with type, with commodities)", c.fetchall())
c.execute("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); log("status", c.fetchall())
c.execute("SELECT count(*) FROM core.occurrences WHERE country_name = 'Canada' AND is_active"); log("active Canadian occurrences now", c.fetchone()[0])
c.execute("""SELECT count(*) FROM core.occurrences o WHERE o.created_by = %s AND NOT ST_Intersects(o.geom, ST_MakeEnvelope(-142, 40, -50, 84, 4326))""", (TAG,))
log("outside Canada box (must be 0)", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
