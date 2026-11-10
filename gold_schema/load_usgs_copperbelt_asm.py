"""USGS 'A database of artisanal, small-scale, and large-scale mining in the Copperbelt region of the Democratic Republic of Congo and Zambia'
(Boston and Alessi, 2024, doi:10.5066/P9LWU4FT; ScienceBase 64dfd268d34e5f6cd553c2cf; FGDC access + use constraints 'None' = US public domain)
-> interzona_cm (2026-11-10).

Source: 164,674 cells of a 1 km grid (EPSG:32735); 1,628 cells flagged Mining = 1 with Scale ASM (artisanal and small-scale) or LSM (medium- and
large-scale), seen on very-high-resolution imagery 2019-2023 (Date field). Comm_DRC / Comm_Zam = POSSIBLE commodities copied from the DRC (2016)
or Zambia (2023) cadastre licence covering the cell - not observed commodities.

Method: touching mining cells of the same scale are merged into mining AREAS (153 LSM, 205 ASM). Per area:
  * LSM: existing active occurrences within 1 km of the area (cell size) -> ATTACH (external id 'lsm:<area>:<occurrence>', comment appended, and
    status UNKNOWN/OCCURRENCE/PROSPECT -> PRODUCER because the imagery shows active mining - not for processing plants, whose operation the
    imagery does not show; other statuses untouched). An LSM area with no occurrence
    inside -> NEW occurrence (is_deposit, workings_type 'Large-scale mining area').
  * ASM: always a NEW occurrence (workings_type 'Artisanal and small-scale mining', is_deposit false) - ASM sites are the new information.
  New records: point = area centroid (position_accuracy AREA_CENTROID), status PRODUCER (active mining on 2019-2023 imagery), name from the
  nearest named occurrence within 10 km; comments give area km2, cell count, imagery dates, possible commodities and the cadastre year.
  Country: from which cadastre field the cells use (DRC -> CD, Zambia -> ZM); if none, the nearest occurrence's country within 30 km.
  Commodities: Cu and Co only (the dataset maps copper-cobalt mining), as SECONDARY links, and only where the licence list names them.
Idempotent (source ids already present are skipped). Usage: python -P load_usgs_copperbelt_asm.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import os, re, sys, time, collections, warnings
import pyogrio, psycopg2, shapely
from shapely.ops import transform
from pyproj import Transformer
from psycopg2.extras import execute_values
warnings.filterwarnings("ignore")

DRY = "--dry" in sys.argv
TAG = "migration_usgs_copperbelt_20261110"
SRC = "USGS_COPPERBELT_ASM"
SHP = "D:/CriticalMineralsDB/Africa/copperbelt_asm_20261110/shp/Mining_Extent_Commodities_Final_reconciled_2.shp"
CITE = ("Boston, K.M., and Alessi, M.A., 2024, A database of artisanal, small-scale, and large-scale mining in the Copperbelt region of the "
        "Democratic Republic of Congo and Zambia: USGS data release, doi:10.5066/P9LWU4FT")
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


TO_WGS = Transformer.from_crs("EPSG:32735", "EPSG:4326", always_xy=True).transform
FILL = {"UNKNOWN", "OCCURRENCE", "PROSPECT"}
ATTACH_M = 1000   # cells are 1 km squares, so an area's edge is only known to ~1 km

# ------------------------------------------------------------------ areas
df = pyogrio.read_dataframe(SHP, where="Mining = 1", encoding="cp1252")
log("mining cells", len(df), dict(df.Scale.value_counts()))
areas = []
for sc in ("LSM", "ASM"):
    sub = df[df.Scale == sc].reset_index(drop=True)
    u = shapely.union_all(sub.geometry.buffer(1).values)
    parts = sorted(getattr(u, "geoms", [u]), key=lambda p: (-p.area, p.centroid.x))
    tree = shapely.STRtree(sub.geometry.values)
    for i, poly in enumerate(parts, 1):
        idx = tree.query(poly, predicate="intersects")
        cells = sub.iloc[idx]
        cells = cells[cells.geometry.centroid.within(poly)]
        drc = [x for x in cells.Comm_DRC if x]; zam = [x for x in cells.Comm_Zam if x]
        poss = list(dict.fromkeys(t.strip() for x in drc + zam for t in x.split(",") if t.strip()))
        dates = sorted(set(d for d in cells.Date if d))
        areas.append(dict(sid=f"{sc.lower()}:{i:03d}", scale=sc, n=len(cells), km2=round(poly.area / 1e6 - 0.0, 1),
                          poly=transform(TO_WGS, poly.buffer(-1)), cen=transform(TO_WGS, poly.centroid),
                          country="CD" if drc and not zam else "ZM" if zam and not drc else None,
                          cad="DRC cadastre (2016)" if drc else "Zambia cadastre (2023)" if zam else None,
                          poss=poss, dates=dates))
log("areas", collections.Counter(a["scale"] for a in areas), "| cells covered", sum(a["n"] for a in areas))
assert sum(a["n"] for a in areas) == len(df), "every mining cell must fall in exactly one area"

# ------------------------------------------------------------------ database
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                     user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,))
DONE = {x[0] for x in c.fetchall()}
log("source ids already loaded", len(DONE))
c.execute("SELECT iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code IN ('CD','ZM')")
JI = dict(c.fetchall())
c.execute("SELECT commodity_name, commodity_id FROM core.commodities WHERE commodity_name IN ('Cu','Co')")
CID = dict(c.fetchall())


def nearest(lon, lat, km):
    c.execute("""SELECT o.occurrence_id, o.name, j.iso_code, ST_Distance(o.geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d
                 FROM core.occurrences o LEFT JOIN core.jurisdictions j ON j.jurisdiction_id = o.jurisdiction_id
                 WHERE o.is_active AND o.created_by <> %s AND ST_DWithin(o.geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s)
                 ORDER BY d LIMIT 1""", (lon, lat, TAG, lon, lat, km * 1000))
    return c.fetchone()


stats, ext, links, logrows = collections.Counter(), [], [], []
status_fill = collections.Counter()
for a in areas:
    lon, lat = a["cen"].x, a["cen"].y
    near = nearest(lon, lat, 30)
    iso = a["country"] or (near[2] if near and near[2] in ("CD", "ZM") else None)
    poss = ", ".join(a["poss"]) if a["poss"] else None
    cuco = [x for x in ("Cu", "Co") if any(re.fullmatch(rf"{x}(O\d?)?", t) for t in a["poss"])]
    base = [f"{'Medium- and large-scale (LSM)' if a['scale'] == 'LSM' else 'Artisanal and small-scale (ASM)'} mining area {a['sid']} "
            f"of {a['km2']:.0f} km2 ({a['n']} active 1-km grid cells) mapped from 2019-2023 satellite imagery in the {CITE}",
            f"Imagery dates: {', '.join(a['dates'])}" if a["dates"] else None,
            f"Possible commodities (from the {a['cad']} licence covering the area, not observed): {poss}" if poss else
            "No cadastre commodity list for this area",
            "Point = area centroid"]
    if a["scale"] == "LSM":
        c.execute("""SELECT o.occurrence_id, o.name, o.status, o.workings_type FROM core.occurrences o
                     WHERE o.is_active AND o.created_by <> %s AND ST_DWithin(o.geog, ST_GeomFromText(%s, 4326)::geography, %s)""",
                  (TAG, a["poly"].wkt, ATTACH_M))
        inside = c.fetchall()
        if inside:
            note = (f"Inside a medium/large-scale mining area of {a['km2']:.0f} km2 mapped as ACTIVE on 2019-2023 imagery "
                    f"(USGS Copperbelt mining database doi:10.5066/P9LWU4FT, area {a['sid']})")
            for oid, name, st, work in inside:
                sid = f"{a['sid']}:{oid}"
                if sid in DONE: continue
                plant = work == "Processing plant" or bool(re.search(r"(?i)\(facility\)|\b(plant|smelter|refinery|concentrator)\b", name or ""))
                new = "PRODUCER" if st in FILL and not plant else st
                n2 = note + (f"; status changed {st} -> PRODUCER on 2026-11-10 from this source" if new != st else "")
                c.execute("""UPDATE core.occurrences SET status = %s, comments = concat_ws(' | ', comments, %s), modified_by = %s, modified_date = now()
                             WHERE occurrence_id = %s""", (new, n2, TAG, oid))
                if new != st: status_fill[(st, new)] += 1
                ext.append(("OCCURRENCE", oid, SRC, sid, "HIGH", TAG)); stats["LSM attachments"] += 1
                logrows.append((a["sid"], "ATTACH", oid, name, st, new))
            stats["LSM areas attached"] += 1
            continue
    if a["sid"] in DONE: continue
    nm = (near[1] if near and near[3] <= 10000 else None)
    label = "Large-scale mining area" if a["scale"] == "LSM" else "Artisanal/small-scale mining area"
    name = f"{label} near {nm} ({a['sid'].upper()})" if nm else f"{label} {a['sid'].upper()} (Copperbelt)"
    com = " | ".join(x for x in base + [f"Nearest existing occurrence: {near[1]} ({round(near[3])} m)" if near else None,
                                        "Status PRODUCER = active mining seen on the imagery; not a verified operating mine" if a["scale"] == "ASM" else
                                        "Status PRODUCER = active mining seen on the imagery",
                                        f"Source: U.S. Geological Survey (public domain). Load tag {TAG}"] if x)
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, comments,
                 is_active, created_by, created_date, position_accuracy) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),'PRODUCER','UNKNOWN',%s,%s,
                 true,%s,now(),'AREA_CENTROID') RETURNING occurrence_id""",
              (name[:300], a["scale"] == "LSM", JI.get(iso), lon, lat,
               "Large-scale mining area" if a["scale"] == "LSM" else "Artisanal and small-scale mining", com, TAG))
    oid = c.fetchone()[0]
    for x in cuco: links.append((oid, CID[x], "SECONDARY", True, TAG))
    ext.append(("OCCURRENCE", oid, SRC, a["sid"], "EXACT", TAG)); stats[f"{a['scale']} new"] += 1
    if not iso: stats["new without country"] += 1
    logrows.append((a["sid"], "NEW", oid, name, None, "PRODUCER"))

