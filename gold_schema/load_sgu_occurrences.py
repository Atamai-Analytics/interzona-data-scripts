"""SGU Mineralresurser (Swedish mineral and bedrock occurrences, CC0 1.0) -> interzona_cm core.occurrences (+ commodities, external ids).

Source: Geological Survey of Sweden (SGU), Mineralresurser GeoPackage (mineralresurser.zip, SGU last-modified 2026-03-18, downloaded
2026-11-07 to D:/CriticalMineralsDB/Sweden/download_20261107/mineralresurser; evidence in Documents/Licence_Evidence/SGU_Sweden).
23,349 points + a 2,975-row reference list. The source has no tonnage or grade values (those columns are empty), so none are loaded.
Rules
  * status (econ_stat): mine/quarry -> PRODUCER (active: Kirunavaara, Aitik, Garpenberg ...); closed mine/quarry and historical mine/quarry
    -> PAST_PRODUCER; mine/quarry? -> UNKNOWN; significant prospect / prospect -> PROSPECT; mineralized outcrop / anomaly -> OCCURRENCE.
    is_deposit for producers, past producers, mine/quarry? and significant prospects.
  * deposit type: only where SGU's MIN4EU type plus commodity is unambiguous (skarn + Fe -> Skarn iron, sedimentHostedCopper, veinPolymetallic);
    otherwise NULL, with SGU's sub-type text kept in mineralization_style and the MIN4EU type in comments.
  * aggregate and dimension-stone sites are loaded (main_type kept in comments) so they can be filtered out.
  * position_accuracy: SGU coord_qlt 'better than 500m' -> AREA_CENTROID; finer precisions left NULL (precise).
  * duplicates of the old USGS MRDS Swedish records (within 200 m, or within 1 km sharing a name word) are MERGED as for Canada: references
    re-pointed to the SGU occurrence, the MRDS row deactivated, all logged to sgu_occ_merge_log_<timestamp>.csv. EU CRMA project rows are not
    matched (they are projects/plants, not SGU occurrences).
Usage: python load_sgu_occurrences.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import csv, os, re, sys, sqlite3, time, datetime, collections
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree
from pyproj import Transformer

DRY = "--dry" in sys.argv
TAG = "migration_sgu_occ_20261107"
SRC = "SWEDEN_SGU_MINERALRESURSER"
HERE = os.path.dirname(os.path.abspath(__file__))
GPKG = "D:/CriticalMineralsDB/Sweden/download_20261107/mineralresurser/extracted/mineralresurser.gpkg"
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def note(*pairs):
    return "; ".join(f"{k}: {v}" for k, v in pairs if v not in (None, "", "N/A"))


def toks(s):
    return [t.strip() for t in (s or "").split(";") if t.strip()]


STATUS = {"mine/quarry": ("PRODUCER", True), "closed mine/quarry": ("PAST_PRODUCER", True), "historical mine/quarry": ("PAST_PRODUCER", True),
          "mine/quarry?": ("UNKNOWN", True), "significant prospect": ("PROSPECT", True), "prospect": ("PROSPECT", False),
          "mineralized outcrop": ("OCCURRENCE", False), "anomaly": ("OCCURRENCE", False)}
NAMES = {"fe-sulphides": "Pyrite", "dimension stone": "Miscellaneous Dimension Stones", "primary aggregate": "Primary Aggregate",
         "kaolinite": "Kaolin", "barite": "Baryte", "quartz sand": "Silica Sand", "phosphorite": "Phosphate Rock", "alum shale": "Oil Shale",
         "nepheline": "Nepheline Syenite", "soapstone": "Talc", "oil": "Oil", "coal": "Coal", "clay mineral": "Clay"}
GENERIC = {"gruva", "gruvan", "gruvor", "fältet", "faltet", "norra", "södra", "sodra", "östra", "ostra", "västra", "vastra", "mine", "mines",
           "nya", "gamla", "stora", "lilla", "berget", "deposit", "field", "skarpning", "skärpning", "brott", "brottet"}


def words(name):
    t = re.sub(r"[^a-z0-9åäö ]", " ", (name or "").lower().replace("*", ""))
    return {w for w in t.split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


def otype(r):
    t, com = r["m4eu_deptp"] or "", toks(r["main_commo"])
    if t == "skarnAndCarbonateReplacement" and com[:1] == ["Fe"]: return "Skarn iron"
    if t == "sedimentHostedCopper": return "Sediment-hosted copper"
    if t == "veinPolymetallic": return "Vein polymetallic"
    return None


# ------------------------------------------------------------------ read SGU
src = sqlite3.connect(f"file:{GPKG}?mode=ro", uri=True); src.row_factory = sqlite3.Row
refs = {str(r["r_ref_id"]): r for r in src.execute("SELECT * FROM referenslista")}
rows = [dict(r) for r in src.execute("SELECT * FROM mineralresurser")]
log("SGU occurrences", len(rows), "| references", len(refs))
tr = Transformer.from_crs(3006, 4326, always_xy=True)
recs, nopos = [], 0
for r in rows:
    if r["e_sweref"] in (None, "") or r["n_sweref"] in (None, ""): nopos += 1; continue
    lon, lat = tr.transform(float(r["e_sweref"]), float(r["n_sweref"]))
    st, dep = STATUS.get(r["econ_stat"] or "", ("UNKNOWN", False))
    rids = toks(r["ref_id_pge"])
    reflist = [f"{refs[i]['r_author']} ({refs[i]['r_year']}) {refs[i]['r_title']}" for i in rids if i in refs][:6]
    name = (r["name"] or "").replace("*", "").strip() or f"SGU {r['id_code']}"
    recs.append(dict(sid=r["id_code"], name=name, lon=lon, lat=lat, status=st, is_deposit=dep, prim=toks(r["main_commo"]), sec=toks(r["othr_commo"]),
                     type_name=otype(r), style=(r["dep_sub_tx"] if r["dep_sub_tx"] not in (None, "", "Unspecified") else None),
                     form=(r["mode_o_occ"] or "").strip("; ") or None, alteration=(r["alteration"] or "").strip("; ") or None,
                     acc="AREA_CENTROID" if "500m" in (r["coord_qlt"] or "") else None,
                     comments=note(("Source", "Geological Survey of Sweden (SGU), Mineralresurser (CC0 1.0)"), ("SGU id", r["id_code"]),
                                   ("Status (SGU)", r["econ_stat"]), ("Main type (SGU)", r["main_type"]), ("Deposit type (SGU)", (r["type_o_dep"] or "").strip("; ")),
                                   ("MIN4EU type", r["m4eu_deptp"]), ("Ore field", r["ore_field"]), ("Alternative names", ", ".join(x for x in (r["alt_name"], r["alt_name2"]) if x)),
                                   ("County", r["county"]), ("Municipality", r["municipal"]), ("Host rock", (r["host_rock"] or "").strip("; ")),
                                   ("Ore minerals", (r["dep_min"] or "").strip("; ")), ("Other minerals", (r["other_min"] or "").strip("; ")),
                                   ("Wall rock", (r["wall_rock"] or "").strip("; ")), ("Age", r["age"]), ("Production start", r["prod_ini"]),
                                   ("Production end", r["prod_compl"]), ("Commodities (SGU)", "; ".join(toks(r["main_commo"]) + toks(r["othr_commo"]))),
                                   ("Coordinate precision", r["coord_qlt"]), ("Comments (SGU)", r["comments"]), ("References", " | ".join(reflist)),
                                   ("Record revised", r["date_o_rev"]))))
log("records without coordinates (skipped)", nopos)

# ------------------------------------------------------------------ gold
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = 'Sweden'"); SWE = c.fetchone()[0]
c.execute("SELECT commodity_name, commodity_id, commodity_symbol FROM core.commodities")
COM = {}
for nm, cid, sym in c.fetchall():
    COM[nm.lower()] = cid
    if sym: COM[sym.lower()] = cid
c.execute("SELECT type_name, occurrence_type_id FROM core.occurrence_types"); OTYPE = {k.lower(): v for k, v in c.fetchall()}
unmapped = collections.Counter()


def cid_for(t):
    v = COM.get(NAMES.get(t.lower(), t).lower())
    if v is None: unmapped[t] += 1
    return v


c.execute("SELECT occurrence_id, name, lat, lon FROM core.occurrences WHERE is_active AND country_name = 'Sweden' AND lat IS NOT NULL AND created_by = 'migration_mrds_20261014'")
ex = c.fetchall()
lat0 = np.radians(62)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
tree = cKDTree(xy([e[2] for e in ex], [e[3] for e in ex]))
P = xy([r["lat"] for r in recs], [r["lon"] for r in recs])
cand = []
for i, r in enumerate(recs):
    for j in tree.query_ball_point(P[i], 1000):
        d = float(np.hypot(*(P[i] - tree.data[j])))
        if d <= 200 or (words(r["name"]) & words(ex[j][1])):
            cand.append((d, i, j))
merge, used_i, used_j = [], set(), set()
for d, i, j in sorted(cand):            # closest pairs first, one-to-one
    if i in used_i or j in used_j: continue
    used_i.add(i); used_j.add(j); merge.append((i, ex[j][0], round(d)))
log("Swedish MRDS records", len(ex), "| matched to SGU (merge)", len(merge))

vals = [(r["name"][:250], r["is_deposit"], SWE, f"SRID=4326;POINT({r['lon']} {r['lat']})", r["status"], OTYPE.get((r["type_name"] or "").lower()),
         r["form"], r["style"], r["alteration"], r["comments"], True, TAG, r["acc"]) for r in recs]
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, occurrence_type_id, deposit_form,
                           mineralization_style, alteration, comments, is_active, created_by, created_date, position_accuracy)
                           VALUES %s RETURNING occurrence_id""", vals,
                     template="(%s,%s,%s,ST_GeomFromEWKT(%s),%s,%s,%s,%s,%s,%s,%s,%s,now(),%s)", fetch=True, page_size=2000)
