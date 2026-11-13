"""Sample catchment basins for stream-sediment samples (pilot: GEUS stream sediments, South Greenland).

A stream-sediment sample represents the ground draining to it, not a point. This script gives every sample its own catchment:
the area that drains to the sample's position on the stream network, minus the area that drains to the next sample upstream
(so the catchments form a patchwork with no overlaps: "sample catchment basins"). Ice-sheet and glacier ground is cut out of the
polygons (it contributes meltwater, not local bedrock detritus) and its share is recorded.

Inputs (downloaded 2026-11-13 with the user's approval, kept in catchments/data, not committed):
  - Copernicus DEM GLO-90 tiles (data/dem/*.tif): free for any use incl. commercial; credit "Copernicus DEM GLO-90 (c) DLR e.V. 2010-2014
    and (c) Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA".
  - ESA WorldCover 2021 v200 tiles (data/worldcover/*.tif), CC BY 4.0: class 70 = snow and ice, 80 = permanent water.
  - Sample positions from interzona_cm (geochem.samples, read role).

Method (all on a 90 m grid in UTM zone 23N, EPSG:32623):
  1. Mosaic + reproject the DEM; ocean = no data or elevation <= 1 m.
  2. Priority-flood fill with a tiny gradient on flats (Barnes et al. 2014), so every land cell drains to the sea.
  3. D8 steepest-descent receivers on the filled surface; flow accumulation in drainage order.
  4. Each sample is moved to the nearest stream cell (>= ~0.1 km2 upstream) within SNAP_M metres, else the cell with most flow.
  5. Labels propagate upstream from each snapped point until they meet the next sample's catchment.
  6. Polygons (ice cells removed) are simplified and written as GeoJSON + CSV for checking; load_catchments.py writes them to the DB.

Usage: python build_catchments.py [--region south_greenland]
"""
import heapq
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import psycopg2
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from pyproj import Transformer
from shapely.geometry import shape, mapping, MultiPolygon, Polygon
from shapely.ops import unary_union, transform as shp_transform
from shapely.validation import make_valid

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "out"
CELL = 90.0  # m
DST_CRS = "EPSG:32623"
SNAP_M = 270.0  # search radius for the stream cell (3 cells)
MIN_STREAM_CELLS = 12  # about 0.1 km2 draining to a cell before it counts as a stream
SIMPLIFY_M = 45.0
REGIONS = {
    # DEM extent (lon/lat) and the sample box inside it (a margin so most catchments are not cut by the grid edge)
    "south_greenland": {"dem": (-51.0, 59.0, -43.0, 62.0), "samples": (-50.6, 59.6, -43.2, 61.85), "source": "GREENLAND_GEUS"},
}
STREAM_SEDIMENT_TYPE_ID = 19


def env():
    e = {}
    for line in open(r"C:\Users\dean\critical-minerals-ai\.env.local", encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"')
    return e


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:7.1f}s] {msg}", flush=True)


def target_grid(lonlat_box):
    w, s, e, n = transform_bounds("EPSG:4326", DST_CRS, *lonlat_box, densify_pts=50)
    w, s = math.floor(w / CELL) * CELL, math.floor(s / CELL) * CELL
    e, n = math.ceil(e / CELL) * CELL, math.ceil(n / CELL) * CELL
    ncols, nrows = int((e - w) / CELL), int((n - s) / CELL)
    return from_origin(w, n, CELL, CELL), nrows, ncols


def load_dem(tf, nrows, ncols):
    srcs = [rasterio.open(p) for p in sorted((DATA / "dem").glob("*.tif"))]
    mosaic, mtf = merge(srcs, nodata=-9999.0)
    crs = srcs[0].crs
    for s in srcs:
        s.close()
    dem = np.full((nrows, ncols), -9999.0, dtype=np.float32)
    reproject(mosaic[0].astype(np.float32), dem, src_transform=mtf, src_crs=crs, src_nodata=-9999.0,
              dst_transform=tf, dst_crs=DST_CRS, dst_nodata=-9999.0, resampling=Resampling.bilinear)
    return dem


def load_worldcover(tf, nrows, ncols):
    lc = np.zeros((nrows, ncols), dtype=np.uint8)
    for p in sorted((DATA / "worldcover").glob("*.tif")):
        with rasterio.open(p) as src:
            part = np.zeros((nrows, ncols), dtype=np.uint8)
            reproject(rasterio.band(src, 1), part, dst_transform=tf, dst_crs=DST_CRS, dst_nodata=0, resampling=Resampling.mode)
            lc = np.where(part > 0, part, lc)
    return lc


