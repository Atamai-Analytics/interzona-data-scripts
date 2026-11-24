"""IAEA World Distribution of Uranium Deposits (2nd ed. 2018, STI/PUB/1800) -> STAGING deposits schema (criticialmineralsexp public.deposits /
locations / deposit_commodities / deposit_endowment). User request 2026-11-24: "extract the deposits to the deposits schema in the meantime".

HELD - NOT FOR RELEASE: (c) IAEA; commercial-product and AI use need IAEA permission (Licence_Evidence/IAEA_UDEPO/EVIDENCE.md).
All rows are inserted with isactive = false and createdby = TAG, and every comment says HELD. Do not activate, copy to interzona_cm or
export to LithoSurfer until the IAEA grants permission.

Input: D:/CriticalMineralsDB/World/IAEA_Uranium_Deposits_2018_STAGING/iaea_udepo_2018_map_extract_STAGING.csv (1,950 deposits; positions
read from the world map, median ~3 km). Country from interzona_cm core.country_boundaries (point in polygon, else nearest within 50 km).
Usage: python load_iaea_udepo_staging.py [--dry | --undo]
"""
import csv, os, sys, psycopg2

TAG = "staging_iaea_udepo_20261124"
SRC = "D:/CriticalMineralsDB/World/IAEA_Uranium_Deposits_2018_STAGING/iaea_udepo_2018_map_extract_STAGING.csv"
DATASOURCE = "IAEA World Distribution of Uranium Deposits, 2nd ed. 2018 (STI/PUB/1800) - HELD, IAEA permission required"
HELD = "HELD - not for release: (c) IAEA, permission requested"
U = 235
TYPE_MAP = {  # IAEA type (or type|subtype) -> deposit_types.deposit_type_id; unmapped types keep only deposit_type_local
    "Sandstone": 35, "Proterozoic unconformity": 69, "Collapse Breccia Pipe": 71, "Carbonate": 36, "Lignite-coal": 37,
    "Black Shales": 59, "Phosphate": 60, "Paleo-quartz-pebble conglomerate": 16, "Polymetallic Breccia Complex": 103,
}
SIZE = {"1 - 300": "SMALL", "301 - 1000": "SMALL", "1001 - 2500": "SMALL", "2501 - 5000": "MEDIUM", "5001 - 10000": "MEDIUM",
        "10001 - 25000": "MEDIUM", "25001 - 50000": "LARGE", "50001 - 100000": "LARGE", "100001 - 1000000": "GIANT", "> 1000000": "GIANT"}

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
cx = dict(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
st = psycopg2.connect(dbname="criticialmineralsexp", **cx); s = st.cursor()

if "--undo" in sys.argv:
    s.execute("SELECT depositid, locationid FROM deposits WHERE createdby = %s", (TAG,)); rows = s.fetchall()
    ids = [r[0] for r in rows]; locs = [r[1] for r in rows]
    s.execute("DELETE FROM deposit_endowment WHERE depositid = ANY(%s)", (ids,))
    s.execute("DELETE FROM deposit_commodities WHERE depositid = ANY(%s)", (ids,))
    s.execute("DELETE FROM deposits WHERE depositid = ANY(%s)", (ids,))
    s.execute("DELETE FROM locations WHERE locationid = ANY(%s) AND createdby = %s", (locs, TAG))
    st.commit(); print("removed", len(ids)); sys.exit(0)

s.execute("SELECT count(*) FROM deposits WHERE createdby = %s", (TAG,))
if s.fetchone()[0]: sys.exit("already loaded - run --undo first")
R = list(csv.DictReader(open(SRC, encoding="utf-8")))

# country by point (interzona_cm)
g = psycopg2.connect(dbname="interzona_cm", **cx); c = g.cursor()
c.execute("CREATE TEMP TABLE p (id text, lat float8, lon float8)")
c.executemany("INSERT INTO p VALUES (%s,%s,%s)", [(r["udepo_id"], float(r["lat"]), float(r["lon"])) for r in R])
c.execute("""SELECT p.id, (SELECT CASE WHEN b.iso_a3 ~ '^[A-Z]{3}$' THEN b.iso_a3 ELSE b.adm0_a3 END FROM core.country_boundaries b
                           WHERE ST_DWithin(b.geom::geography, ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)::geography, 50000)
                           ORDER BY b.geom <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326) LIMIT 1) FROM p""")
iso = dict(c.fetchall()); g.close()
s.execute("SELECT countrycode3, countryid FROM countries WHERE isactive IS NOT FALSE")
cid = {k.strip(): v for k, v in s.fetchall() if k}
miss = sum(1 for r in R if cid.get(iso.get(r["udepo_id"]) or "") is None)
print(f"{len(R)} deposits; no country match {miss}; typed {sum(1 for r in R if r['type'] in TYPE_MAP)}")
if "--dry" in sys.argv: sys.exit(0)

n = 0
for r in R:
    lat, lon = float(r["lat"]), float(r["lon"])
    sub = f" / {r['subtype']}" if r["subtype"] else ""
    s.execute("""INSERT INTO locations (locationcode, locationname, locationtype, latitude, longitude, srid_geographic, geom, countryid,
                 datasource, datasource_url, external_id, comments, createdby, createddate, isactive)
                 VALUES ('IAEA', %s, 'DEPOSIT', %s, %s, 4326, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s,
                 'https://www.iaea.org/publications/12314/world-distribution-of-uranium-deposits', %s, %s, %s, now(), false) RETURNING locationid""",
              (r["name"], lat, lon, lon, lat, cid.get(iso.get(r["udepo_id"]) or ""), DATASOURCE, f"UDEPO:{r['udepo_id']}",
               f"{HELD} | Position read from the IAEA 2018 world map (Mercator, CM 10W), median ~3 km; overlapping symbols may be off more", TAG))
    loc = s.fetchone()[0]
    s.execute("""INSERT INTO deposits (locationid, deposit_type_id, deposit_type_local, deposit_group_local, size_category, resource_data, grade_info,
                 "references", comments, isactive, createdby, createddate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,now()) RETURNING depositid""",
              (loc, TYPE_MAP.get(r["type"]), f"IAEA: {r['type'] or 'unclassified'}{sub}", r["type"] or None, SIZE.get(r["resources_tU_range"], "UNKNOWN"),
               f"Uranium resources {r['resources_tU_range']} tU (IAEA range: maximum of original resource, production or remaining resource; may be historic)",
               f"Grade {r['grade_U_pct_range']} % U (IAEA range)" if r["grade_U_pct_range"] not in ("", "<Null>") else None,
               "Fairclough, M.C., Irvine, J.A., Katona, L.F., Slimmon, W.L. (2018) World Distribution of Uranium Deposits, 2nd ed., IAEA STI/PUB/1800",
               f"{HELD} | UDEPO id {r['udepo_id']} | nearest existing U occurrence in interzona_cm: {r['nearest_occurrence_id']} {r['nearest_name']} "
               f"({r['nearest_km']} km, {r['match_class']})", TAG))
    dep = s.fetchone()[0]
    s.execute("""INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, isactive, createdby, createddate)
                 VALUES (%s, %s, 'PRIMARY', false, %s, now())""", (dep, U, TAG))
    for seq, (measure, val, unit) in enumerate([("AMOUNT", r["resources_tU_range"], "tU (range)"), ("GRADE", r["grade_U_pct_range"], "% U (range)")]):
        if val and val != "<Null>":
            s.execute("""INSERT INTO deposit_endowment (depositid, commodity_id, commodity_raw, data_type, measure, value_num, value_text, unit, seq,
                         source, isactive, createdby, createddate) VALUES (%s,%s,'U','RESOURCE',%s,NULL,%s,%s,%s,%s,false,%s,now())""",
                      (dep, U, measure, val, unit, seq, "IAEA World Distribution of Uranium Deposits 2018 (HELD)", TAG))
    n += 1
st.commit(); print("loaded", n, "deposits (isactive = false, HELD)")
