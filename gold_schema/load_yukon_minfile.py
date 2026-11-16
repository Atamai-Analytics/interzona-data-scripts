"""Yukon MINFILE occurrences + Yukon mineral-deposit resource estimates -> interzona_cm (core.occurrences, occurrence_commodities, external_ids,
resource_estimates). Tag migration_yukon_minfile_20261116.

Sources (Government of Yukon, Open Government Licence - Yukon v2.0, commercial use with attribution; evidence Licence_Evidence/YUKON_YGS_RGS/LICENCE_NOTES.md):
  Mineral_Occurrences_250k.fgdb.zip       MINFILE, 3,223 records (map-data.service.yukon.ca, folder dated 2026-11-15; records modified to 2026)
  Mineral_Deposits_by_Zone.fgdb.zip       186 zone resource statements (NI 43-101 / JORC / historic), YGS mineral deposits inventory (to 2024)
Rules
  * MINFILE 'Anomaly' records (574, geochemical/geophysical anomalies with no mineralisation found) are NOT loaded (same rule as Saskatchewan SMDI).
  * status: Deposit -> is_deposit, status UNKNOWN (MINFILE's PRODUCER_IND is 'Y' for every 'Deposit', including never-mined ones such as Mactung,
    so it is NOT a production flag); Prospect -> PROSPECT; Showing -> OCCURRENCE; Unknown -> UNKNOWN.
  * deposit type: MINFILE DEPOSIT_TYPE kept in mineralization_style; occurrence_type_id only for an unambiguous match (TYPE_MAP).
  * commodities: MAIN_COMMODITY tokens (first PRIMARY, rest SECONDARY) mapped to core.commodities.
  * duplicates (same rule as load_canada_occurrences.py): an active occurrence within 200 m, or within 1 km sharing a name word. Old USGS MRDS
    records are MERGED into the MINFILE occurrence (references re-pointed, MRDS producer/past-producer status kept, MRDS row inactive, logged); a match to any other source attaches the
    MINFILE id to that occurrence (no new row).
  * resources: one resource_estimates row per zone x commodity: tonnage t, average grade, contained metal (Au/Ag/Pt/Pd koz; base metals converted
    from lb to t); classification = YGS's combined categories (YGS summed the categories - not a single-category figure); reporting standard
    NI 43-101 / JORC code / Historic estimate; effective_date = YGS reference date. Zone -> occurrence: a Yukon occurrence within 3 km sharing a word
    with the property or zone name, else the nearest within 1 km; unmatched zones are reported and not loaded.
Every merge / attach is written to yukon_minfile_merge_log_<stamp>.csv. Usage: python load_yukon_minfile.py [--dry]
"""
import csv, datetime, os, re, sys, collections
import numpy as np
import psycopg2, pyogrio, warnings
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree
warnings.filterwarnings("ignore")

DRY = "--dry" in sys.argv
TAG = "migration_yukon_minfile_20261116"
SRC, RSRC = "YUKON_MINFILE", "YUKON_MINERAL_DEPOSITS"
D = "D:/CriticalMineralsDB/Yukon/_m/"
HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