def priority_flood(z, ocean):
    """Fill depressions (with a tiny gradient across flats) so that every land cell has a strictly lower path to the sea.
    z and ocean are padded 2-D arrays (outer ring = ocean). Returns the filled surface (float64, ocean = -1e9)."""
    nr, nc = z.shape
    zf = z.astype(np.float64).ravel().copy()
    oc = ocean.ravel()
    seen = oc.copy()
    offs = (-nc - 1, -nc, -nc + 1, -1, 1, nc - 1, nc, nc + 1)
    # Seeds: land cells touching the ocean (or the grid edge, which is ocean after padding).
    land = ~ocean
    touch = np.zeros_like(ocean)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                touch |= np.roll(np.roll(ocean, dr, 0), dc, 1)
    seeds = np.flatnonzero((land & touch).ravel())
    heap = [(float(zf[i]), int(i)) for i in seeds]
    heapq.heapify(heap)
    seen[seeds] = True
    pop, push = heapq.heappop, heapq.heappush
    eps = 1e-4
    n = 0
    while heap:
        zc, c = pop(heap)
        n += 1
        for o in offs:
            m = c + o
            if seen[m]:
                continue
            seen[m] = True
            zm = zf[m]
            if zm <= zc:
                zm = zc + eps
                zf[m] = zm
            push(heap, (zm, m))
    zf[oc] = -1e9
    return zf.reshape(nr, nc), n


def d8_receivers(zf):
    """Steepest-descent receiver (flat index, -1 = drains straight to the sea or nowhere) on the filled, padded surface."""
    nr, nc = zf.shape
    best = np.zeros((nr, nc))
    recv = np.full(nr * nc, -1, dtype=np.int64)
    idx = np.arange(nr * nc).reshape(nr, nc)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if not (dr or dc):
                continue
            nb = np.roll(np.roll(zf, -dr, 0), -dc, 1)  # neighbour at (r+dr, c+dc)
            drop = (zf - nb) / (math.sqrt(2) if dr and dc else 1.0)
            better = drop > best
            best = np.where(better, drop, best)
            nbi = np.roll(np.roll(idx, -dr, 0), -dc, 1)
            recv = np.where(better.ravel(), nbi.ravel(), recv)
    return recv


