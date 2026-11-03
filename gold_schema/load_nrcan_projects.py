"""Natural Resources Canada project lists (Open Government Licence - Canada) -> interzona_cm core.projects / project_ownership / occurrences.

  NRCAN_CRITICAL_MINERALS  'Critical minerals advanced projects, mines and processing facilities in Canada' (2025 edition, 292 properties)
  NRCAN_MAJOR_PROJECTS     'Major Projects Inventory' (2025-2035), MINING sector points only (127): planned / under-construction mines with
                           capital cost. A major project that matches a critical-minerals property (shared name word within 25 km) adds its
                           capital cost and construction status to that project instead of creating a second one (match: shared name word within 100 km,
                           because major-project points are municipality-level); a planned / under-construction match lifts an
                           advanced exploration project to DEVELOPMENT (asset MINE).
Projects
  * status: mines / producing sites and active processing -> PRODUCER, 'Past producer' -> PAST_PRODUCER, advanced (exploration) projects ->
    EXPLORATION, advanced processing projects and planned / under-construction major projects -> DEVELOPMENT; 'On hold / suspended' ->
    CARE_AND_MAINTENANCE for producing sites, otherwise kept and stated in the description.
  * asset_type: MINE, PROJECT (advanced exploration), REFINERY (smelter / refinery), RECYCLING, PROCESSING (other plants).
  * operator / owners -> core.project_ownership.owner_name (company_id only when the name equals an existing core.companies name).
  * site: linked to an active occurrence within 3 km sharing a name word (or within 500 m); otherwise a new occurrence is created at the
    NRCan point (major-project-only points are municipality-level: position_accuracy AREA_CENTROID, project location_precision TOWN).
Usage: python load_nrcan_projects.py [--dry] [--reload]
"""
import os, re, sys, glob, time, collections
import numpy as np
import psycopg2
import pyogrio
from scipy.spatial import cKDTree

DRY = "--dry" in sys.argv
TAG = "migration_nrcan_projects_20261103"
HERE = os.path.dirname(os.path.abspath(__file__))
CAN = "D:/CriticalMineralsDB/Canada"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


GENERIC = {"mine", "mines", "project", "projet", "lake", "lac", "deposit", "property", "expansion", "underground", "open", "pit", "gold", "copper",
           "nickel", "lithium", "graphite", "iron", "zinc", "uranium", "coal", "phase", "development", "plant", "mill", "site", "north", "south",
           "east", "west", "river", "mountain", "mount", "corp", "corporation", "limited", "inc", "ltd", "mining", "resources", "minerals", "metals",
           "the", "and", "creek", "hill", "hills", "valley", "island", "bay", "point", "lakes", "range", "operation", "operations", "facility", "refinery", "smelter", "tantale", "tantalum", "rare", "earth", "earths", "critical"}


