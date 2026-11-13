"""Builds core.facility_superseded: older-release USGS capacity rows that a 2024 Minerals Yearbook row replaces (same plant, newer figure).
The view core.facility_capacity_published sets is_latest_year = false for these rows. Run after build_facility_clusters.py, after any
facility load and after hide_myb2024.py restore.

An older row (any USGS source except USGS_MYB2024) is superseded by a 2024 'anchor' row (USGS_MYB2024, not placed only at a town point) when
  - same commodity (case-insensitive), and
  - compatible stage: same stage_group; or one side is the generic 'Other processing plant' and the other is any non-Mine stage (the older
    Africa release files Mufulira/Nkana/Chambishi smelters and refineries as generic processing plants, the 2024 table names the stage), and
  - same place: same complex in core.facility_site_clusters (sites within ~3 km), or within 10 km when either point is only an
    AREA_CENTROID AND the names share a distinctive word (a town or mine name: 'Plant in Pingluo County' / 'Plant in Pingluo County'; without the name test
    10 km wrongly merged KOV with Kilamusembu and Impala with the Rustenburg plant).   - or a reviewed pair in MANUAL below (older USGS facility id -> 2024 facility id; rows of the same commodity are paired). A general
    'shared owner within 10 km' rule was tried 2026-11-11 and rejected: right for Obi, wrong for KOV/Kilamusembu, Impala/Bafokeng, Baise/Tiandong.
  - TOWN rule (2026-11-13): a 2024 row placed only at a town point (TOWN_CENTROID) supersedes an older row of the same commodity and
    compatible stage within 15 km when the older row's NAME contains the place named in the 2024 location text ('Plant in Dukem' 2024 ->
    'Plant at Dukem' 2014); one-for-one: a 2024 row that would replace several older facilities is dropped (as for the area rule).
Older releases never supersede each other. Usage: python build_facility_supersede.py [--dry]
"""
import csv, os, re, sys, unicodedata, psycopg2

DRY = "--dry" in sys.argv

# Reviewed same-plant pairs the automatic rules miss: (older source_system, older USGS facility id, 2024 facility id, evidence)
MANUAL = [
    ("USGS_SWASIA_GIS", "IDN218", "IDN0043", "Obi Island HPAL: 2018 'HPAL Plant' (7.6 km from the 2024 area point); both owned by "
                                             "PT Halmahera Persada Lygend (Harita/Lygend); 2024 = MHP + sulfate, 2018 = nickel + cobalt sulphate"),
    ("USGS_SWASIA_GIS", "AFG029", "AFG0026", "Bakhut/Bakhud fluorspar mine: same owner Amania Mining Co., 10,812 t vs 10,800 t, 9.5 km apart"),
    ("USGS_CHINA_GIS", "CHN0154", "CHN0267", "Yongdeng/Yondeng ferrosilicon plant: same owner Tengda Xibei Ferroalloy, 250,000 t both, ~6 km "
                                            "(CHN0153 Dragon Northwest ferrochromium in the same county is a different plant - not paired)"),
    ("USGS_AFRICA_GIS", "ZAF179", "ZAF0235", "Daniëlskuil/Danielskuil lime plant: same owner Idwala Lime, 1,000,000 t both, ~6 km"),
    # Puerto Ordaz (Ciudad Guayana) complex, 2026-11-12: 2014 LAC points vs 2024 lines (town-placed or on another LAC point), same operator and
    # capacity; the releases name the commodity differently ('Iron and steel' vs 'Direct-reduced iron' / 'Iron ore'), so these pair any commodity.
    ("USGS_LAC_GIS", "VE43", "VEN0002", "Alcasa aluminium smelter, 170,000 t both", True),
    ("USGS_LAC_GIS", "VE44", "VEN0006", "Venalum aluminium smelter, 430,000 t (2014) / 440,000 t (2024)", True),
    ("USGS_LAC_GIS", "VE45", "VEN0029", "FerroAtlantica ferrosilicon plant, 96,000 t both", True),
    ("USGS_LAC_GIS", "VE49", "VEN0049", "SIDOR pellet plant, 4,250,000 t both", True),
    # 2026-11-13, after the gazetteer placement: pairs the town rule leaves out by design (one 2024 row, two older facilities / other name)
    ("USGS_AFRICA_GIS", "NGA056", "NGA0010", "Ewekoro cement plants (Lafarge Africa): 2018 NGA056+NGA057 share one 3,500,000 t capacity; 2024 'Plants in Ewekoro' 3,500,000 t"),
    ("USGS_AFRICA_GIS", "NGA057", "NGA0010", "Ewekoro cement plants (Lafarge Africa): 2018 NGA056+NGA057 share one 3,500,000 t capacity; 2024 'Plants in Ewekoro' 3,500,000 t"),
    ("USGS_AFRICA_GIS", "NGA066", "NGA0008", "Sokoto cement plant at Kalambaina (Cement Co. of Northern Nigeria, now BUA): 2018 500,000 t, 2024 8,000,000 t after expansion, 2 km apart"),
    ("USGS_LAC_GIS", "VE46", "VEN0022", "Orinoco Iron / Briquetera del Orinoco HBI plant, 2,200,000 t both", True),
    ("USGS_LAC_GIS", "VE47", "VEN0025", "Ferrominera HBI plant, 1,000,000 t (2014 also 1,100,000 t line) / 1,000,000 t", True),
    ("USGS_LAC_GIS", "VE48", "VEN0024", "Comsigua HBI plant, 1,000,000 t both", True),
]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')

