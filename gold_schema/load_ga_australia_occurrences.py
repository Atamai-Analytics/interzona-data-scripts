"""Geoscience Australia OZMIN deposits + state/territory mineral occurrences (CC BY 4.0) -> interzona_cm core.occurrences.

Source: GA web service https://services.ga.gov.au/gis/earthresource/wfs (AccessConstraints: CC BY 4.0), downloaded 2026-11-08 in the browser
pane to D:/CriticalMineralsDB/Australia/download_20261108 (ga_ozmin_mineral_deposits_20261108.csv 4,371; ga_state_mineral_occurrences_20261108.csv
193,651). Evidence: Documents/Licence_Evidence/GA_OZMIN/EVIDENCE.md. Western Australia comes from MINEDEX (load_minedex_occurrences.py, loaded first).
Order and rules
  1. OZMIN deposits (source AUSTRALIA_GA_OZMIN): outside WA all loaded. In WA, a deposit matching a MINEDEX occurrence (<= 300 m, or <= 2 km sharing a
     name word) is NOT loaded again: the OZMIN ENO is added as an external id of the MINEDEX occurrence and the OZMIN status / deposit model /
     companies are appended to its comments. Unmatched WA OZMIN deposits are loaded. All OZMIN rows are deposits (is_deposit).
     status: operating mine -> PRODUCER; historic mine / closed -> PAST_PRODUCER; care and maintenance -> CARE_AND_MAINTENANCE; under development ->
     DEVELOPMENT; scoping / (pre-, definitive, bankable) feasibility -> FEASIBILITY; mineral deposit -> PROSPECT.
  2. State/territory occurrences (source AUSTRALIA_GA_STATE_OCCURRENCES): WA rows skipped (they are the MINEDEX sites). Rows within 200 m of an OZMIN
     deposit (or 1 km sharing a name word) are skipped as duplicates (their id is kept as an external id of the OZMIN occurrence). status from CLASS
     text: abandoned/historic -> PAST_PRODUCER; operating -> PRODUCER; care and maintenance -> CARE_AND_MAINTENANCE; feasibility -> FEASIBILITY;
     mine/pit/quarry/diggings/workings/production -> UNKNOWN (deposit); deposit/resource area/field -> PROSPECT (deposit); prospect -> PROSPECT;
     occurrence/anomaly -> OCCURRENCE; empty/other -> UNKNOWN. Original class, source, state id and accuracy kept in comments.
  3. position_accuracy = AREA_CENTROID when GA's ACCURACY_M >= 1000 (metres kept in comments).
  4. Old USGS MRDS records outside WA (WA ones were merged by the MINEDEX loader) that match a new record (<= 200 m, or <= 1 km sharing a name word)
     are MERGED: references re-pointed, MRDS row deactivated, logged to ga_occ_merge_log_<timestamp>.csv.
Usage: python load_ga_australia_occurrences.py [--dry]
"""
import csv, os, re, sys, time, datetime, collections
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree

DRY = "--dry" in sys.argv
TAG = "migration_ga_aus_occ_20261108"
SRC_DEP, SRC_OCC = "AUSTRALIA_GA_OZMIN", "AUSTRALIA_GA_STATE_OCCURRENCES"
HERE = os.path.dirname(os.path.abspath(__file__))
DL = "D:/CriticalMineralsDB/Australia/download_20261108"
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
sys.path.insert(0, HERE)
CODES = {}
exec(re.search(r"^CODES = \{.*?\}\n", open(os.path.join(HERE, "load_minedex_occurrences.py"), encoding="utf-8").read(), re.S | re.M).group(0))
CODES.update({"Coal": "Coal", "BCoal": "Black Coal", "BrCoal": "Brown Coal", "Mns": "Mineral Sand", "Mgs": "MgCO3", "Mgst": "MgCO3", "Brt": "Baryte",
              "PGE": "PGE", "REE": "REE", "REO": "Rare Earth Oxide", "U3O8": "U", "WO3": "WO3", "V2O5": "V2O5", "P2O5": "Phosphate Rock", "Ta2O5": "Ta2O5",
              "SnO2": "SnO2", "TiO2": "TiO2", "MnOre": "Manganese Ore", "FeOre": "Fe", "Al2O3": "Alumina", "MgO": "Magnesia", "K2SO4": "K2SO4",
              "Opal": "Opal", "Jade": "Jade", "Sap": "Sapphire", "Agg": "Primary Aggregate", "Grvl": "Sand and Gravel", "Snd": "Sand and Gravel",
              "Dimst": "Miscellaneous Dimension Stones", "Slt": "Slate", "Peat": "Peat", "Zeo": "Zeolite", "Perl": "Perlite", "Wol": "Wollastonite",
              "Ochr": "Ochre", "OilSh": "Oil Shale", "Salt": "Salt", "Cel": "Strontianite",
              "Opl": "Opal", "Cy": "Clay", "Cybk": "Brick Clay", "Cywf": "White Firing Clay", "Cbl": "Black Coal", "Cbr": "Brown Coal",
              "Spr": "Sapphirine", "Cors": "Sapphire", "Sic": "SiO2", "Dmdg": "Diamond Gemstone", "Sl": "Slate", "NaCl": "Salt",
              "Sto": "Miscellaneous Dimension Stones", "Zeol": "Zeolite", "Sigs": "Silica Gemstone", "Osh": "Oil Shale", "Wo": "Wollastonite",
              "Och": "Ochre", "Zrngs": "Zircon Gemstone", "Qtza": "Amethyst", "FeCr2O4": "Chromite", "Feox": "Iron Oxide", "Prl": "Pyrophyllite",
              "Nsy": "Nepheline Syenite", "Aggr": "Primary Aggregate", "Rdn": "Rhodonite", "Eps": "Epsomite", "Aga": "Agate"})


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def note(*pairs):
    return "; ".join(f"{k}: {v}" for k, v in pairs if v not in (None, "", "N/A"))


GENERIC = {"mine", "mines", "north", "south", "east", "west", "central", "deposit", "prospect", "openpit", "pit", "shaft", "group", "find",
           "extended", "main", "upper", "lower", "alluvials", "hill", "creek", "well", "range", "mount", "australia", "anomaly", "spec", "loch",
           "nickel", "gold", "lady", "lake", "bore", "island", "bay", "beach", "rocks", "workings", "quarry", "project", "copper", "tin", "lead",
           "silver", "zinc", "iron", "coal", "reef", "lode", "gully", "flat", "river", "station", "road", "area", "field", "claim", "lease", "unnamed"}


def words(name):
    t = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return {w for w in t.split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


def toks(codes):
    return [t.strip().strip("()") for t in (codes or "").split(",") if t.strip().strip("()")]


def is_wa(state, lon):
    return state == "WA" or (state == "" and lon < 129.0)


DEP_STATUS = {"operating mine": "PRODUCER", "historic mine": "PAST_PRODUCER", "closed": "PAST_PRODUCER", "care and maintenance": "CARE_AND_MAINTENANCE",
              "under development": "DEVELOPMENT", "scoping": "FEASIBILITY", "pre-feasibility": "FEASIBILITY", "feasibility": "FEASIBILITY",
              "definitive feasibility": "FEASIBILITY", "bankable feasibility": "FEASIBILITY", "mineral deposit": "PROSPECT"}


def occ_status(cls):
    c = (cls or "").lower()
    if re.search(r"abandon|historic|disused", c): return "PAST_PRODUCER", True
    if "operating" in c: return "PRODUCER", True
    if "care and maint" in c: return "CARE_AND_MAINTENANCE", True
    if "feasib" in c: return "FEASIBILITY", True
    if re.search(r"\bmine\b|\bpit\b|quarry|digging|workings|production|placer mine|open cut", c): return "UNKNOWN", True
    if re.search(r"deposit|resource area|\bfield\b", c): return "PROSPECT", True
    if "prospect" in c: return "PROSPECT", False
    if re.search(r"occurrence|anomaly", c): return "OCCURRENCE", False
    return "UNKNOWN", False


lat0 = np.radians(-28)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])