newid = [x[0] for x in ids]
log("new occurrences", len(newid))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("OCCURRENCE", newid[i], SRC, r["sid"], TAG) for i, r in enumerate(recs)], page_size=5000)
links, seen = [], set()
for i, r in enumerate(recs):
    for role, ts in (("PRIMARY", r["prim"]), ("SECONDARY", r["sec"])):
        for t in ts:
            v = cid_for(t)
            if v and (newid[i], v) not in seen:
                seen.add((newid[i], v)); links.append((newid[i], v, role, True, TAG))
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links, page_size=5000)
log("commodity links", len(links), "| unmapped tokens", sum(unmapped.values()), unmapped.most_common(25))

REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
           ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
           ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id")]
logrows, rep = [], collections.Counter()
for i, old, d in merge:
    new = newid[i]
    for tbl, col in REPOINT:
        c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new, old))
        if c.rowcount: logrows.append(("repoint", tbl, old, new, c.rowcount, d)); rep[tbl] += c.rowcount
    c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (new, old))
    if c.rowcount: logrows.append(("repoint", "core.external_ids(USGS_MRDS)", old, new, c.rowcount, d)); rep["external_ids"] += c.rowcount
    c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (TAG, old))
    logrows.append(("deactivate", "core.occurrences", old, new, 1, d))
