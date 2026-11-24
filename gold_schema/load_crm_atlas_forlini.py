"""Critical Raw Materials Atlas (Vincenzo Forlini, MIT licence) -> 20 European CRM facilities missing from interzona_cm (new occurrences +
facility rows without capacity + operator), source_system CRM_ATLAS_FORLINI. User OK 2026-11-23 ("Yes, add them").

Input: D:/CriticalMineralsDB/Europe/CRM_Atlas_Forlini_20261123/{facilities,cities,companies}.csv (downloaded 2026-11-23 with approval from
github.com/vincenzo-forlini/Critical-Raw-Materials-Atlas, data/; LICENSE.txt = MIT (c) 2026 Vincenzo Forlini). The comparison
atlas_vs_interzona_20261123.csv matched 148 of the 169 Atlas sites to existing records (by name, company or a differently named record nearby);
the 20 below are the genuine gaps (checked by name search). Cornish Lithium (= USGS 'Direct Lithium Extraction Plant') and HyProMag Pforzheim
(= CRMA 'HyProMag GmbH') are already present and are not added.
Positions: the Atlas places sites at the city point (cities.csv) -> position_accuracy TOWN_CENTROID. The author calls the data a 'seed dataset'
compiled from public knowledge and 'not a citable source': each row keeps the Atlas source URL (company site or EU decision) and confidence.
Status: operating -> PRODUCER, planned / construction -> DEVELOPMENT, care-and-maintenance -> CARE_AND_MAINTENANCE, closed -> CLOSED.
facility_capacity: one row per material, annual_capacity NULL; facility_stage Mine / Refinery / Smelter for primary sites and 'Recycling'
(phase Secondary) for the Atlas 'recovery' sites; facility_status = the Atlas status (checked Sep-Nov 2026), data_year 2026.
Usage: python load_crm_atlas_forlini.py [--dry | --undo]
"""
import csv, os, re, sys, time
import psycopg2

DRY, UNDO = "--dry" in sys.argv, "--undo" in sys.argv
TAG = "migration_crm_atlas_forlini_20261123"
SRC = "CRM_ATLAS_FORLINI"
D = "D:/CriticalMineralsDB/Europe/CRM_Atlas_Forlini_20261123/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
CREDIT = "Critical Raw Materials Atlas (Vincenzo Forlini, 2026), https://vincenzo-forlini.github.io/Critical-Raw-Materials-Atlas/, MIT licence"
IDS = ["se-woxna-lem", "no-heroya-reetec", "de-burghausen-wacker", "fr-larochelle-solvay", "fr-jarrie-framatome", "es-lascruces-fqm",
       "es-arteixo-ferroglobe", "at-stmartin-wbh", "cz-karvina-okd", "pl-jastrzebie-jsw", "gb-ellesmere-lcm", "de-dormagen-cylib",
       "de-burghausen-tozero", "gb-birmingham-hypromag", "gb-belfast-ionic", "gb-plymouth-altilium", "no-fredrikstad-hydrovolt",
       "ch-biberist-librec", "fr-lyon-mecaware", "gb-teesside-greenlithium"]
# Atlas material -> (commodity_id, commodity_name as used by the USGS facility rows)
MAT = {"Aluminium and bauxite": (1078, "Aluminum"), "Cobalt": (1105, "Cobalt"), "Copper": (1106, "Copper"), "Hafnium": (1085, "Hafnium"),
       "Lithium": (1089, "Lithium"), "Manganese": (1112, "Manganese"), "Nickel": (1107, "Nickel"), "Natural graphite": (994, "Graphite"),
       "Heavy rare earth elements": (1123, "Rare earths"), "Light rare earth elements": (1123, "Rare earths"), "Silicon metal": (1147, "Silicon"),
       "Tungsten": (1103, "Tungsten"), "Coking coal": (961, "Coal")}