STAGE = """CASE WHEN fc.feature_type ILIKE 'Brine%%' OR fc.feature_type = 'B' THEN 'Brine operation'
            WHEN fc.facility_stage = 'Mine' OR (fc.facility_stage IS NULL AND (fc.feature_type ILIKE 'Mines%%' OR fc.feature_type = 'M')) THEN 'Mine'
            WHEN fc.facility_stage IN ('Smelter', 'Refinery', 'Concentrator') THEN fc.facility_stage
            WHEN fc.facility_stage ILIKE '%%Smelter%%' THEN 'Smelter'
            ELSE 'Other processing plant' END"""

STOP = ", ".join(repr(w) for w in """plant plants mine mines smelter refinery facility facilities factory works project operation operations
near company quarry quarries deposit processing cement mill limited group industrial zone area complex station field fields leach heap
north south east west upper lower county province district island chromite ferroalloy ferroalloys steel alumina aluminum
aluminium iron nickel copper gold silver zinc lead coal salt lime gypsum phosphate surface underground open""".split())

SQL = rf"""
WITH r AS (
  SELECT fc.facility_capacity_id, fc.source_system, lower(fc.commodity_name) AS com, {STAGE} AS stage, o.geog, o.position_accuracy AS pos, lower(o.name) AS nm,
         cl.cluster_id
  FROM core.facility_capacity fc JOIN core.occurrences o ON o.occurrence_id = fc.occurrence_id
  LEFT JOIN core.facility_site_clusters cl ON cl.occurrence_id = fc.occurrence_id
  WHERE fc.is_active IS DISTINCT FROM false AND o.is_active AND fc.source_system LIKE 'USGS%%'
), a AS (SELECT * FROM r WHERE source_system = 'USGS_MYB2024' AND pos IS DISTINCT FROM 'TOWN_CENTROID'),
   old AS (SELECT * FROM r WHERE source_system <> 'USGS_MYB2024')
SELECT DISTINCT ON (old.facility_capacity_id) old.facility_capacity_id, a.facility_capacity_id,
       CASE WHEN old.cluster_id = a.cluster_id THEN 'complex' ELSE 'area 10 km' END
FROM old JOIN a ON a.com = old.com
 AND (a.stage = old.stage OR (a.stage = 'Other processing plant' AND old.stage NOT IN ('Mine', 'Brine operation'))
                          OR (old.stage = 'Other processing plant' AND a.stage NOT IN ('Mine', 'Brine operation')))
 AND (old.cluster_id = a.cluster_id
      OR ((old.pos = 'AREA_CENTROID' OR a.pos = 'AREA_CENTROID') AND ST_DWithin(old.geog, a.geog, 10000)
          AND EXISTS (SELECT 1 FROM regexp_split_to_table(old.nm, '[^a-z]+') w
                      WHERE length(w) >= 4 AND w NOT IN ({STOP}) AND strpos(old.com, w) = 0 AND a.nm ~ ('\m' || w || '\M'))))
ORDER BY old.facility_capacity_id, (old.cluster_id = a.cluster_id) DESC
"""

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute(SQL); rows = c.fetchall()
# One-for-one for the 10 km area rule (2026-11-12): a single 2024 row may not replace rows of SEVERAL older USGS facilities - that hid the
# three Baotou separation plants (CHN1155-1157) behind one 2024 'Mine in Baotou' row on a shared town name.
area = [r for r in rows if r[2] == "area 10 km"]
if area:
    c.execute("SELECT facility_capacity_id, split_part(source_row_id, '-', 1) FROM core.facility_capacity WHERE facility_capacity_id = ANY(%s)", ([r[0] for r in area],))
    old_fac = dict(c.fetchall())
    per_new = {}
    for r in area: per_new.setdefault(r[1], set()).add(old_fac[r[0]])
    many = {n for n, s in per_new.items() if len(s) > 1}
    dropped = [r for r in area if r[1] in many]
    rows = [r for r in rows if not (r[2] == "area 10 km" and r[1] in many)]
    print("area-rule rows dropped (one 2024 row would replace several older facilities):", len(dropped))
