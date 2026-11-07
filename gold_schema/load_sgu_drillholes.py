"""SGU Borrhål (Swedish drill holes, CC0 1.0) -> interzona_cm drilling.drillholes.

Source: Geological Survey of Sweden (SGU), Borrhål GeoPackage (borrhal.zip, product 2.1, SGU last-modified 2025-09-24, downloaded 2026-11-07 to
D:/CriticalMineralsDB/Sweden/download_20261107/borrhal; evidence in Documents/Licence_Evidence/SGU_Sweden). 36,672 holes, collars only: no assays,
logs or downhole surveys are in the product (the 'analyse' / 'dhprotocol' flags only say SGU's archive holds them).
Field meanings (product description p.3-4): depth_from = start of hole below surface, depth_to = end of hole, tot_depth = metres of core kept,
archive = archive holding the core (NULL = no core kept), mine_level = level in a mine (collared underground).
Rules
  * position: SWEREF99 TM (EPSG:3006) n_sweref/e_sweref; where missing, RT90 2.5 gon V (EPSG:3021) northing/easting; holes with neither are skipped.
    position_accuracy_m from qpos: 5 RTK -> 0.1, 4 DGPS -> 1, 3 -> 50, 2 -> 200, 1 'within the map sheet' -> 5000; otherwise NULL.
  * total_depth_m = depth_to (end of hole), else tot_depth. date_drilled = 1 January of drillyear (year only; noted in comments).
  * dip: SGU records most holes with positive dip = downward. Stored with our convention (negative = downward): surface holes -> -|dip|;
    underground holes: positive -> negative, negative -> NULL (could be up-holes; SGU value kept in comments). |dip| > 90 -> NULL (kept in comments).
    azimuth outside 0-360 -> NULL (kept in comments).
  * duplicate idcode (64 rows) -> source_hole_id idcode + '#' + SGU row id.
  * company = previous owner of the information (prev_owner). core_status from archive/tot_depth; hyperspectral scan links kept in comments.
Usage: python load_sgu_drillholes.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import os, sys, sqlite3, time, collections
import psycopg2
from psycopg2.extras import execute_values
from pyproj import Transformer

DRY = "--dry" in sys.argv
TAG = "migration_sgu_drillholes_20261107"
SRC = "SWEDEN_SGU_BORRHAL"
HERE = os.path.dirname(os.path.abspath(__file__))
GPKG = "D:/CriticalMineralsDB/Sweden/download_20261107/borrhal/extracted/borrhal.gpkg"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def num(s):
    try: return float(str(s).replace(",", ".").strip())
    except (TypeError, ValueError): return None


def note(*pairs):
    return "; ".join(f"{k}: {v}" for k, v in pairs if v not in (None, "", "N/A"))


ACC = {"5": 0.1, "4": 1, "3": 50, "2": 200, "1": 5000}
t3006 = Transformer.from_crs(3006, 4326, always_xy=True)
t3021 = Transformer.from_crs(3021, 4326, always_xy=True)
src = sqlite3.connect(f"file:{GPKG}?mode=ro", uri=True); src.row_factory = sqlite3.Row
rows = [dict(r) for r in src.execute("SELECT * FROM borrhal")]
dup = collections.Counter(r["idcode"] for r in rows)
log("SGU drill holes", len(rows), "| duplicate idcodes", sum(1 for k, v in dup.items() if v > 1))
recs, skipped, stats = [], 0, collections.Counter()
for r in rows:
    e, n = num(r["e_sweref"]), num(r["n_sweref"])
    if e and n:
        lon, lat = t3006.transform(e, n); ox, oy, crs = e, n, "SWEREF99 TM (EPSG:3006)"
    elif num(r["easting"]) and num(r["northing"]):
        ox, oy = num(r["easting"]), num(r["northing"]); lon, lat = t3021.transform(ox, oy); crs = "RT90 2.5 gon V (EPSG:3021)"; stats["rt90"] += 1
    else:
        skipped += 1; continue
    if not (10.5 < lon < 24.5 and 55 < lat < 69.2):
        stats["outside_sweden_skipped"] += 1; continue
    ug = str(r["mine_level"] if r["mine_level"] is not None else "").strip() != ""
    d = r["dip"]; dip = None; dipnote = None
    if d is not None:
        if abs(d) > 90: dipnote = f"SGU dip {d} out of range, not used"; stats["dip_bad"] += 1
        elif not ug: dip = -abs(d)
        elif d >= 0: dip = -d
        else: dipnote = f"SGU dip {d} on an underground hole (possibly an up-hole), not used"; stats["dip_ug_neg"] += 1
    az = r["azimuth"]
    aznote = None
    if az is not None and not (0 <= az <= 360): aznote = f"SGU azimuth {az} out of range, not used"; az = None; stats["az_bad"] += 1
    dto, tot = num(r["depth_to"]), num(r["tot_depth"])
    depth = dto if dto and dto > 0 else (tot if tot and tot > 0 else None)
    yr = str(r["drillyear"] if r["drillyear"] is not None else "").strip()
    ddate = f"{yr}-01-01" if yr.isdigit() and 1850 <= int(yr) <= 2026 else None
    dfr = num(r["depth_from"])
    span = ", ".join(x for x in ((f"{tot:g} m of core" if tot else None), (f"hole {dfr:g}-{dto:g} m" if dto and dfr is not None else None)) if x)
    core = (f"core kept at SGU ({span})" if span else "core kept at SGU") if r["archive"] else "no core kept at SGU"
    hyper = [x for x in (r["level0zipfile1"], r["level2zipfile1"]) if x]
    sid = r["idcode"] if dup[r["idcode"]] == 1 else f"{r['idcode']}#{r['id']}"
    recs.append((SRC, sid[:60], r["drillhole"] or r["idcode"], r["name"], (r["prev_owner"] or None),
                 "core drilling (SGU Borrhål)", ddate, depth, az, dip, num(r["zkoord"]), lat, lon, f"SRID=4326;POINT({lon} {lat})", f"SRID=4326;POINT({lon} {lat})", ox, oy, crs,
                 ACC.get(str(r["qpos"])), r["qpos_tx"] or r["references"], ug, core, "SGU National Drill Core Archive, Malå" if r["archive"] else None,
                 note(("Source", "Geological Survey of Sweden (SGU), Borrhål (CC0 1.0)"), ("SGU id", r["idcode"]), ("Drill year", yr or None),
                      ("Alternative name", r["altname"]), ("Mine level", r["mine_level"]), ("District", r["district"]), ("Local grid", r["local_grid"]),
                      ("County", r["county"]), ("Municipality", r["commune"]), ("Previous owner", r["prev_owner"]), ("Core archive", r["archive"]),
                      ("Geological log at SGU", "yes" if r["dhprotocol"] else None), ("Analyses at SGU", "yes" if r["analyse"] else None),
                      ("Downhole measurements at SGU", "yes" if r["measure"] else None), ("Report", r["report"]), ("Scanned", "yes" if r["scannat"] else None),
                      ("Hyperspectral scan", " | ".join(hyper) if hyper else None), ("Hyperspectral viewer", r["viewer_url"]),
                      ("Collar casing", r["rorhojd"]), ("Coordinate source", r["references"]), ("Coordinate note", r["qinfo"]), ("SGU comments", r["comments"]),
                      ("Dip note", dipnote), ("Azimuth note", aznote))))
log("loadable", len(recs), "| no position (skipped)", skipped, "|", dict(stats))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM drilling.drillholes WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT drill_type_id FROM geochem.drill_types WHERE drill_type_code = 'DIAMOND'"); DIAMOND = c.fetchone()[0]
execute_values(c, """INSERT INTO drilling.drillholes (source_system, source_hole_id, hole_name, prospect, company, drill_type_local, date_drilled, total_depth_m,
                     azimuth_deg, dip_deg, collar_elevation_m, lat, lon, geom, geog, original_x, original_y, original_crs, position_accuracy_m, position_method,
                     collared_underground, core_status, core_store_location, comments, drill_type_id, is_active, created_by, created_date) VALUES %s""",
               recs, template=f"(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromEWKT(%s),ST_GeomFromEWKT(%s)::geography,%s,%s,%s,%s,%s,%s,%s,%s,%s,{DIAMOND},true,'{TAG}',now())",
               page_size=2000)
c.execute("SELECT count(*) FROM drilling.drillholes WHERE source_system = %s", (SRC,)); log("inserted", c.fetchone()[0])

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,false,%s,true,%s,%s,%s,'2026-11-07',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Geological Survey of Sweden (SGU)", "Borrhål (drill holes), product version 2.1, GeoPackage, SGU last modified 2025-09-24",
           "CC0 1.0 Universal (public domain dedication)", "https://www.sgu.se/produkter-och-tjanster/geologiska-data/om-geologiska-data/licensvillkor/",
           "Source: Geological Survey of Sweden (SGU), Borrhål, CC0 1.0. Attribution is not required under CC0 and is given as a courtesy.",
           "Cleared: CC0 1.0 stated in the product description and SGU licence page (checked 2026-11-07). Loaded 2026-11-07.",
           "Collars only: no assays, logs or downhole surveys in the product (SGU's archive holds them for many holes). Drill year only (date set to 1 January). "
           "Information mostly from external drilling protocols and reports (previous owners include Boliden, NSG, Viscaria/Outokumpu); SGU does not vouch for it. "
           "Coordinates often converted from RT90, UTM or local grids. Holes without coordinates (about 9,300) and one with a mistyped northing (HTM91003) not loaded.",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/SGU_Sweden/EVIDENCE.md", TAG))

c.execute("""SELECT count(*), count(dip_deg), count(azimuth_deg), count(total_depth_m), round(sum(total_depth_m)), count(position_accuracy_m),
             count(*) FILTER (WHERE collared_underground), count(*) FILTER (WHERE core_store_location IS NOT NULL), min(date_drilled), max(date_drilled)
             FROM drilling.drillholes WHERE source_system = %s""", (SRC,))
log("holes, with dip, azimuth, depth, sum depth m, accuracy, underground, core at SGU, first/last year", c.fetchone())
c.execute("SELECT count(*) FROM drilling.drillholes WHERE source_system = %s AND NOT ST_Intersects(geom, ST_MakeEnvelope(10.5, 55, 24.5, 69.2, 4326))", (SRC,))
log("outside Sweden box (must be 0)", c.fetchone()[0])
c.execute("SELECT count(*) FROM drilling.drillholes WHERE source_system = %s AND NOT ST_Equals(geom, geog::geometry)", (SRC,)); log("geom/geog mismatch (must be 0)", c.fetchone()[0])
c.execute("SELECT company, count(*) FROM drilling.drillholes WHERE source_system = %s GROUP BY 1 ORDER BY 2 DESC LIMIT 6", (SRC,)); log("top companies", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
