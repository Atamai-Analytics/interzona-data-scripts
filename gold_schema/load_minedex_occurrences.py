"""WA MINEDEX (DMIRS-001, Mines and mineral deposits, CC BY 4.0) -> interzona_cm core.occurrences (+ commodities, external ids).

Source: Department of Energy, Mines, Industry Regulation and Safety (DEMIRS), Western Australia. Downloaded 2026-11-08 from the open
ArcGIS map service (SLIP Industry_and_Mining MapServer/0, data last updated 2026-11-06) to D:/CriticalMineralsDB/Australia/download_20261108
(minedex_part_*.json, 48,533 sites). Licence evidence: Documents/Licence_Evidence/WA_MINEDEX (catalogue API: license_id cc-by, CC BY 4.0).
Rules
  * loaded site types: Mine, Deposit, Prospect, Occurrence, Target, Geological Observation, Unknown. NOT loaded: Infrastructure
    (plants, dumps, tailings, roads, towns ...) and Other (environment sites) - about 7,950 sites.
  * status from type x stage: Operating -> PRODUCER; Care and Maintenance -> CARE_AND_MAINTENANCE; Under Development -> DEVELOPMENT;
    Mine/Deposit Proposed -> DEVELOPMENT is NOT claimed: Proposed -> FEASIBILITY for Mine/Deposit, PROSPECT otherwise;
    Mine Shut -> PAST_PRODUCER; Target -> EXPLORATION; otherwise by type (Deposit/Prospect -> PROSPECT, Occurrence/Observation -> OCCURRENCE).
    is_deposit for Mine and Deposit site types. The MINEDEX type, sub-type and stage are kept in comments.
  * commodities: MINEDEX element symbols map directly; industrial-mineral codes through CODES below; unknown or product codes are left
    unlinked (the full MINEDEX commodity string is always kept in comments).
  * duplicates of the old USGS MRDS WA records (within 200 m, or within 1 km sharing a name word) are MERGED as for Sweden/Canada:
    references re-pointed to the MINEDEX occurrence, the MRDS row deactivated, all logged to minedex_occ_merge_log_<timestamp>.csv.
Usage: python load_minedex_occurrences.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import csv, os, re, sys, glob, json, time, datetime, collections
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree

DRY = "--dry" in sys.argv
TAG = "migration_minedex_occ_20261108"
SRC = "AUSTRALIA_WA_MINEDEX"
HERE = os.path.dirname(os.path.abspath(__file__))
DL = "D:/CriticalMineralsDB/Australia/download_20261108"
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def note(*pairs):
    return "; ".join(f"{k}: {v}" for k, v in pairs if v not in (None, "", "N/A", "Unspecified"))


LOAD_TYPES = {"Mine", "Deposit", "Prospect", "Occurrence", "Target", "Geological Observation", "Unknown"}
# MINEDEX industrial-mineral / material codes -> core.commodities names (codes not listed stay unlinked)
CODES = {"Gvl": "Sand and Gravel", "Sd": "Sand and Gravel", "Sdc": "Sand and Gravel", "PisoGravel": "Sand and Gravel", "Dmd": "Diamond",
         "HM": "Heavy Mineral Sand", "Ilm": "Ilmenite", "Lst": "Limestone", "Lst-Lsd": "Limestone", "Lsd": "Limestone", "Chalk": "Limestone",
         "CaCO3": "Limestone", "Aglime": "Limestone", "Zrn": "Zircon", "Mag": "Magnetite", "Agg": "Primary Aggregate", "Aggc": "Primary Aggregate",
         "Aggm": "Primary Aggregate", "Aggd": "Primary Aggregate", "Gp": "Gypsum", "Leu": "Leucoxene", "Brl": "Beryl", "Rt": "Rutile",
         "Dst": "Miscellaneous Dimension Stones", "OrnStone": "Miscellaneous Dimension Stones", "Kln": "Kaolin", "Bx": "Bauxite",
         "Gran": "Granite", "BlackGran": "Granite", "Mnz": "Monazite", "Sisd": "Silica Sand", "Brt": "Baryte", "Gr": "Graphite", "TGC": "Graphite",
         "Grt": "Garnet", "Cyfi": "Clay", "Ball": "Clay", "IndClay": "Clay", "Clay-white": "White Firing Clay", "Brck": "Brick Clay", "Brick": "Brick Clay",
         "Phos": "Phosphate Rock", "Asb": "Asbestos", "Asbs": "Asbestos Serpentine", "Asbr": "Asbestos Amphibole", "Asba": "Asbestos Amphibole",
         "Tlc": "Talc", "Fl": "Fluorite", "Marb": "Marble", "Qtz": "Quartz", "FeOre": "Fe", "Bas": "Basalt", "NaturalGas": "Reservoir Gas",
         "Diat": "Diatomite", "Bent": "Bentonite", "Mnt": "Bentonite", "Sdst": "Sandstone", "Hem": "Hematite", "Hem-MIO": "Hematite", "Fel": "Feldspar",
         "Opalc": "Opal", "Opalg": "Opal", "CaO": "Lime", "Lignite": "Brown Coal", "Chrp": "Chrysoprase", "Tur": "Tourmaline", "K2O": "Potash",
         "Ky": "Kyanite", "Crude oil": "Oil", "Glt": "Glauconite", "Clc": "Calcite", "Cal": "Calcite", "TaNb2O5": "Ta2O5", "Cor": "Corundum",
         "Alu": "Alunite", "Toz": "Topaz", "Spon": "Spongolite", "LNG": "Reservoir Gas", "Al2O3": "Alumina", "Al2O3Bayer": "Alumina", "Shell": "Shell Grit",
         "Lpd": "Li", "Ptl": "Li", "Spd": "Spodumene", "SpdConc": "Spodumene", "Vrm": "Vermiculite", "Py": "Pyrite", "Atta": "Palygorskite",
         "Sil": "Sillimanite", "REO": "Rare Earth Oxide", "Hly": "Halloysite", "Srp": "Serpentine", "Amaz": "Amazonite", "And": "Andalusite",
         "Anh": "Anhydrite", "Ap": "Apatite", "Dy2O3": "Dy", "Tb2O3": "Tb", "ZrO2": "Zirconia", "Fe2O3": "Iron Oxide", "Prh": "Prehnite",
         "Ath": "Anthophyllite", "Vrs": "Variscite", "Vrsg": "Variscite", "Chr": "Chromite", "Crd": "Cordierite", "Trq": "Turquoise", "Mal": "Malachite",
         "Dol": "MgCO3", "Diatomite": "Diatomite"}
GENERIC = {"mine", "mines", "north", "south", "east", "west", "central", "deposit", "prospect", "openpit", "pit", "shaft", "group", "find",
           "extended", "main", "upper", "lower", "alluvials", "hill", "creek", "well", "range", "mount", "australia", "austrlia", "anomaly",
           "spec", "loch", "nickel", "gold", "lady", "lake", "bore", "island", "bay", "beach", "rocks", "group", "workings"}
NOT_DEPOSIT = re.compile(r"borrow|hwy|highway|lot|heap leach|portal|stockpile|dump|plant|camp", re.I)


def words(name):
    t = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return {w for w in t.split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


def status(t, s):
    if s == "Operating": return "PRODUCER"
    if s == "Care and Maintenance": return "CARE_AND_MAINTENANCE"
    if s == "Under Development": return "DEVELOPMENT"
    if t == "Target": return "EXPLORATION"
    if s == "Proposed": return "FEASIBILITY" if t in ("Mine", "Deposit") else "PROSPECT"
    if t == "Mine": return "PAST_PRODUCER" if s == "Shut" else "UNKNOWN"
    if t in ("Deposit", "Prospect"): return "PROSPECT"
    if t in ("Occurrence", "Geological Observation"): return "OCCURRENCE"
    return "UNKNOWN"


# ------------------------------------------------------------------ read MINEDEX
rows = [f["attributes"] for p in sorted(glob.glob(f"{DL}/minedex_part_*.json")) for f in json.load(open(p, encoding="utf-8"))["features"]]
assert len(rows) == len({r["site_code"] for r in rows}), "duplicate site codes"
skipped = collections.Counter(r["site_type_"] for r in rows if r["site_type_"] not in LOAD_TYPES)
rows = [r for r in rows if r["site_type_"] in LOAD_TYPES]
log("MINEDEX sites loaded", len(rows), "| skipped by type", dict(skipped))
extract = datetime.datetime.fromtimestamp(rows[0]["extract_da"] / 1000, datetime.timezone.utc).date()
recs = []
for r in rows:
    toks = [t.strip() for t in (r["site_commo"] or "").split(",") if t.strip()]
    recs.append(dict(sid=r["site_code"], name=(r["site_title"] or r["short_name"] or r["site_code"]).strip(), lat=r["latitude"], lon=r["longitude"],
                     status=status(r["site_type_"], r["site_stage"]), is_deposit=r["site_type_"] in ("Mine", "Deposit"), toks=toks,
                     comments=note(("Source", "WA DEMIRS MINEDEX (CC BY 4.0)"), ("MINEDEX site", r["site_code"]), ("Site type", r["site_type_"]),
                                   ("Sub-type", r["site_sub_t"]), ("Stage", r["site_stage"]), ("Commodities (MINEDEX)", r["site_commo"]),
                                   ("Commodity group", r["target_com"]), ("Project", f"{r['proj_title']} ({r['proj_code']})" if r["proj_code"] else None),
                                   ("Short name", r["short_name"] if r["short_name"] != r["site_title"] else None), ("MINEDEX link", r["web_link"]),
                                   ("Extract date", str(extract)))))

# ------------------------------------------------------------------ gold
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = 'Australia'"); AUS = c.fetchone()[0]
c.execute("SELECT commodity_name, commodity_id, commodity_symbol FROM core.commodities")
COM = {}
for nm, cid, sym in c.fetchall():
    COM[nm.lower()] = cid
    if sym: COM[sym.lower()] = cid
unmapped = collections.Counter()


def cid_for(t):
    v = COM.get(CODES.get(t, t).lower())
    if v is None: unmapped[t] += 1
    return v


c.execute("""SELECT occurrence_id, name, lat, lon FROM core.occurrences WHERE is_active AND country_name = 'Australia' AND lat IS NOT NULL
             AND created_by = 'migration_mrds_20261014' AND lon < 129.1""")
ex = c.fetchall()
lat0 = np.radians(-26)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
tree = cKDTree(xy([e[2] for e in ex], [e[3] for e in ex]))
P = xy([r["lat"] for r in recs], [r["lon"] for r in recs])
cand = []
for i, r in enumerate(recs):
    for j in tree.query_ball_point(P[i], 1000):
        d = float(np.hypot(*(P[i] - tree.data[j])))
        if d <= 200 or ((words(r["name"]) & words(ex[j][1])) and not NOT_DEPOSIT.search(r["name"])):
            cand.append((d, i, j))
merge, used_i, used_j = [], set(), set()
for d, i, j in sorted(cand):            # closest pairs first, one-to-one
    if i in used_i or j in used_j: continue
    used_i.add(i); used_j.add(j); merge.append((i, ex[j][0], round(d), ex[j][1]))
log("WA-side MRDS records", len(ex), "| matched to MINEDEX (merge)", len(merge))

vals = [(r["name"][:250], r["is_deposit"], AUS, f"SRID=4326;POINT({r['lon']} {r['lat']})", r["status"], r["comments"], True, TAG) for r in recs]
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, comments, is_active, created_by, created_date)
                           VALUES %s RETURNING occurrence_id""", vals,
                     template="(%s,%s,%s,ST_GeomFromEWKT(%s),%s,%s,%s,%s,now())", fetch=True, page_size=2000)
