#!/usr/bin/env python3
"""Build the list of divisionid assignments for locations that have none (read-only; writes CSVs to the scratchpad).

For every location with divisionid NULL:
  1. find the geoBoundaries CGAZ ADM1 polygon it lies in; if none, the nearest polygon within MAX_EDGE_M (geodesic metres);
  2. map the polygon to the division the DATABASE ALREADY USES for that polygon: the dominant divisionid of the already-assigned
     locations inside it (>= 90 % share, >= 20 locations, division belongs to the same country as the location), or - for polygons
     with no assigned locations - an explicit override (China provinces, checked by name);
  3. skip (and list) everything else: Antarctica, Finland leftovers (ambiguous Aland/Finland Proper), no polygon within range,
     polygon without a confident division, or a division from a different country than the location's.
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely.ops import nearest_points

SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad")
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
MAX_EDGE_M = 2000.0
# polygons that have no already-assigned locations to learn from: (shapeGroup, shapeName) -> division code (China, checked against names)
OVERRIDES = {
    ("CHN", "Xinjiang Uyghur Autonomous Region"): "CN-XJ",
    ("NOR", "Troms og Finnmark"): "NO-54",
    ("CHN", "Inner Mongolia Autonomous Region"): "CN-NM",
    ("CHN", "Tibet Autonomous Region"): "CN-XZ",
    ("CHN", "Guangxi Zhuang Autonomous Region"): "CN-GX",
    ("CHN", "Guangzhou Province"): "CN-GD",          # CGAZ's label for GUANGDONG: polygon bounds lon 109.7-117.2, lat 21.0-25.6 (checked) - not Guizhou
    ("CHN", "Ningxia Ningxia Hui Autonomous Region"): "CN-NX",
}
SKIP_COUNTRIES = {"Antarctica"}


def main():
    nul = pd.read_csv(SP / "null_locations.csv")
    cells = pd.read_csv(SP / "cells.csv")
    divs = pd.read_csv(SP / "divisions_all.csv")
    ctry = pd.read_csv(SP / "countries.csv").set_index("countryid")["countryname"].to_dict()
    dv_country = divs.set_index("divisionid").countryid.to_dict()
    code_to_id = {(r.countryid, r.divisioncode): r.divisionid for r in divs.itertuples()}
    poly = gpd.read_file(SHP, engine="pyogrio")[["shapeName", "shapeGroup", "geometry"]].reset_index(drop=True)
    poly["pid"] = poly.index

    # ---- polygon -> division mapping learned from assigned locations
    ass = cells[cells.divisionid.notna()]
    pts = gpd.GeoDataFrame(ass, geometry=gpd.points_from_xy(ass.lon, ass.lat), crs=4326)
    j = gpd.sjoin(pts, poly[["pid", "geometry"]], how="inner", predicate="within")
    per = j.groupby(["pid", "divisionid"]).n.sum().reset_index()
    tot = per.groupby("pid").n.sum().rename("tot")
    top = per.sort_values("n", ascending=False).drop_duplicates("pid").set_index("pid").join(tot)
    top["share"] = top.n / top.tot
    learned = top[(top.share >= 0.9) & (top.tot >= 20)].divisionid.astype(int).to_dict()
    print(f"polygons with a learned division: {len(learned)} of {len(poly)}")
    pid_by_name = {(r.shapeGroup, r.shapeName): r.pid for r in poly.itertuples()}
    for key, code in OVERRIDES.items():
        pid = pid_by_name[key]
        cname = {"CHN": "China", "NOR": "Norway"}[key[0]]
        cid = [c for c, n in ctry.items() if n == cname][0]
        did = code_to_id[(cid, code)]
        if pid in learned and learned[pid] != did:
            print("  WARNING override conflicts with learned mapping:", key, learned[pid], did)
        learned.setdefault(pid, did)
        b = poly.loc[pid, "geometry"].bounds
        print(f"  override {key[1]!r} -> {code} (divisionid {did}); polygon bounds lon {b[0]:.1f}..{b[2]:.1f}, lat {b[1]:.1f}..{b[3]:.1f}")

    # ---- locate every NULL location
    g = gpd.GeoDataFrame(nul, geometry=gpd.points_from_xy(nul.longitude, nul.latitude), crs=4326)
    w = gpd.sjoin(g, poly[["pid", "geometry"]], how="left", predicate="within").drop_duplicates("locationid")
    w["how"] = np.where(w.pid.notna(), "within", None)
    out = w[w.pid.isna()].copy()
    if len(out):
        # nearest polygon (ranked in a metric CRS) then the true geodesic distance to its nearest boundary point
        geod = Geod(ellps="WGS84")
        g3857 = out[["locationid", "geometry"]].set_geometry("geometry").to_crs(3857)
        p3857 = poly[["pid", "geometry"]].to_crs(3857)
        nn = gpd.sjoin_nearest(g3857, p3857, how="left").drop_duplicates("locationid").set_index("locationid")
        dist, pids = {}, {}
        for r in out.itertuples():
            pid = int(nn.loc[r.locationid, "pid"])
            _, q = nearest_points(r.geometry, poly.loc[pid, "geometry"])
            dist[r.locationid] = geod.inv(r.longitude, r.latitude, q.x, q.y)[2]
            pids[r.locationid] = pid
        w.loc[out.index, "pid"] = out.locationid.map(pids)
        w.loc[out.index, "edge_m"] = out.locationid.map(dist)
        w.loc[out.index, "how"] = "nearest"
    w["edge_m"] = w.get("edge_m", np.nan)

    def decide(r):
        cn = ctry.get(int(r.countryid))
        if cn in SKIP_COUNTRIES:
            return None, "skipped_country"
        if cn == "Finland":
            return None, "finland_left_for_review"
        if pd.isna(r.pid):
            return None, "no_polygon"
        if r.how == "nearest" and not (r.edge_m <= MAX_EDGE_M):
            return None, f"nearest_polygon_farther_than_{int(MAX_EDGE_M)}m"
        did = learned.get(int(r.pid))
        if did is None:
            return None, "polygon_without_confident_division"
        if dv_country.get(did) != r.countryid:
            return None, "division_belongs_to_other_country"
        return did, "ok_" + r.how

    res = w.apply(decide, axis=1, result_type="expand")
    w["new_divisionid"], w["reason"] = res[0], res[1]
    w["country"] = w.countryid.map(ctry)
    w["polygon"] = w.pid.map(lambda p: f"{poly.loc[int(p), 'shapeGroup']}/{poly.loc[int(p), 'shapeName']}" if pd.notna(p) else None)
    ok = w[w.new_divisionid.notna()]
    print("\nassignments:", len(ok), "of", len(w), "NULL locations")
    print(pd.crosstab(w.country, w.reason).loc[lambda t: t.sum(axis=1) > 0].sort_values("ok_within", ascending=False).head(25).to_string())
    ok[["locationid", "countryid", "new_divisionid", "reason"]].assign(new_divisionid=lambda d: d.new_divisionid.astype(int)).to_csv(SP / "division_assign.csv", index=False)
    w[w.new_divisionid.isna()].drop(columns="geometry").to_csv(SP / "division_assign_leftovers.csv", index=False)
    print("\nper-division assignments (top 25):")
    names = divs.set_index("divisionid").divisionname.to_dict()
    print(ok.groupby("new_divisionid").size().sort_values(ascending=False).head(25).rename(index=lambda i: f"{int(i)} {names[int(i)]}").to_string())
    print("\nnearest-polygon edge distances (assigned): max %.0f m, median %.0f m" % (ok.edge_m.max(), ok.edge_m.median()) if ok.edge_m.notna().any() else "")
    lo = w[(w.reason.str.startswith("nearest_polygon_farther"))]
    if len(lo):
        print(f"edge points beyond {MAX_EDGE_M:.0f} m (left unassigned): {len(lo)}; by country:", lo.country.value_counts().head(6).to_dict(),
              "| distance quantiles m:", {q: int(lo.edge_m.quantile(q)) for q in (0.1, 0.5, 0.9)})


if __name__ == "__main__":
    main()