def words(name):
    t = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().translate(str.maketrans("éèêëàâäîïôöùûüç", "eeeeaaaiioouuuc")))
    return {w for w in t.split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


COMMOD = {"rare earth elements": "REE", "rare earths": "REE", "platinum group metals": "PGE", "platinum group elements": "PGE", "pgm": "PGE", "pge": "PGE",
          "potash": "Potash", "graphite": "Graphite", "fluorspar": "Fluorite", "high-purity iron": "Fe", "iron ore": "Fe", "iron": "Fe", "aluminum": "Al",
          "aluminium": "Al", "copper": "Cu", "nickel": "Ni", "cobalt": "Co", "lithium": "Li", "uranium": "U", "zinc": "Zn", "lead": "Pb", "gold": "Au",
          "silver": "Ag", "molybdenum": "Mo", "tungsten": "W", "vanadium": "V", "titanium": "Ti", "niobium": "Nb", "tantalum": "Ta", "scandium": "Sc",
          "magnesium": "Mg", "manganese": "Mn", "tellurium": "Te", "bismuth": "Bi", "antimony": "Sb", "indium": "In", "gallium": "Ga", "germanium": "Ge",
          "cesium": "Cs", "caesium": "Cs", "chromium": "Cr", "zirconium": "Zr", "helium": None, "hydrogen": None, "palladium": "Pd", "platinum": "Pt",
          "phosphate": "Phosphate Rock", "silicon": "Si", "high-purity quartz": "Quartz", "silica": "SiO2", "tin": "Sn", "beryllium": "Be",
          "coal": "Coal", "selenium": "Se", "cadmium": "Cd", "iron": "Fe", "sulfur": "S", "sulphur": "S", "metallurgical coal": "Coal", "diamonds": "Diamond", "diamond": "Diamond", "salt": "Salt"}


def commodity_ids(text, COM):
    out = []
    for t in re.split(r",|;| and ", (text or "").lower()):
        t = t.strip().strip(".")
        if not t: continue
        key = COMMOD.get(t, t)
        v = COM.get(str(key).lower()) if key else None
        if v is None:   # 'lithium (spodumene)', 'lithium hydroxide', 'aluminum (pure or alloyed)', 'high-purity iron ore' -> the base element
            for cand in (t.split("(")[0].strip(), t.split(" ")[0], t.split(" ")[-1]):
                k2 = COMMOD.get(cand, cand)
                v = COM.get(str(k2).lower()) if k2 else None
                if v: break
        if v and v not in out: out.append(v)
    return out


cm = pyogrio.read_dataframe(glob.glob(f"{CAN}/NRCan_critical_minerals/*.gdb")[0])
mp = pyogrio.read_dataframe(glob.glob(f"{CAN}/NRCan_major_projects/*.gdb")[0], layer="major_projects_inventory_point")
mp = mp[mp["sector"] == "Mining"].copy()
mp["lon"] = mp.geometry.to_crs(4326).x; mp["lat"] = mp.geometry.to_crs(4326).y
log("NRCan critical-minerals properties", len(cm), "| major mining projects", len(mp))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
if "--reload" in sys.argv:   # remove this loader's rows first (projects, ownership, ids, sites it created) so it can run again
    c.execute("""UPDATE core.projects SET geom = CASE WHEN location_source LIKE 'NRCan%%' THEN NULL ELSE geom END,
                   location_precision = CASE WHEN location_source LIKE 'NRCan%%' THEN NULL ELSE location_precision END,
                   occurrence_id = CASE WHEN occurrence_id IN (SELECT occurrence_id FROM core.occurrences WHERE created_by = %s) THEN NULL ELSE occurrence_id END,
                   jurisdiction_id = CASE WHEN jurisdiction_id IN (SELECT jurisdiction_id FROM core.jurisdictions WHERE parent_jurisdiction_id =
                       (SELECT jurisdiction_id FROM core.jurisdictions WHERE name = 'Canada' AND level = 'COUNTRY'))
                       THEN (SELECT jurisdiction_id FROM core.jurisdictions WHERE name = 'Canada' AND level = 'COUNTRY') ELSE jurisdiction_id END,
                   location_source = CASE WHEN location_source LIKE 'NRCan%%' THEN NULL ELSE location_source END, modified_by = NULL, modified_date = NULL
                 WHERE modified_by = %s AND created_by <> %s""", (TAG, TAG, TAG))
    log("reload: un-enriched projects of other sources", c.rowcount)
    c.execute("UPDATE core.occurrences SET project_id = NULL WHERE project_id IN (SELECT project_id FROM core.projects WHERE created_by = %s)", (TAG,))
    for sql in ("DELETE FROM core.external_ids WHERE created_by = %s", "DELETE FROM core.project_ownership WHERE created_by = %s",
                "DELETE FROM core.projects WHERE created_by = %s", "DELETE FROM core.occurrence_commodities WHERE created_by = %s",
                "DELETE FROM core.occurrences WHERE created_by = %s", "DELETE FROM core.data_sources WHERE created_by = %s"):
        c.execute(sql, (TAG,)); log("reload:", sql.split(" WHERE")[0], c.rowcount)
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system IN ('NRCAN_CRITICAL_MINERALS','NRCAN_MAJOR_PROJECTS')")
assert c.fetchone()[0] == 0, "already loaded (use --reload)"
c.execute("SELECT commodity_name, commodity_id, commodity_symbol FROM core.commodities")
COM = {}
for n, i, s in c.fetchall():
    COM[n.lower()] = i
    if s: COM[s.lower()] = i
c.execute("SELECT j.name, j.jurisdiction_id FROM core.jurisdictions j JOIN core.jurisdictions p ON p.jurisdiction_id = j.parent_jurisdiction_id WHERE p.name = 'Canada'")
PROV = dict(c.fetchall()); PROV["Québec"] = PROV.get("Quebec")
c.execute("SELECT lower(name), company_id FROM core.companies"); COMPANY = dict(c.fetchall())

# major projects matched to critical-minerals properties
lat0 = np.radians(55)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
cmP = xy(cm["Latitude"], cm["Longitude"]); cmT = cKDTree(cmP)
mp_match = {}
NOT_SAME = {("Horne", "Horne 5")}   # Glencore's Horne smelter is not Falco's Horne 5 mine project (reviewed 2026-11-03)
for k, r in mp.iterrows():
    for j in cmT.query_ball_point(xy([r["lat"]], [r["lon"]])[0], 100000):   # major-project points are municipality-level
        if (cm.iloc[j]["PropertyNameEN"], r["project_name"]) in NOT_SAME: continue
        if words(r["project_name"]) & words(cm.iloc[j]["PropertyNameEN"]):
            mp_match.setdefault(j, []).append(k); break
matched_mp = {k for ks in mp_match.values() for k in ks}
log("major projects matched to a critical-minerals property", len(matched_mp))

projects = []   # name, lat, lon, province, status, asset, commodities_text, owners, desc, src, sid, precision
for j, r in cm.iterrows():
    grp, stage, act = r["OperationGroupEN"], r["DevelopmentStageEN"] or "", r["ActivityStatusEN"]
    onhold = act != "Active"
    if stage == "Past producer": status = "PAST_PRODUCER"
    elif grp == "Advanced exploration project": status = "EXPLORATION"
    elif grp == "Advanced processing project": status = "DEVELOPMENT"
    else: status = "CARE_AND_MAINTENANCE" if onhold else "PRODUCER"
    s = stage.lower()
    asset = ("PROJECT" if grp == "Advanced exploration project" else "RECYCLING" if "recycl" in s else
             "REFINERY" if ("smelter" in s or "refinery" in s) else "MINE" if grp.startswith("Mines") else "PROCESSING")
    extra = [mp.loc[k] for k in mp_match.get(j, [])]
    if extra and status == "EXPLORATION":   # a planned / under-construction major mining project: in development, not exploration
        status, asset = "DEVELOPMENT", "MINE"
    cap = "; ".join(f"Major Projects Inventory: {e['project_name']} ({e['company']}), {e['status'].lower()}, capital cost C${e['capital_cost']} million" for e in extra)
    desc = "; ".join(x for x in [f"NRCan critical minerals list 2025: {grp}", f"stage: {stage}", f"activity: {act}", f"commodities: {r['CommoditiesEN']}",
                                 f"operator/owners: {r['OperatorOwnersEN']}", cap, f"website: {r['Website']}" if r["Website"] not in (None, "", "N/A") else "",
                                 f"impact assessment: {r['CIAR']}" if r["CIAR"] not in (None, "", "N/A") else ""] if x)
    projects.append(dict(name=r["PropertyNameEN"], lat=float(r["Latitude"]), lon=float(r["Longitude"]), province=r["ProvincesEN"], status=status,
                         asset=asset, comm=r["CommoditiesEN"], owners=r["OperatorOwnersEN"], desc=desc, src="NRCAN_CRITICAL_MINERALS",
                         sid=str(r["ID"]), extra_ids=[("NRCAN_MAJOR_PROJECTS", str(e["id"])) for e in extra], precision="SITE", onhold=onhold,
                         deposit=grp in ("Advanced exploration project", "Mines and other primary producing sites")))
for k, r in mp.iterrows():
    if k in matched_mp: continue
    desc = f"NRCan Major Projects Inventory (mining): {r['status']}; capital cost C${r['capital_cost']} million; location: {r['location']}; company: {r['company']}"
    nm = r["project_name"].lower()
    asset = "REFINERY" if re.search(r"refiner|smelter", nm) else "PROCESSING" if re.search(r"plant|facility|processing|upgrade|usine", nm) else "MINE"
    projects.append(dict(name=r["project_name"], lat=float(r["lat"]), lon=float(r["lon"]), province=r["province"], status="DEVELOPMENT", asset=asset,
                         comm=None, owners=r["company"], desc=desc, src="NRCAN_MAJOR_PROJECTS", sid=str(r["id"]), extra_ids=[], precision="TOWN",
                         onhold=False, deposit=True))
log("projects to load", len(projects))

# sites: link to existing active occurrences or create
c.execute("SELECT occurrence_id, name, lat, lon, project_id FROM core.occurrences WHERE is_active AND country_name = 'Canada' AND lat IS NOT NULL")
ex = c.fetchall(); exT = cKDTree(xy([e[2] for e in ex], [e[3] for e in ex]))
linked, created = 0, 0
for p in projects:
    P = xy([p["lat"]], [p["lon"]])[0]; best = None
    for j in exT.query_ball_point(P, 3000):
        d = float(np.hypot(*(P - exT.data[j])))
        if d <= 500 or (words(p["name"]) & words(ex[j][1])):
            score = (0 if words(p["name"]) & words(ex[j][1]) else 1, d)
            if best is None or score < best[0]: best = (score, j)
    if best:
        p["occ"] = ex[best[1]][0]; linked += 1
    else:
        c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, position_accuracy, comments, is_active, created_by, created_date)
                     VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,true,%s,now()) RETURNING occurrence_id""",
                  (p["name"][:250], p["deposit"], PROV.get(p["province"]), p["lon"], p["lat"], p["status"],
                   "AREA_CENTROID" if p["precision"] == "TOWN" else None, "Site created from " + p["desc"], TAG))
        p["occ"] = c.fetchone()[0]; created += 1
        for cid in commodity_ids(p["comm"], COM):
            c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'PRIMARY',true,%s)", (p["occ"], cid, TAG))
log("sites linked to existing occurrences", linked, "| new sites", created)

# projects already in gold from other sources (company reports, SDSG ...) -> attach the NRCan id and fill only their EMPTY fields (position, site,
# province); no duplicate. Match: same company (owner name = an existing company) and a shared name word, or within 15 km and a shared name word.
c.execute("""SELECT p.project_id, p.name, ST_Y(p.geom), ST_X(p.geom), p.company_id FROM core.projects p WHERE p.is_active AND p.created_by <> %s
             AND (p.geom IS NULL OR ST_Intersects(p.geom, ST_MakeEnvelope(-142, 40, -50, 84, 4326)))""", (TAG,))
old_p = c.fetchall()
geo_p = [x for x in old_p if x[2] is not None]
oldT = cKDTree(xy([x[2] for x in geo_p], [x[3] for x in geo_p])) if geo_p else None
attached = []
unmapped = collections.Counter()
for p in projects:
    P = xy([p["lat"]], [p["lon"]])[0]
    owner_ids = {COMPANY.get(o.strip().lower()) for o in re.split(r";|\s/\s", p["owners"] or "")} - {None}
    own_words = set().union(*[words(o) for o in re.split(r";|\s/\s", p["owners"] or "")]) | {"tinto", "rio"}   # company names are not site names
    cand = [x for x in old_p if x[4] in owner_ids and (words(p["name"]) - own_words) & (words(x[1]) - own_words)]
    if not cand and oldT is not None:
        cand = [geo_p[j] for j in oldT.query_ball_point(P, 15000) if words(p["name"]) & words(geo_p[j][1])]
    if cand:
        pid = cand[0][0]
        for src, sid in [(p["src"], p["sid"])] + p["extra_ids"]:
            c.execute("INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES ('PROJECT',%s,%s,%s,%s)", (pid, src, sid, TAG))
        c.execute("""UPDATE core.projects SET geom = coalesce(geom, ST_SetSRID(ST_MakePoint(%s,%s),4326)),
                       location_precision = coalesce(location_precision, %s), location_source = coalesce(location_source, %s),
                       occurrence_id = coalesce(occurrence_id, %s),
                       jurisdiction_id = CASE WHEN jurisdiction_id = (SELECT jurisdiction_id FROM core.jurisdictions WHERE name = 'Canada' AND level = 'COUNTRY')
                                              OR jurisdiction_id IS NULL THEN %s ELSE jurisdiction_id END,
                       modified_by = %s, modified_date = now() WHERE project_id = %s""",
                  (p["lon"], p["lat"], p["precision"], "NRCan critical minerals list 2025 (site coordinates)" if p["precision"] == "SITE"
                   else "NRCan Major Projects Inventory (municipality-level point)", p["occ"], PROV.get(p["province"]), TAG, pid))
        attached.append((p["name"], pid)); continue
    cids = commodity_ids(p["comm"], COM)
    for t in re.split(r",|;| and ", (p["comm"] or "").lower()):
        t = t.strip().strip(".")
        if t and not (COMMOD.get(t, t) and COM.get(str(COMMOD.get(t, t)).lower())): unmapped[t] += 1
    c.execute("""INSERT INTO core.projects (company_id, name, jurisdiction_id, status, primary_commodity_id, geom, description, is_active, created_by, created_date,
                 occurrence_id, asset_type, location_precision, location_source)
                 VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,true,%s,now(),%s,%s,%s,%s) RETURNING project_id""",
              (COMPANY.get((p["owners"] or "").lower()), p["name"][:250], PROV.get(p["province"]), p["status"], cids[0] if cids else None, p["lon"], p["lat"],
               p["desc"], TAG, p["occ"], p["asset"], p["precision"],
               "NRCan critical minerals list 2025 (site coordinates)" if p["precision"] == "SITE" else "NRCan Major Projects Inventory (municipality-level point)"))
    pid = c.fetchone()[0]
    c.execute("UPDATE core.occurrences SET project_id = %s WHERE occurrence_id = %s AND project_id IS NULL", (pid, p["occ"]))
    for o in [x.strip() for x in re.split(r";|\s/\s", p["owners"] or "") if x.strip()]:
        c.execute("""INSERT INTO core.project_ownership (project_id, company_id, owner_name, as_of_year, is_active, created_by, created_date)
                     VALUES (%s,%s,%s,2025,true,%s,now())""", (pid, COMPANY.get(o.lower()), o[:250], TAG))
    for src, sid in [(p["src"], p["sid"])] + p["extra_ids"]:
        c.execute("INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES ('PROJECT',%s,%s,%s,%s)", (pid, src, sid, TAG))
log("unmapped commodity words", unmapped.most_common(12))
log("already in gold from another source (NRCan id attached, no new project)", len(attached), attached[:20])

for src, ds, lic_url in [("NRCAN_CRITICAL_MINERALS", "Critical minerals advanced projects, mines and processing facilities in Canada (2025 edition, modified 2026-02-23)",
                          "https://open.canada.ca/data/en/dataset/22b2db8a-dc12-47f2-9737-99d3da921751"),
                         ("NRCAN_MAJOR_PROJECTS", "Major Projects Inventory 2025-2035 (mining sector), modified 2026-01-01",
                          "https://open.canada.ca/data/en/dataset/f5f2db55-31e4-42fb-8c73-23e1c44de9b2")]:
    c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
                 licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
                 VALUES (%s,'Natural Resources Canada',%s,'Open Government Licence - Canada','https://open.canada.ca/en/open-government-licence-canada',true,%s,true,%s,%s,
                 'D:/CriticalMineralsDB/Documents/Licence_Evidence/CANADA_NRCAN/','2026-11-03',true,%s,now()) ON CONFLICT DO NOTHING""",
              (src, ds, f"Contains information licensed under the Open Government Licence - Canada. Source: Natural Resources Canada, {ds} ({lic_url}).",
               "Cleared: Open Government Licence - Canada on the open.canada.ca record (checked 2026-11-03). Loaded 2026-11-03.",
               "Compiled annually by NRCan with the provinces and territories from public company information; statuses as at the edition date.", TAG))

c.execute("SELECT status, asset_type, count(*) FROM core.projects WHERE created_by = %s GROUP BY 1,2 ORDER BY 3 DESC", (TAG,)); log("projects", c.fetchall())
c.execute("SELECT count(*), count(primary_commodity_id), count(company_id), count(occurrence_id) FROM core.projects WHERE created_by = %s", (TAG,))
log("projects (n, with commodity, with company id, with site)", c.fetchone())
c.execute("""SELECT j.name, count(*) FROM core.projects p JOIN core.jurisdictions j USING (jurisdiction_id) WHERE p.created_by = %s GROUP BY 1 ORDER BY 2 DESC""", (TAG,))
log("by province", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