if links:
    execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links)
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s", ext)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'U.S. Geological Survey',%s,'U.S. Government work (public domain); metadata use constraints: None',
                     'https://doi.org/10.5066/P9LWU4FT', true, %s, true, %s, %s, %s, '2026-11-10', true, %s, now())
             ON CONFLICT DO NOTHING""",
          (SRC, "A database of artisanal, small-scale, and large-scale mining in the Copperbelt region of the DRC and Zambia (2024)",
           "Source: U.S. Geological Survey, Boston and Alessi (2024), doi:10.5066/P9LWU4FT.",
           "Cleared: USGS data release, FGDC metadata access and use constraints 'None' (checked 2026-11-10). Loaded 2026-11-10.",
           "Mining areas = merged 1 km grid cells with active mining on 2019-2023 imagery; points are area centroids; commodities are POSSIBLE "
           "(copied from DRC 2016 / Zambia 2023 cadastre licences), only Cu/Co linked; ASM status PRODUCER means mining seen, not a verified operation. "
           "Built partly from Maxar imagery and the DRC/Zambia cadastre portals (confirmation email to USGS drafted, optional).",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/USGS_COPPERBELT_ASM", TAG))

log("stats", dict(stats))
log("status filled on attached occurrences", dict(status_fill))
log("commodity links", collections.Counter(x[1] for x in links))
one = lambda s, p=None: (c.execute(s, p), c.fetchall())[1]
log("new by country", one("""SELECT country_name, workings_type, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1, 2 ORDER BY 1, 2""", (TAG,)))
log("ext ids", one("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,)))
log("sample LSM attachments", [r for r in logrows if r[1] == "ATTACH"][:12])
log("sample new", [r[3] for r in logrows if r[1] == "NEW"][:12])
with open(os.path.join(HERE, f"log_{TAG}.csv"), "w", encoding="utf-8") as fh:
    fh.write("area,action,occurrence_id,name,old_status,new_status\n")
    for r in logrows: fh.write(",".join('"' + str(x).replace('"', "'") + '"' for x in r) + "\n")
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