ELEMENTS = {"uranium": "U", "gold": "Au", "copper": "Cu", "iron": "Fe", "zinc": "Zn", "nickel": "Ni", "thorium": "Th", "lead": "Pb", "molybdenum": "Mo",
            "silver": "Ag", "cobalt": "Co", "phosphorus": "P", "lithium": "Li", "magnesium": "Mg", "tungsten": "W", "cerium": "Ce", "zirconium": "Zr",
            "titanium": "Ti", "vanadium": "V", "platinum": "Pt", "palladium": "Pd", "chromium": "Cr", "manganese": "Mn", "niobium": "Nb", "tantalum": "Ta",
            "beryllium": "Be", "tin": "Sn", "bismuth": "Bi", "arsenic": "As", "antimony": "Sb", "cadmium": "Cd", "selenium": "Se", "tellurium": "Te",
            "gallium": "Ga", "germanium": "Ge", "indium": "In", "yttrium": "Y", "lanthanum": "La", "neodymium": "Nd", "dysprosium": "Dy", "rhodium": "Rh",
            "osmium": "Os", "iridium": "Ir", "ruthenium": "Ru", "strontium": "Sr", "barium": "Ba", "fluorine": "F", "mercury": "Hg", "rhenium": "Re",
            "thallium": "Tl", "ytterbium": "Yb", "holmium": "Ho", "gadolinium": "Gd", "praseodymium": "Pr", "thulium": "Tm",
            "barite": "Baryte", "coal": "Coal", "asbestos": "Asbestos", "chrysotile": "Chrysotile", "rare earths": "REE", "fluorite": "Fluorite",
            "gypsum": "Gypsum", "magnetite": "Magnetite", "limestone": "Limestone", "tungsten trioxide": "WO3", "beryl": "Beryl", "jade/nephrite": "Jade",
            "silica": "SiO2", "emerald": "Emerald", "wolframite": "W", "molybdenum disulfide": "Mo", "copper - oxide": "Cu", "copper - total": "Cu",
            "copper - sulphide": "Cu", "phosphate": "Phosphate Rock", "rhodonite": "Rhodonite", "pge": "PGE",
            "gemstones": None, "pyrrhotite": None, "calcium": None}
TYPE_MAP = {"Sediment hosted Mississippi Valley-Type Pb-Zn (MVT)": "MVT zinc-lead", "Skarn W": "Skarn tungsten", "Skarn Cu": "Skarn copper",
            "Skarn Pb-Zn": "Skarn zinc-lead-silver", "Vein Polymetallic Ag-Pb-Zn+/-Au": "Vein polymetallic",
            "Ultramafic Mafic Gabbroid Cu-Ni-PGE": "U-M intrusion nickel-copper-PGE"}
GENERIC = {"mine", "mines", "lake", "deposit", "showing", "showings", "property", "prospect", "occurrence", "zone", "river", "creek", "mount",
           "north", "south", "east", "west", "gold", "copper", "silver", "the", "and", "site", "claim", "claims", "group", "main", "number",
           "project", "district", "hill", "mountain", "range", "central", "upper", "lower"}
STATUS = {"Deposit": "UNKNOWN", "Prospect": "PROSPECT", "Showing": "OCCURRENCE", "Unknown": "UNKNOWN"}
UNITS = {"AU": ("Au", "g/t", "OZ"), "AG": ("Ag", "g/t", "OZ"), "PT": ("Pt", "g/t", "OZ"), "PD": ("Pd", "g/t", "OZ"),
         "CU": ("Cu", "%", "LBS"), "MO": ("Mo", "%", "LBS"), "PB": ("Pb", "%", "LBS"), "ZN": ("Zn", "%", "LBS"), "NI": ("Ni", "%", "LBS"),
         "CO": ("Co", "%", "LBS"), "WO3": ("WO3", "%", "LBS"), "SN": ("Sn", "%", "LBS"), "SB": ("Sb", "%", "LBS"), "FE": ("Fe", "%", "LBS"),
         "BASO4": ("Baryte", "%", "TONNES")}
STD = {"43-101": "NI 43-101", "JORC": "JORC code", "Historic": "Historic estimate"}


def classification(rr, cats):
    if not cats or cats == "Unspecified":
        return "Reserve (category not stated)" if rr == "Reserve" else "Resource, category not stated"
    t = "+".join(x.strip() for x in cats.split(","))
    return t if len(t) <= 30 else "Combined (all categories)"