# TOWN rule (2026-11-13): town-placed 2024 rows vs older rows named after the same place.
PL = "D:/CriticalMineralsDB/World/usgs_facilities_20261110/myb2024_placement.csv"
fold = lambda s: "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "").lower()) if not unicodedata.combining(ch))
words = lambda s: re.sub(r"[^a-z0-9]+", " ", fold(s)).split()
GENERIC = set("""village town city industrial zone area estate free port deposit deposits field settlement township near vicinity of outskirts
the district region province state county municipality""".split())
place = {}
for p in csv.DictReader(open(PL, encoding="utf-8", newline="")):
    if p["method"] == "TOWN" and p["location"]:
        w = [x for x in words(re.split(r"[,;()]| and | near ", p["location"])[0]) if x not in GENERIC]
        if w and len("".join(w)) >= 4: place[p["fid"]] = " ".join(w)
c.execute(f"""
WITH r AS (
  SELECT fc.facility_capacity_id, fc.source_system, fc.source_row_id, lower(fc.commodity_name) AS com, {STAGE} AS stage, o.geog,
         o.position_accuracy AS pos, o.name AS nm
  FROM core.facility_capacity fc JOIN core.occurrences o ON o.occurrence_id = fc.occurrence_id
  WHERE fc.is_active IS DISTINCT FROM false AND o.is_active AND fc.source_system LIKE 'USGS%%')
SELECT old.facility_capacity_id, a.facility_capacity_id, regexp_replace(a.source_row_id, '^FAC_|_[0-9]+$', '', 'g'), old.nm,
       split_part(old.source_row_id, '-', 1), ST_Distance(old.geog, a.geog)
FROM r a JOIN r old ON old.com = a.com AND old.source_system <> 'USGS_MYB2024'
 AND (a.stage = old.stage OR (a.stage = 'Other processing plant' AND old.stage NOT IN ('Mine', 'Brine operation'))
                          OR (old.stage = 'Other processing plant' AND a.stage NOT IN ('Mine', 'Brine operation')))
 AND ST_DWithin(old.geog, a.geog, 15000)
WHERE a.source_system = 'USGS_MYB2024' AND a.pos = 'TOWN_CENTROID'
ORDER BY ST_Distance(old.geog, a.geog)""")
done = {r[0] for r in rows}
town, best = [], {}
for old_id, new_id, fid, old_nm, old_fac, d in c.fetchall():
    pw = place.get(fid)
    if not pw or old_id in done or old_id in best: continue
    if re.search(r"\b" + re.escape(pw) + r"\b", " ".join(words(old_nm))):
        best[old_id] = (old_id, new_id, "town name", old_fac)