def main():
    region = REGIONS[sys.argv[sys.argv.index("--region") + 1] if "--region" in sys.argv else "south_greenland"]
    OUT.mkdir(exist_ok=True)
    tf, nrows, ncols = target_grid(region["dem"])
    log(f"grid {nrows} x {ncols} at {CELL:.0f} m")
    dem = load_dem(tf, nrows, ncols)
    log(f"DEM loaded: min {dem[dem > -9000].min():.1f} max {dem.max():.1f}")
    lc = load_worldcover(tf, nrows, ncols)
    ice = lc == 70
    log(f"WorldCover loaded: ice {ice.mean():.1%}, water {(lc == 80).mean():.1%}, no data {(lc == 0).mean():.1%}")

    ocean = (dem <= 1.0) | (dem <= -9000)
    # Pad with an ocean ring so neighbour offsets never leave the array.
    P = lambda a, v: np.pad(a, 1, constant_values=v)
    zp, op, icep = P(dem, -9999.0), P(ocean, True), P(ice, False)
    nr, nc = zp.shape
    log(f"land cells {(~op).sum():,}")
    zf, n = priority_flood(zp, op)
    log(f"priority flood done ({n:,} cells)")
    recv = d8_receivers(zf)
    land = ~op.ravel()
    recv[~land] = -1
    order = np.flatnonzero(land)[np.argsort(-zf.ravel()[land], kind="stable")]  # upstream first
    acc = np.where(land, 1.0, 0.0)
    rv = recv
    for c in order:
        r = rv[c]
        if r >= 0:
            acc[r] += acc[c]
    log("flow accumulation done")

    # Samples
    e = env()
    conn = psycopg2.connect(host=e["PGHOST"], port=e.get("PGPORT", 5432), dbname=e["PGDATABASE"], user=e["PGUSER"], password=e["PGPASSWORD"], sslmode="require")
    w, s, ee, nn = region["samples"]
    with conn, conn.cursor() as cur:
        cur.execute("""SELECT sample_id, lon, lat FROM geochem.samples WHERE source_system = %s AND sample_type_id = %s AND is_active
                       AND lon BETWEEN %s AND %s AND lat BETWEEN %s AND %s""", (region["source"], STREAM_SEDIMENT_TYPE_ID, w, ee, s, nn))
        samples = cur.fetchall()
    conn.close()
    log(f"{len(samples):,} samples")
    to_utm = Transformer.from_crs("EPSG:4326", DST_CRS, always_xy=True)
    to_ll = Transformer.from_crs(DST_CRS, "EPSG:4326", always_xy=True)
    inv = ~tf
    rad = int(round(SNAP_M / CELL))
    pour_of_cell = {}
    snapped = []
    for sid, lon, lat in samples:
        x, y = to_utm.transform(lon, lat)
        col, row = inv * (x, y)
        r0, c0 = int(row) + 1, int(col) + 1  # +1 for the padding
        # The nearest stream cell (at least MIN_STREAM_CELLS upstream); if there is none within reach, the cell with the most flow.
        # Taking the most flow everywhere would pull samples from the small tributary they were taken from onto a bigger river nearby.
        best_d, bi, best_acc, bi_acc = 1e18, -1, -1.0, -1
        for dr in range(-rad, rad + 1):
            for dc in range(-rad, rad + 1):
                if dr * dr + dc * dc > rad * rad:
                    continue
                rr, cc = r0 + dr, c0 + dc
                if 0 < rr < nr - 1 and 0 < cc < nc - 1:
                    i = rr * nc + cc
                    if not land[i]:
                        continue
                    if acc[i] > best_acc:
                        best_acc, bi_acc = acc[i], i
                    if acc[i] >= MIN_STREAM_CELLS:
                        cx, cy = tf * (cc - 1 + 0.5, rr - 1 + 0.5)
                        d = (cx - x) ** 2 + (cy - y) ** 2
                        if d < best_d:
                            best_d, bi = d, i
        if bi < 0:
            bi = bi_acc
        if bi < 0:
            snapped.append((sid, lon, lat, None))
            continue
        pour_of_cell.setdefault(bi, []).append(sid)
        rr, cc = divmod(bi, nc)
        px, py = tf * (cc - 1 + 0.5, rr - 1 + 0.5)
        snapped.append((sid, lon, lat, (bi, math.hypot(px - x, py - y))))
    pours = list(pour_of_cell.keys())
    log(f"snapped {sum(1 for s_ in snapped if s_[3]):,} samples to {len(pours):,} stream cells; {sum(1 for s_ in snapped if not s_[3])} not on land")

    # Labels: each pour cell gets its own id; cells inherit the label of their receiver, processed downstream first.
    lab = np.zeros(nr * nc, dtype=np.int32)
    for k, c in enumerate(pours, start=1):
        lab[c] = k
    for c in order[::-1]:
        if lab[c] == 0:
            r = rv[c]
            if r >= 0:
                lab[c] = lab[r]
    log("labels done")
    parent = {k: int(lab[rv[c]]) if rv[c] >= 0 else 0 for k, c in enumerate(pours, start=1)}  # next sample catchment downstream
    n_up = {k: 0 for k in parent}
    for k in parent:
        p = parent[k]
        seen_ = set()
        while p and p not in seen_:
            seen_.add(p)
            n_up[p] += 1
            p = parent[p]
    lab2 = lab.reshape(nr, nc)[1:-1, 1:-1]
    icel = ice
    cells = np.bincount(lab2.ravel(), minlength=len(pours) + 1)
    ice_cells = np.bincount(lab2[icel].ravel(), minlength=len(pours) + 1)
    edge = set(np.unique(np.concatenate([lab2[0], lab2[-1], lab2[:, 0], lab2[:, -1]])).tolist()) - {0}

    # Polygons of the ice-free part of each catchment.
    poly_lab = np.where(icel, 0, lab2).astype(np.int32)
    parts = {}
    for geom, val in shapes(poly_lab, mask=poly_lab > 0, transform=tf, connectivity=8):
        parts.setdefault(int(val), []).append(shape(geom))
    log("polygonized")
    snap_of = {s_[0]: s_[3][1] for s_ in snapped if s_[3]}
    rows = []
    cell_km2 = CELL * CELL / 1e6
    for k, c in enumerate(pours, start=1):
        geom = unary_union(parts.get(k, [])) if parts.get(k) else None
        if geom is not None and not geom.is_empty:
            geom = make_valid(geom.simplify(SIMPLIFY_M, preserve_topology=True))  # 8-connected raster outlines can self-touch
            if geom.geom_type == "GeometryCollection":
                geom = unary_union([g_ for g_ in geom.geoms if g_.geom_type in ("Polygon", "MultiPolygon")])
            geom = shp_transform(lambda x, y, z=None: to_ll.transform(x, y), geom)
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])
        rr, cc = divmod(c, nc)
        plon, plat = to_ll.transform(*(tf * (cc - 1 + 0.5, rr - 1 + 0.5)))
        info = {
            "own_km2": round(cells[k] * cell_km2, 3), "ice_share": round(ice_cells[k] / max(cells[k], 1), 3),
            "upstream_km2": round(acc[c] * cell_km2, 3), "upstream_samples": n_up[k], "edge": k in edge,
            "pour_lon": round(plon, 6), "pour_lat": round(plat, 6), "downstream_pour": parent[k],
        }
        for sid in pour_of_cell[c]:
            rows.append({"sample_id": sid, "pour": k, "snap_m": round(snap_of[sid], 1), **info, "geom": geom})
    with open(OUT / "catchments_south_greenland.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {k: v for k, v in r.items() if k != "geom"}, "geometry": mapping(r["geom"]) if r["geom"] else None}
            for r in rows]}, f)
    own = np.array([r["own_km2"] for r in rows]); up = np.array([r["upstream_km2"] for r in rows])
    snapd = np.array([r["snap_m"] for r in rows])
    log(f"wrote {len(rows):,} sample catchments; own area km2 median {np.median(own):.2f} p90 {np.percentile(own, 90):.1f} max {own.max():.0f}; "
        f"upstream km2 median {np.median(up):.2f}; snap m median {np.median(snapd):.0f} p90 {np.percentile(snapd, 90):.0f}; "
        f"tiny (<0.1 km2 upstream) {(up < 0.1).sum()}; ice share >50% {sum(r['ice_share'] > 0.5 for r in rows)}; touching grid edge {sum(r['edge'] for r in rows)}; "
        f"no polygon {sum(r['geom'] is None for r in rows)}")


if __name__ == "__main__":
    main()