newid = [x[0] for x in ids]
log("new occurrences", len(newid))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("OCCURRENCE", newid[i], SRC, r["sid"], TAG) for i, r in enumerate(recs)], page_size=5000)
links, seen = [], set()
for i, r in enumerate(recs):
    for k, t in enumerate(r["toks"]):
        v = cid_for(t)
        if v and (newid[i], v) not in seen:
            seen.add((newid[i], v)); links.append((newid[i], v, "PRIMARY" if k == 0 else "SECONDARY", True, TAG))
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links, page_size=5000)
log("commodity links", len(links), "| unmapped tokens", sum(unmapped.values()), unmapped.most_common(30))

REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
           ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
           ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id")]
logrows, rep = [], collections.Counter()
for i, old, d, oldname in merge:
    new = newid[i]
    for tbl, col in REPOINT:
        c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new, old))
        if c.rowcount: logrows.append(("repoint", tbl, old, new, c.rowcount, d)); rep[tbl] += c.rowcount
    c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (new, old))
    if c.rowcount: logrows.append(("repoint", "core.external_ids(USGS_MRDS)", old, new, c.rowcount, d)); rep["external_ids"] += c.rowcount
    c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (TAG, old))
    logrows.append(("deactivate", "core.occurrences", old, new, 1, d, oldname, recs[i]["name"]))