per_new = {}
for old_id, new_id, _, old_fac in best.values(): per_new.setdefault(new_id, set()).add(old_fac)
many = {n for n, s in per_new.items() if len(s) > 1}
town = [(o, n, rule) for o, n, rule, _ in best.values() if n not in many]
print("town-name rule:", len(town), "rows superseded |", sum(1 for v in best.values() if v[1] in many), "dropped (one 2024 row would replace several older facilities)")
rows += town
c.execute("""SELECT fc.facility_capacity_id, fc.source_row_id, fc.commodity_name, fc.annual_capacity, o.name FROM core.facility_capacity fc
             JOIN core.occurrences o USING (occurrence_id) WHERE fc.facility_capacity_id = ANY(%s)""",
          ([v[0] for v in best.values()] + [v[1] for v in best.values()],))
info = {x[0]: x[1:] for x in c.fetchall()}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "facility_supersede_town_rule_review.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["kept", "old_id", "old_row", "commodity", "old_capacity", "old_name", "new_id", "new_row", "new_capacity", "new_name"])
    for o, n, _, _ in best.values():
        w.writerow([n not in many, o, info[o][0], info[o][1], info[o][2], info[o][3], n, info[n][0], info[n][2], info[n][3]])

# Reviewed MANUAL pairs win over the automatic rules (2026-11-13): after a facility load, a new site can join a complex and the complex rule
# then pairs by commodity alone - Venalum (VE44, 430 kt) was paired with Alcasa's 2024 row (170 kt). Collect manual pairs first.
manual_rows = []
for entry in MANUAL:
    src, old_id, new_id, why = entry[:4]
    any_commodity = len(entry) > 4 and entry[4]
    c.execute(f"""SELECT DISTINCT ON (o.facility_capacity_id) o.facility_capacity_id, n.facility_capacity_id
                 FROM core.facility_capacity o JOIN core.facility_capacity n ON {"true" if any_commodity else "lower(n.commodity_name) = lower(o.commodity_name)"}
                 WHERE o.source_system = %s AND split_part(o.source_row_id, '-', 1) = %s AND o.is_active IS DISTINCT FROM false
                   AND n.source_system = 'USGS_MYB2024' AND regexp_replace(n.source_row_id, '^FAC_|_[0-9]+$', '', 'g') = %s
                   AND n.is_active IS DISTINCT FROM false
                 ORDER BY o.facility_capacity_id, n.facility_capacity_id""", (src, old_id, new_id))
    pairs = c.fetchall()
    print(f"manual {old_id} -> {new_id}: {len(pairs)} rows")
    manual_rows += [(p[0], p[1], "manual: " + why) for p in pairs]
mdone = {r[0] for r in manual_rows}
overridden = [r for r in rows if r[0] in mdone and r[1] != next(m[1] for m in manual_rows if m[0] == r[0])]
print("automatic pairs overridden by a manual pair:", len(overridden), overridden)
rows = [r for r in rows if r[0] not in mdone] + manual_rows
print("superseded rows:", len(rows), "| by complex:", sum(r[2] == 'complex' for r in rows), "| by 10 km area rule:",
      sum(r[2] == 'area 10 km' for r in rows), "| manual:", sum(r[2].startswith('manual') for r in rows))
if not DRY:
    c.execute("""CREATE TABLE IF NOT EXISTS core.facility_superseded (facility_capacity_id integer PRIMARY KEY,
                 superseded_by integer NOT NULL, rule text NOT NULL)""")
    c.execute("TRUNCATE core.facility_superseded")
    c.executemany("INSERT INTO core.facility_superseded VALUES (%s, %s, %s)", rows)
    c.execute("GRANT SELECT ON core.facility_superseded TO cm_app_readonly")
    g.commit()
    print("written core.facility_superseded")
g.close()
