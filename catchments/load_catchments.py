"""Load sample catchment basins built by build_catchments.py into geochem.sample_catchments (the LITHODAT admin loader connection
from lithosurfer-work/.env, as for every geochem write; the app's write role has no access to the geochem schema).

Replaces every row of the given region (rollback = delete the region's rows; the table holds nothing else).
Usage: python load_catchments.py [--region south_greenland] [--dry-run]
"""
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from build_catchments import OUT, REGIONS

METHOD = "Copernicus DEM GLO-90 reprojected to 90 m UTM 23N; priority-flood fill + D8; snap to the nearest stream cell (>= 0.1 km2 upstream) within 270 m, else max flow; ice (ESA WorldCover 2021 class 70) removed; simplified 45 m"


def main():
    region = sys.argv[sys.argv.index("--region") + 1] if "--region" in sys.argv else "south_greenland"
    src = REGIONS[region]["source"]
    fc = json.load(open(OUT / f"catchments_{region}.geojson", encoding="utf-8"))
    rows = []
    for f in fc["features"]:
        p = f["properties"]
        g = json.dumps(f["geometry"]) if f["geometry"] else None
        rows.append((p["sample_id"], src, region, g, p["pour"], p["pour_lon"], p["pour_lat"], p["snap_m"], p["own_km2"], p["upstream_km2"],
                     p["ice_share"], p["upstream_samples"], p["downstream_pour"] or None, p["edge"], METHOD))
    print(f"{len(rows):,} rows; {sum(r[3] is None for r in rows)} without a polygon")
    if "--dry-run" in sys.argv:
        return
    e = {}
    for line in open(Path(__file__).parent.parent / ".env", encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"')
    conn = psycopg2.connect(host=e["LITHODAT_DB_HOST"], port=e["LITHODAT_DB_PORT"], dbname="interzona_cm", user=e["LITHODAT_DB_USER"], password=e["LITHODAT_DB_PASSWORD"])
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM geochem.sample_catchments WHERE source_system = %s AND region = %s", (src, region))
        execute_values(cur, """INSERT INTO geochem.sample_catchments (sample_id, source_system, region, geom, pour_id, pour_lon, pour_lat, snap_m,
              own_area_km2, upstream_area_km2, ice_share, upstream_samples, downstream_pour_id, touches_grid_edge, method) VALUES %s""",
            rows, template="(%s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", page_size=200)
        cur.execute("SELECT count(*), count(geom), round(sum(own_area_km2)::numeric) FROM geochem.sample_catchments WHERE region = %s", (region,))
        print("loaded (rows, with polygon, total own km2):", cur.fetchone())
    conn.close()


if __name__ == "__main__":
    main()