path = os.path.join(HERE, f"minedex_occ_merge_log_{STAMP}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["action", "table", "old_occurrence_id", "new_occurrence_id", "rows", "distance_m", "mrds_name", "minedex_name"]); w.writerows(logrows)
log("merge log", path, "| re-pointed", dict(rep))

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-08',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Department of Energy, Mines, Industry Regulation and Safety (DEMIRS), Western Australia",
           f"MINEDEX - Mines and mineral deposits (DMIRS-001), map-service extract {extract}",
           "Creative Commons Attribution 4.0 International (CC BY 4.0)", "https://creativecommons.org/licenses/by/4.0/",
           "Contains MINEDEX data, Department of Energy, Mines, Industry Regulation and Safety, State of Western Australia, licensed under CC BY 4.0.",
           "Cleared: CC BY 4.0 on the WA data catalogue record (API license_id cc-by, metadata modified 2026-11-07, checked 2026-11-08). Loaded 2026-11-08.",
           "Western Australia only. Infrastructure and environment sites not loaded. No resource tonnages in this extract (MINEDEX holds them per project; not loaded). "
           "Status mapped from MINEDEX site type and stage (originals in comments). Many mines are recorded as several sites (pits, shafts, workings).",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/WA_MINEDEX/EVIDENCE.md", TAG))

c.execute("SELECT status, count(*), count(*) FILTER (WHERE is_deposit) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,))
log("status (n, deposits)", c.fetchall())
c.execute("SELECT count(*) FILTER (WHERE array_length(commodities,1) > 0), count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)); log("with commodities / all", c.fetchone())
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND NOT ST_Intersects(geom, ST_MakeEnvelope(105, -36, 129.1, -10, 4326))", (TAG,))
log("outside WA box incl. Christmas Island and Timor Sea targets (must be 0)", c.fetchone()[0])
c.execute("SELECT count(*) FILTER (WHERE created_by = %s AND 'Li' = ANY(commodities)), count(*) FILTER (WHERE country_name = 'Australia') FROM core.occurrences WHERE is_active", (TAG,))
log("MINEDEX lithium sites / active Australian occurrences now", c.fetchone())
c.execute("""SELECT name, status, commodities FROM core.occurrences WHERE created_by = %s AND name IN
             ('Mt Cattlin - Dowling Openpit','Dalgaranga Tantalite Mine','Londonderry No 2','Cornwall Primary Pegmatite') ORDER BY name""", (TAG,))
log("spot check", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