def words(name):
    t = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return {w for w in t.split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


def log(*a):
    print(time_s(), *a, flush=True)


def time_s():
    return datetime.datetime.now().strftime("%H:%M:%S")


def isna(v):
    return v is None or (isinstance(v, float) and v != v)


o = pyogrio.read_dataframe(D + "Mineral_Occurrences_250k/Mineral_Occurrences_250k.gdb", read_geometry=False)
z = pyogrio.read_dataframe(D + "Mineral_Deposits_by_Zone/Mineral_Deposits_by_Zone.gdb", read_geometry=False)
stats = collections.Counter()
recs = []
for r in o.itertuples(index=False):
    st = r.DEPOSIT_STATUS
    if st == "Anomaly": stats["anomaly not loaded"] += 1; continue
    toks = [t.strip() for t in (r.MAIN_COMMODITY or "").split(",") if t.strip()]
    toks = [x for t in toks for x in (("lead", "zinc") if t == "lead + zinc" else (t,))]
    dtype = None if isna(r.DEPOSIT_TYPE) or r.DEPOSIT_TYPE == "Unknown" else r.DEPOSIT_TYPE
    mod = r.LAST_MODIFIED_DATE.strftime("%Y-%m-%d") if not isna(r.LAST_MODIFIED_DATE) and hasattr(r.LAST_MODIFIED_DATE, "strftime") else None
    note = "; ".join(x for x in [
        f"Yukon MINFILE {r.MINFILE_NUMBER}: {r.MINFILE_FULL_LABEL}", f"MINFILE status: {st}",
        f"deposit type: {dtype}" if dtype else "", f"also known as: {r.ALIAS}" if not isna(r.ALIAS) and r.ALIAS else "",
        f"NTS {r.NTS_MAP250K}", f"record {r.LINK_TO_DOCUMENT}" if r.LINK_TO_DOCUMENT else "", f"last modified {mod}" if mod else ""] if x)
    recs.append(dict(sid=r.MINFILE_NUMBER, name=(r.MINFILE_NAME or r.MINFILE_NUMBER).strip(), lat=float(r.LATITUDE_DD), lon=float(r.LONGITUDE_DD),
                     is_deposit=st == "Deposit", status=STATUS[st], dtype=dtype, toks=toks,
                     comments=note + " | Source: Yukon Geological Survey, Yukon MINFILE. Contains information licensed under the Open Government Licence - Yukon."))
    stats["MINFILE " + st] += 1
log("MINFILE records to load", len(recs), dict(stats))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)); assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'STATE_PROVINCE' AND name = 'Yukon'"); YUKON = c.fetchone()[0]
c.execute("SELECT commodity_name, commodity_id FROM core.commodities"); COM = {n.lower(): i for n, i in c.fetchall()}
c.execute("SELECT type_name, occurrence_type_id FROM core.occurrence_types"); OTYPE = dict(c.fetchall())
unmapped = collections.Counter()


def cid_for(tok):
    t = tok.lower()
    if t not in ELEMENTS: unmapped[tok] += 1; return None
    key = ELEMENTS[t]
    if key is None: return None
    v = COM.get(key.lower()); assert v, key
    return v


# duplicates against existing active occurrences in/near Yukon
c.execute("""SELECT occurrence_id, name, lat, lon, created_by FROM core.occurrences
             WHERE is_active AND lat BETWEEN 59.5 AND 70 AND lon BETWEEN -142 AND -123 AND lat IS NOT NULL""")
ex = c.fetchall()
lat0 = np.radians(64)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
tree = cKDTree(xy([e[2] for e in ex], [e[3] for e in ex]))
P = xy([r["lat"] for r in recs], [r["lon"] for r in recs])
merge, attach, used = [], [], set()
for i, r in enumerate(recs):
    best = None
    for j in tree.query_ball_point(P[i], 1000):
        if j in used: continue
        dd = float(np.hypot(*(P[i] - tree.data[j])))
        if dd <= 200 or (words(r["name"]) & words(ex[j][1])):
            if best is None or dd < best[1]: best = (j, dd)
    if best:
        j = best[0]; used.add(j)
        (merge if ex[j][4] == "migration_mrds_20261014" else attach).append((i, ex[j][0], round(best[1]), ex[j][1]))
log("existing occurrences in the Yukon box", len(ex), "| MRDS to merge", len(merge), "| other matches (attach id)", len(attach))
attach_idx = {a[0] for a in attach}