path = os.path.join(HERE, f"sgu_occ_merge_log_{STAMP}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["action", "table", "old_occurrence_id", "new_occurrence_id", "rows", "distance_m"]); w.writerows(logrows)
log("merge log", path, "| re-pointed", dict(rep))

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,false,%s,true,%s,%s,%s,'2026-11-07',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Geological Survey of Sweden (SGU)", "Mineralresurser (mineral and bedrock occurrences), GeoPackage, SGU last modified 2026-03-18",
           "CC0 1.0 Universal (public domain dedication)", "https://www.sgu.se/produkter-och-tjanster/geologiska-data/om-geologiska-data/licensvillkor/",
           "Source: Geological Survey of Sweden (SGU), Mineralresurser, CC0 1.0. Attribution is not required under CC0 and is given as a courtesy.",
           "Cleared: CC0 1.0 stated in the product description and SGU licence page (checked 2026-11-07). Loaded 2026-11-07.",
           "No tonnage or grade values in the source. Includes ~3,500 aggregate and dimension-stone sites (main type in comments). Locations within 10-500 m (precision in comments).",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/SGU_Sweden/EVIDENCE.md", TAG))

c.execute("SELECT status, count(*), count(*) FILTER (WHERE is_deposit), count(occurrence_type_id) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,))
log("status (n, deposits, typed)", c.fetchall())
c.execute("SELECT count(*) FILTER (WHERE array_length(commodities,1) > 0), count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)); log("with commodities / all", c.fetchone())
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND NOT ST_Intersects(geom, ST_MakeEnvelope(10.5, 55, 24.5, 69.2, 4326))", (TAG,))
log("outside Sweden box (must be 0)", c.fetchone()[0])
c.execute("SELECT count(*) FROM core.occurrences WHERE country_name = 'Sweden' AND is_active"); log("active Swedish occurrences now", c.fetchone()[0])
c.execute("SELECT name, status, commodities FROM core.occurrences WHERE created_by = %s AND name IN ('Kirunavaara','Aitik','Garpenbergsgruvan','Kristineberg','Björkdal')", (TAG,))
log("spot check", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
