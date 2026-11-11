"""Builds core.facility_superseded: older-release USGS capacity rows that a 2024 Minerals Yearbook row replaces (same plant, newer figure).
The view core.facility_capacity_published sets is_latest_year = false for these rows. Run after build_facility_clusters.py, after any
facility load and after hide_myb2024.py restore.

An older row (any USGS source except USGS_MYB2024) is superseded by a 2024 'anchor' row (USGS_MYB2024, not placed only at a town point) when
  - same commodity (case-insensitive), and
  - compatible stage: same stage_group; or one side is the generic 'Other processing plant' and the other is any non-Mine stage (the older
    Africa release files Mufulira/Nkana/Chambishi smelters and refineries as generic processing plants, the 2024 table names the stage), and
  - same place: same complex in core.facility_site_clusters (sites within ~3 km), or within 10 km when either point is only an
    AREA_CENTROID AND the names share a distinctive word (a town or mine name: 'Plant in Pingluo County' / 'Plant in Pingluo County'; without the name test
    10 km wrongly merged KOV with Kilamusembu and Impala with the Rustenburg plant). Obi Island 'HPAL Plant' vs 'Smelter in Obi island' stays separate.
Older releases never supersede each other. Usage: python build_facility_supersede.py [--dry]
"""
import os, sys, psycopg2

DRY = "--dry" in sys.argv
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
print("superseded rows:", len(rows), "| by complex:", sum(r[2] == 'complex' for r in rows), "| by 10 km area rule:", sum(r[2] != 'complex' for r in rows))
if not DRY:
    c.execute("""CREATE TABLE IF NOT EXISTS core.facility_superseded (facility_capacity_id integer PRIMARY KEY,
                 superseded_by integer NOT NULL, rule text NOT NULL)""")
    c.execute("TRUNCATE core.facility_superseded")
    c.executemany("INSERT INTO core.facility_superseded VALUES (%s, %s, %s)", rows)
    c.execute("GRANT SELECT ON core.facility_superseded TO cm_app_readonly")
    g.commit()
    print("written core.facility_superseded")
g.close()