rows, keep = [], []
for i, r in enumerate(recs):
    if i in attach_idx: continue
    keep.append(i)
    rows.append((r["name"][:250], r["is_deposit"], YUKON, f"SRID=4326;POINT({r['lon']} {r['lat']})", r["status"], OTYPE.get(TYPE_MAP.get(r["dtype"])),
                 r["dtype"], r["comments"], True, TAG))
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, occurrence_type_id, mineralization_style,
                           comments, is_active, created_by, created_date) VALUES %s RETURNING occurrence_id""",
                     rows, template="(%s,%s,%s,ST_GeomFromEWKT(%s),%s,%s,%s,%s,%s,%s,now())", fetch=True, page_size=2000)
newid = {i: x[0] for i, x in zip(keep, ids)}
for i, oid, _, _ in attach: newid[i] = oid
log("new occurrences", len(ids))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s",
               [("OCCURRENCE", newid[i], SRC, r["sid"], "MEDIUM" if i in attach_idx else "EXACT", TAG) for i, r in enumerate(recs)], page_size=5000)
links, seen = [], set()
for i, r in enumerate(recs):
    have = set()
    if i in attach_idx:
        c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (newid[i],)); have = {x[0] for x in c.fetchall()}
    for k, t in enumerate(r["toks"]):
        v = cid_for(t)
        if v and v not in have and (newid[i], v) not in seen:
            seen.add((newid[i], v)); links.append((newid[i], v, "SECONDARY" if (k or i in attach_idx) else "PRIMARY", True, TAG))
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links, page_size=5000)
log("commodity links", len(links), "| unmapped tokens", dict(unmapped))
for i, oid, _, _ in attach:
    c.execute("UPDATE core.occurrences SET comments = coalesce(comments || ' | ', '') || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
              (recs[i]["comments"], TAG, oid))

REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
           ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
           ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id")]
logrows = []
for i, old, dd, oname in merge:
    new = newid[i]
    for tbl, col in REPOINT:
        c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new, old))
        if c.rowcount: logrows.append(("repoint", tbl, old, new, c.rowcount, dd, oname, recs[i]["name"]))
    c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (new, old))
    if c.rowcount: logrows.append(("repoint", "core.external_ids(USGS_MRDS)", old, new, c.rowcount, dd, oname, recs[i]["name"]))
    # keep MRDS's production stage where MINFILE has none (MINFILE gives no production status)
    c.execute("""UPDATE core.occurrences n SET status = o.status, is_deposit = n.is_deposit OR o.is_deposit
                 FROM core.occurrences o WHERE n.occurrence_id = %s AND o.occurrence_id = %s
                   AND o.status IN ('PRODUCER','PAST_PRODUCER','DEVELOPMENT','FEASIBILITY','EXPLORATION') AND n.status IN ('UNKNOWN','PROSPECT','OCCURRENCE')
                 RETURNING o.status""", (new, old))
    kept = c.fetchone()
    if kept: logrows.append(("status_from_mrds", kept[0], old, new, 1, dd, oname, recs[i]["name"]))
    c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (TAG, old))
    logrows.append(("deactivate", "core.occurrences", old, new, 1, dd, oname, recs[i]["name"]))
for i, oid, dd, oname in attach: logrows.append(("attach_external_id", SRC + ":" + recs[i]["sid"], oid, oid, 1, dd, oname, recs[i]["name"]))

# ---------------- resource estimates by zone
c.execute("""SELECT occurrence_id, name, lat, lon FROM core.occurrences WHERE is_active AND jurisdiction_id = %s AND lat IS NOT NULL""", (YUKON,))
yo = c.fetchall()
ytree = cKDTree(xy([e[2] for e in yo], [e[3] for e in yo]))
res, nomatch = [], []
for r in z.itertuples(index=False):
    p = xy([r.LATITUDE_DD], [r.LONGITUDE_DD])[0]
    wz = words(r.PROPERTY) | words(r.ZONE)
    best = None
    for j in ytree.query_ball_point(p, 3000):
        dd = float(np.hypot(*(p - ytree.data[j])))
        score = (0 if words(yo[j][1]) & wz else 1, dd)
        if score[0] == 1 and dd > 1000: continue
        if best is None or score < best[0]: best = (score, j)
    if not best: nomatch.append((r.PROPERTY, r.ZONE)); stats["zones without an occurrence"] += 1; continue
    oid = yo[best[1]][0]
    when = r.REFERENCE_DATE.date() if not isna(r.REFERENCE_DATE) and hasattr(r.REFERENCE_DATE, "date") else None
    cls = classification(r.RESOURCE_RESERVE, r.CATEGORIES)
    cm = (f"Yukon Geological Survey mineral deposits inventory (zone summary, {r.COMMODITIES}): property {r.PROPERTY}, zone {r.ZONE}; categories "
          f"{r.CATEGORIES} ({r.RESOURCE_RESERVE.lower()}) summed by YGS - refer to the source statement for exact figures; report {r.URL}. "
          "Contains information licensed under the Open Government Licence - Yukon.")
    for key, (com, gu, cu) in UNITS.items():
        grade = getattr(r, f"AVG_{key}_{'GT' if gu == 'g/t' else 'PCT'}")
        tot = getattr(r, f"TOTAL_{key}_{cu}")
        if isna(grade) and isna(tot): continue
        if (isna(grade) or grade == 0) and (isna(tot) or tot == 0): continue
        cont, cunit = (tot / 1000.0, f"koz {com}") if cu == "OZ" else ((tot * 0.45359237 / 1000.0, f"t {com}") if cu == "LBS" else (tot, f"t {com}"))
        res.append((oid, COM[com.lower()], cls, STD.get(r.COMPLIANT, r.COMPLIANT), when, r.TONNES_TOTAL, "t",
                    None if isna(grade) else grade, f"{gu} {com}", None if isna(tot) else cont, cunit, True, TAG, RSRC, (r.ZONE or r.PROPERTY)[:200], cm))
execute_values(c, """INSERT INTO core.resource_estimates (occurrence_id, commodity_id, classification, reporting_standard, effective_date, tonnage, tonnage_unit,
                    grade, grade_unit, contained_metal, contained_metal_unit, is_active, created_by, source_system, zone_name, comments, created_date)
                    VALUES %s""", res, template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())", page_size=2000)
log("resource rows", len(res), "| zones without an occurrence", len(nomatch), nomatch[:15])

path = os.path.join(HERE, f"yukon_minfile_merge_log_{STAMP}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["action", "table", "old_occurrence_id", "new_occurrence_id", "rows", "distance_m", "existing_name", "minfile_name"]); w.writerows(logrows)
log("merge log", path, len(logrows))

for src, ds, cav in [
    (SRC, "Yukon MINFILE - Mineral Occurrences 250k (GeoYukon, records modified to 2026)",
     "MINFILE 'Anomaly' records (geochemical/geophysical anomalies) not loaded. 'Deposit' records are deposits with a resource or significant "
     "mineralisation - MINFILE's producer flag marks every deposit, so production status is UNKNOWN unless another source says otherwise. "
     "Old USGS MRDS duplicates were merged into the MINFILE records, keeping MRDS's producer / past-producer status (may be out of date)."),
    (RSRC, "Yukon mineral deposits inventory - Mineral Deposits by Zone (YGS, resource statements to 2024)",
     "YGS summed and averaged the categories of each statement (e.g. Indicated + Inferred combined) - classification shows the combined categories; "
     "includes historic (non-compliant) estimates; check the linked report for exact figures.")]:
    c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
                 licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
                 VALUES (%s,'Yukon Geological Survey (Government of Yukon)',%s,'Open Government Licence - Yukon',
                 'https://yukon.ca/en/your-government/open-government/open-government-licence-yukon',true,
                 'Yukon Geological Survey. Contains information licensed under the Open Government Licence - Yukon.',true,
                 'Cleared: open.yukon.ca dataset pages list Open Government Licence - Yukon (v2.0, commercial use with attribution); checked 2026-11-16.',
                 %s,'D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\YUKON_YGS_RGS\\','2026-11-16',true,%s,now()) ON CONFLICT DO NOTHING""", (src, ds, cav, TAG))

c.execute("SELECT status, is_deposit, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1, 2 ORDER BY 3 DESC", (TAG,)); log("new by status", c.fetchall())
c.execute("SELECT count(*) FROM core.occurrences WHERE jurisdiction_id = %s AND is_active", (YUKON,)); log("active Yukon occurrences now", c.fetchone()[0])
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND NOT ST_Intersects(geom, ST_MakeEnvelope(-141.1, 59.9, -123.7, 69.7, 4326))", (TAG,))
log("outside Yukon box (must be 0)", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED", TAG)