STATUS = {"operating": "PRODUCER", "planned": "DEVELOPMENT", "construction": "DEVELOPMENT", "care-and-maintenance": "CARE_AND_MAINTENANCE", "closed": "CLOSED"}
STAGE = {"mining": ("Mines and Quarries", "Mine", "Primary"), "refining": ("Mineral Processing Plant", "Refinery", "Primary"),
         "smelting": ("Mineral Processing Plant", "Smelter", "Primary"), "processing": ("Mineral Processing Plant", "Refinery", "Primary"),
         "recovery": ("Recycling Plant", "Recycling", "Secondary")}
WORKINGS = {"mining": None, "refining": "Refinery", "smelting": "Smelter", "processing": "Processing plant", "recovery": "Recycling plant"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
if UNDO:
    c.execute("DELETE FROM core.facility_capacity WHERE created_by = %s", (TAG,)); log("capacity", c.rowcount)
    c.execute("DELETE FROM core.occurrence_ownership WHERE created_by = %s", (TAG,)); log("ownership", c.rowcount)
    c.execute("DELETE FROM core.occurrence_commodities WHERE created_by = %s", (TAG,)); log("commodities", c.rowcount)
    c.execute("DELETE FROM core.external_ids WHERE created_by = %s", (TAG,)); log("external ids", c.rowcount)
    c.execute("DELETE FROM geochem.sample_occurrence_links l USING core.occurrences o WHERE o.occurrence_id = l.occurrence_id AND o.created_by = %s", (TAG,)); log("sample links", c.rowcount)
    c.execute("DELETE FROM core.occurrences WHERE created_by = %s", (TAG,)); log("occurrences", c.rowcount)
    c.execute("DELETE FROM core.data_sources WHERE source_system = %s AND created_by = %s", (SRC, TAG)); log("data source", c.rowcount)
    g.commit(); log("UNDONE"); sys.exit()

rd = lambda f: list(csv.DictReader(open(D + f, encoding="utf-8-sig")))
fac = {r["id"]: r for r in rd("facilities.csv")}
city = {(r["city"], r["country"]): r for r in rd("cities.csv")}
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s", (TAG,))
assert c.fetchone()[0] == 0, "already loaded - run --undo first"
c.execute("SELECT iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'")
JI = dict(c.fetchall())
c.execute("SELECT company_id, name, short_name FROM core.companies WHERE is_active")
nz = lambda v: re.sub(r"\s+", " ", re.sub(r"\b(inc|corp|corporation|ltd|limited|llc|plc|company|co|holdings|group|the|sa|nv|ag|gmbh|se|as|asa|ab)\b", " ",
                                         re.sub(r"[^a-z0-9 ]+", " ", (v or "").lower()))).strip()
comp = {}
for ci, nm, sn in c.fetchall():
    for v in (nm, sn):
        if nz(v) and len(nz(v)) > 3: comp[nz(v)] = ci
n_occ = n_cap = n_own = 0
for aid in IDS:
    f = fac[aid]
    cy = city[(f["city"], f["country"])]
    lat, lon, iso = float(cy["lat"]), float(cy["lon"]), cy["country_code"]
    assert iso in JI, (aid, iso)
    mats = [m for m in MAT if f.get(m, "").strip()]
    assert mats, aid
    ft, stage, phase = STAGE[f["stage"]]
    # nearest existing record, for the comment (the comparison already showed it is a different site)
    c.execute("""SELECT o.name, round(ST_Distance(o.geog, ST_MakePoint(%s,%s)::geography)) FROM core.occurrences o
                 WHERE o.is_active ORDER BY o.geog <-> ST_MakePoint(%s,%s)::geography LIMIT 1""", (lon, lat, lon, lat))
    near, dist = c.fetchone()
    com = " | ".join(x for x in [
        f"{f['name']} - {f['stage']} site ({', '.join(mats)}) from the {CREDIT}",
        f"Atlas status (checked {f['last_checked']}): {f['status']}; Atlas confidence: {f['confidence']}",
        f"Note (Atlas): {f['note']}" if f["note"] else None,
        f"Atlas source: {f['source_url']}" if f["source_url"] else None,
        f"Strategic Project (CRMA): {f['crma_project']}" if f.get("crma_project") else None,
        f"POSITION IS APPROXIMATE: placed at the city point of {f['city']} ({f['country']}); the site is in or near that town",
        f"Nearest existing record: {near} ({dist} m) - a different site",
        "The Atlas author describes the data as a seed dataset compiled from public knowledge, not a citable source; cite the linked source.",
        f"Load tag {TAG}"] if x)
    if DRY:
        log("DRY", aid, "|", f["name"], "|", STATUS[f["status"]], "|", stage, "|", mats, "|", f["company"], "->", comp.get(nz(f["company"])))
        continue
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, comments, is_active,
                 created_by, created_date, position_accuracy) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,%s,true,%s,now(),'TOWN_CENTROID')
                 RETURNING occurrence_id""",
              (f["name"], f["stage"] == "mining", JI[iso], lon, lat, STATUS[f["status"]], WORKINGS[f["stage"]], com, TAG))
    oid = c.fetchone()[0]; n_occ += 1
    seen = set()
    for i, m in enumerate(mats):
        cid, cname = MAT[m]
        if cid not in seen:
            c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s) ON CONFLICT DO NOTHING",
                      (oid, cid, "PRIMARY" if not seen else "SECONDARY", TAG))
        if cid in seen and cname == "Rare earths":
            continue   # heavy + light rare earths -> one 'Rare earths' facility row
        seen.add(cid)
        c.execute("""INSERT INTO core.facility_capacity (occurrence_id, commodity_id, commodity_name, commodity_group, feature_type, facility_stage, phase,
                     product_form, annual_capacity, capacity_notes, facility_status, data_year, source_system, source_row_id, source_urls, is_active, created_by, created_date)
                     VALUES (%s,%s,%s,NULL,%s,%s,%s,NULL,NULL,%s,%s,2026,%s,%s,%s,true,%s,now())""",
                  (oid, cid, cname, ft, stage, phase, "No capacity published in the source; site listed by the Critical Raw Materials Atlas",
                   f["status"], SRC, f"{aid[:24]}:{cid}", [u for u in [f["source_url"]] if u], TAG))
        n_cap += 1
    c.execute("""INSERT INTO core.occurrence_ownership (occurrence_id, owner_name, company_id, ownership_role, share_pct, as_of_year, source_system, footnote, created_by)
                 VALUES (%s,%s,%s,'OPERATOR',NULL,2026,%s,NULL,%s)""", (oid, f["company"], comp.get(nz(f["company"])), SRC, TAG))
    n_own += 1
    c.execute("""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by)
                 VALUES ('OCCURRENCE',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (oid, SRC, aid, f["confidence"].upper(), TAG))
if DRY:
    g.rollback(); log("DRY RUN - nothing written"); sys.exit()
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'Vincenzo Forlini (independent)','Critical Raw Materials Atlas - European CRM facilities (20 sites missing from other sources)',
             'MIT','https://opensource.org/license/mit',true,%s,true,
             'Cleared: repository LICENSE = MIT (c) 2026 Vincenzo Forlini, read via the GitHub API 2026-11-23; CSVs downloaded with user approval. Loaded 2026-11-23.',
             'Seed dataset compiled from public knowledge, not a citable source (author): positions at city level (TOWN_CENTROID), status as checked Sep-Nov 2026, no capacities; cite the linked company or EU source. Only the 20 sites not already in USGS / CRMA / national records were loaded.',
             %s,'2026-11-23',true,%s,now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, CREDIT + ".", r"D:\CriticalMineralsDB\Europe\CRM_Atlas_Forlini_20261123\LICENSE.txt", TAG))
g.commit()
log("occurrences", n_occ, "| facility rows", n_cap, "| operators", n_own)