def norm(n):
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def match(new_names, new_lat, new_lon, old_names, old_lat, old_lon, near, far, same_name_far=5000, one_to_one=True):
    """one-to-one closest pairs: (i_new, j_old, metres) within `near` m, within `far` m sharing a name word, or within
    `same_name_far` m with the identical normalised name (large deposits are often placed several km apart by different sources)"""
    if not old_names or not new_names: return []
    tree = cKDTree(xy(old_lat, old_lon)); P = xy(new_lat, new_lon); cand = []
    for i in range(len(new_names)):
        wi = words(new_names[i])
        ni = norm(new_names[i])
        for j in tree.query_ball_point(P[i], max(far, same_name_far)):
            d = float(np.hypot(*(P[i] - tree.data[j])))
            if d <= near or (d <= far and (wi & words(old_names[j]))) or (len(ni) >= 4 and ni == norm(old_names[j])): cand.append((d, i, j))
    out, ui, uj = [], set(), set()
    for d, i, j in sorted(cand):
        if i in ui or (one_to_one and j in uj): continue
        ui.add(i); uj.add(j); out.append((i, j, round(d)))
    return out


# ------------------------------------------------------------------ read
dep = list(csv.DictReader(open(f"{DL}/ga_ozmin_mineral_deposits_20261108.csv", encoding="utf-8")))
occ = list(csv.DictReader(open(f"{DL}/ga_state_mineral_occurrences_20261108.csv", encoding="utf-8")))
for r in dep + occ:
    r["lat"], r["lon"] = float(r["LAT_GDA94"]), float(r["LONG_GDA94"])
log("OZMIN deposits", len(dep), "| state occurrences", len(occ))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system IN (%s, %s)", (SRC_DEP, SRC_OCC))
assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system = 'AUSTRALIA_WA_MINEDEX'")
assert c.fetchone()[0] > 40000, "load MINEDEX first"
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


# ------------------------------------------------------------------ 1. OZMIN vs MINEDEX (WA)
c.execute("""SELECT o.occurrence_id, o.name, o.lat, o.lon FROM core.occurrences o JOIN core.external_ids e ON e.entity_type = 'OCCURRENCE'
             AND e.entity_id = o.occurrence_id AND e.source_system = 'AUSTRALIA_WA_MINEDEX' WHERE o.is_active""")
mdx = c.fetchall()
wa_dep = [r for r in dep if is_wa(r["STATE"], r["lon"])]
m = match([r["DEPOSIT_NAME"] for r in wa_dep], [r["lat"] for r in wa_dep], [r["lon"] for r in wa_dep],
          [x[1] for x in mdx], [x[2] for x in mdx], [x[3] for x in mdx], 300, 2000)
enrich = [(wa_dep[i], mdx[j][0], d) for i, j, d in m]
enriched_eno = {r["ENO"] for r, _, _ in enrich}
dep_load = [r for r in dep if r["ENO"] not in enriched_eno]
log("WA OZMIN deposits", len(wa_dep), "| matched to MINEDEX (enrich, not loaded)", len(enrich), "| OZMIN deposits to load", len(dep_load))

# ------------------------------------------------------------------ 2. state occurrences (non-WA) vs OZMIN
occ_nw = [r for r in occ if not is_wa(r["STATE"], r["lon"])]
m2 = match([r["OCCURRENCE_NAME"] for r in occ_nw], [r["lat"] for r in occ_nw], [r["lon"] for r in occ_nw],
           [r["DEPOSIT_NAME"] for r in dep_load], [r["lat"] for r in dep_load], [r["lon"] for r in dep_load], 200, 1000, one_to_one=False)
dup_of = {i: j for i, j, d in m2}
occ_load = [r for k, r in enumerate(occ_nw) if k not in dup_of]
log("non-WA state occurrences", len(occ_nw), "| duplicates of OZMIN (skipped)", len(dup_of), "| to load", len(occ_load))


def rec_dep(r):
    st = DEP_STATUS.get(r["OPERATING_STATUS"], "UNKNOWN")
    acc = float(r["ACCURACY_M"] or 0)
    return dict(sid=r["ENO"], src=SRC_DEP, name=r["DEPOSIT_NAME"].strip() or f"OZMIN {r['ENO']}", lat=r["lat"], lon=r["lon"], status=st, is_deposit=True,
                toks=toks(r["COMMODITY_CODES"]), acc="AREA_CENTROID" if acc >= 1000 else None,
                comments=note(("Source", "Geoscience Australia OZMIN (CC BY 4.0)"), ("OZMIN ENO", r["ENO"]), ("State", r["STATE"]),
                              ("Status (OZMIN)", r["OPERATING_STATUS"]), ("Commodities (OZMIN)", r["COMMODITY_NAMES"]), ("Synonyms", r["SYNONYMS"]),
                              ("Companies", r["COMPANIES"]), ("Province", r["PROVINCES"]), ("Geologic age", r["GEOLOGIC_AGE"]),
                              ("Deposit model", r["DEPOSIT_MODEL"]), ("Location accuracy (m)", r["ACCURACY_M"]), ("Location", r["DEPOSIT_LOCATION"])))


def rec_occ(r):
    st, isdep = occ_status(r["CLASS"])
    acc = float(r["ACCURACY_M"] or 0)
    return dict(sid=r["ENO"], src=SRC_OCC, name=(r["OCCURRENCE_NAME"] or "").strip() or f"{r['STATE']} occurrence {r['OTHER_ID'] or r['ENO']}",
                lat=r["lat"], lon=r["lon"], status=st, is_deposit=isdep, toks=toks(r["COMMODITY_CODES"]), acc="AREA_CENTROID" if acc >= 1000 else None,
                comments=note(("Source", f"{r['STATE']} geological survey mineral occurrences, compiled by Geoscience Australia (CC BY 4.0)"),
                              ("GA ENO", r["ENO"]), ("State id", r["OTHER_ID"]), ("State", r["STATE"]), ("Class", (r["CLASS"] or "").strip()),
                              ("Project", r["PROJECT"]), ("Commodities (source)", r["COMMODITY_NAMES"]), ("Location accuracy (m)", r["ACCURACY_M"]),
                              ("Source reference", (r["SOURCE"] or "").strip()[:300]), ("Location", r["OCCURRENCE_LOCATION"])))


recs = [rec_dep(r) for r in dep_load] + [rec_occ(r) for r in occ_load]
vals = [(r["name"][:250], r["is_deposit"], AUS, f"SRID=4326;POINT({r['lon']} {r['lat']})", r["status"], r["comments"], True, TAG, r["acc"]) for r in recs]
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, comments, is_active, created_by, created_date, position_accuracy)
                           VALUES %s RETURNING occurrence_id""", vals,
                     template="(%s,%s,%s,ST_GeomFromEWKT(%s),%s,%s,%s,%s,now(),%s)", fetch=True, page_size=2000)
newid = [x[0] for x in ids]
log("new occurrences", len(newid))
ext = [("OCCURRENCE", newid[i], r["src"], r["sid"], TAG) for i, r in enumerate(recs)]
ext += [("OCCURRENCE", oid, SRC_DEP, r["ENO"], TAG) for r, oid, d in enrich]
ozmin_id = {r["ENO"]: newid[k] for k, r in enumerate(dep_load)}
ext += [("OCCURRENCE", ozmin_id[dep_load[j]["ENO"]], SRC_OCC, occ_nw[i]["ENO"], TAG) for i, j in dup_of.items()]
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s", ext, page_size=5000)
log("external ids", len(ext))
links, seen = [], set()
for i, r in enumerate(recs):
    for k, t in enumerate(r["toks"]):
        v = cid_for(t)
        if v and (newid[i], v) not in seen:
            seen.add((newid[i], v)); links.append((newid[i], v, "PRIMARY" if k == 0 else "SECONDARY", True, TAG))
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links, page_size=5000)
log("commodity links", len(links), "| unmapped tokens", sum(unmapped.values()), unmapped.most_common(40))
for r, oid, d in enrich:
    c.execute("UPDATE core.occurrences SET comments = concat_ws('; ', comments, %s), modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
              (note(("OZMIN", f"ENO {r['ENO']} ({r['DEPOSIT_NAME']}, {d} m)"), ("OZMIN status", r["OPERATING_STATUS"]), ("OZMIN deposit model", r["DEPOSIT_MODEL"]),
                     ("OZMIN companies", r["COMPANIES"]), ("OZMIN province", r["PROVINCES"])), TAG, oid))

# ------------------------------------------------------------------ 4. MRDS merge outside WA
c.execute("""SELECT occurrence_id, name, lat, lon FROM core.occurrences WHERE is_active AND country_name = 'Australia' AND lat IS NOT NULL
             AND created_by = 'migration_mrds_20261014' AND lon >= 129.1""")
ex = c.fetchall()
m3 = match([ex_[1] for ex_ in ex], [ex_[2] for ex_ in ex], [ex_[3] for ex_ in ex], [r["name"] for r in recs], [r["lat"] for r in recs], [r["lon"] for r in recs], 200, 1000)
REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
           ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
           ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id")]
logrows, rep = [], collections.Counter()
NO_MERGE = {("Goonumbla Northparkes", "Goonumbla-Alectown Limestone Deposits")}   # reviewed 2026-11-08: Cu-Au deposit vs limestone, not the same
m3 = [(i, j, d) for i, j, d in m3 if (ex[i][1], recs[j]["name"]) not in NO_MERGE]
for i, j, d in m3:
    old, new = ex[i][0], newid[j]
    for tbl, col in REPOINT:
        c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new, old))
        if c.rowcount: logrows.append(("repoint", tbl, old, new, c.rowcount, d, "", "")); rep[tbl] += c.rowcount
    c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (new, old))
    if c.rowcount: logrows.append(("repoint", "core.external_ids(USGS_MRDS)", old, new, c.rowcount, d, "", "")); rep["external_ids"] += c.rowcount
    c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (TAG, old))
    logrows.append(("deactivate", "core.occurrences", old, new, 1, d, ex[i][1], recs[j]["name"]))
path = os.path.join(HERE, f"ga_occ_merge_log_{STAMP}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["action", "table", "old_occurrence_id", "new_occurrence_id", "rows", "distance_m", "mrds_name", "new_name"]); w.writerows(logrows)
log("non-WA MRDS records", len(ex), "| merged", len(m3), "| merge log", path, "| re-pointed", dict(rep))

for src, name, caveat in ((SRC_DEP, "OZMIN mineral deposits (WFS ama:MineralDeposits), downloaded 2026-11-08",
                           "About 1,000+ major and historically significant deposits per GA plus later additions (4,371 rows). WA deposits that match a MINEDEX site are "
                           "attached to it (external id + comments) rather than loaded twice. Resource figures are in a separate layer (not loaded yet)."),
                          (SRC_OCC, "State and territory mineral occurrences compiled by GA (WFS ama:MineralOccurrences), downloaded 2026-11-08",
                           "Non-WA rows only (WA comes from MINEDEX). Location accuracy varies (1 m to 5 km; >= 1 km flagged AREA_CENTROID). Status derived from each "
                           "state's class wording (kept in comments). Rows duplicating an OZMIN deposit are attached to it, not loaded.")):
    c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
                 licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
                 VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-08',true,%s,now()) ON CONFLICT DO NOTHING""",
              (src, "Geoscience Australia (Commonwealth of Australia)", name, "Creative Commons Attribution 4.0 International (CC BY 4.0)",
               "https://creativecommons.org/licenses/by/4.0/",
               "Contains Geoscience Australia OZMIN and state and territory mineral occurrence data, Commonwealth of Australia (Geoscience Australia), licensed under CC BY 4.0.",
               "Cleared: CC BY 4.0 stated in the GA WFS AccessConstraints (checked 2026-11-08). Loaded 2026-11-08.", caveat,
               "D:/CriticalMineralsDB/Documents/Licence_Evidence/GA_OZMIN/EVIDENCE.md", TAG))

c.execute("SELECT status, count(*), count(*) FILTER (WHERE is_deposit) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,))
log("status (n, deposits)", c.fetchall())
c.execute("SELECT count(*) FILTER (WHERE array_length(commodities,1) > 0), count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)); log("with commodities / all", c.fetchone())
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND NOT ST_Intersects(geom, ST_MakeEnvelope(96, -45, 168, -9, 4326))", (TAG,))
log("outside Australia box (must be 0)", c.fetchone()[0])
c.execute("SELECT count(*) FROM core.occurrences WHERE is_active AND country_name = 'Australia'"); log("active Australian occurrences now", c.fetchone()[0])
c.execute("""SELECT name, status, commodities FROM core.occurrences WHERE created_by = %s AND name IN
             ('Olympic Dam','Broken Hill','Mount Isa','Cadia Hill','Ranger','McArthur River','Finniss','Mount Morgan') ORDER BY name""", (TAG,))
log("spot check", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
