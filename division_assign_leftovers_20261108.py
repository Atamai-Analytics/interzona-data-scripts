#!/usr/bin/env python3
"""Assign a division to the remaining scattered locations with divisionid NULL (criticialmineralsexp), 2026-11-08.

Same mapping as division_assign_build.py (CGAZ ADM1 polygon -> the division the DB already uses for it: >= 90 % share of >= 20 assigned
locations, same country) plus the 'clearly nearest' rule used for the Greenland / Sweden / China follow-ups: a point outside every polygon
takes the nearest polygon of ITS OWN COUNTRY within 50 km when the runner-up polygon is >= 5 km farther or >= 2x farther.
Excluded on purpose: Antarctica (no divisions), and the locations already reviewed as ambiguous (greenland_division_review_ambiguous.csv,
china_division_review_leftovers.csv, sweden_division_review_leftovers.csv, finland_skerry_division_review_leftovers.csv).
Fallback mapping when a polygon has no learned division: a division of the same country whose name equals the polygon name.
Writes division_leftovers_plan_<ts>.csv (locationid, country, polygon, divisionid, distance_m, rule); with --apply updates locations in one
transaction after writing finland_fix_backups/locations_divisionid_before_leftover_fix_<ts>.csv.
"""
import os, sys, datetime, unicodedata
from pathlib import Path
import geopandas as gpd, numpy as np, pandas as pd, psycopg2
from pyproj import Geod

APPLY = "--apply" in sys.argv
HERE = Path(__file__).parent
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
ENV = {}
for l in open(HERE / ".env", encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
con = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="criticialmineralsexp", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
q = lambda s: pd.read_sql(s, con)
nul = q("""SELECT l.locationid, l.latitude AS lat, l.longitude AS lon, l.countryid, c.countryname, c.countrycode3 FROM locations l
           JOIN countries c ON c.countryid = l.countryid WHERE l.divisionid IS NULL AND l.latitude IS NOT NULL AND l.longitude IS NOT NULL""")
skip = set()
for f in ("greenland_division_review_ambiguous.csv", "china_division_review_leftovers.csv", "sweden_division_review_leftovers.csv",
          "finland_skerry_division_review_leftovers.csv"):
    p = HERE / f
    if p.exists():
        d = pd.read_csv(p); col = [c for c in d.columns if c.lower() == "locationid"][0]; skip |= set(d[col].astype(int))
nul = nul[(nul.countryname != "Antarctica") & (~nul.locationid.isin(skip))].copy()
print("candidates", len(nul), "| excluded reviewed", len(skip))
cells = q("""SELECT round(latitude::numeric, 2)::float AS lat, round(longitude::numeric, 2)::float AS lon, divisionid, count(*) AS n
             FROM locations WHERE divisionid IS NOT NULL AND latitude IS NOT NULL GROUP BY 1, 2, 3""")
divs = q("SELECT divisionid, countryid, divisionname FROM divisions")
dv_country = divs.set_index("divisionid").countryid.to_dict()
poly = gpd.read_file(SHP, engine="pyogrio")[["shapeName", "shapeGroup", "geometry"]].reset_index(drop=True); poly["pid"] = poly.index
pts = gpd.GeoDataFrame(cells, geometry=gpd.points_from_xy(cells.lon, cells.lat), crs=4326)
j = gpd.sjoin(pts, poly[["pid", "geometry"]], how="inner", predicate="within")
per = j.groupby(["pid", "divisionid"]).n.sum().reset_index(); tot = per.groupby("pid").n.sum().rename("tot")
top = per.sort_values("n", ascending=False).drop_duplicates("pid").set_index("pid").join(tot); top["share"] = top.n / top.tot
learned = top[(top.share >= 0.9) & (top.tot >= 20)].divisionid.astype(int).to_dict()
fold = lambda s: unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().replace(" province", "").replace(" region", "").strip()
byname = {(r.countryid, fold(r.divisionname)): r.divisionid for r in divs.itertuples()}

geod = Geod(ellps="WGS84")
P = gpd.GeoDataFrame(nul, geometry=gpd.points_from_xy(nul.lon, nul.lat), crs=4326)
inside = gpd.sjoin(P, poly[["pid", "shapeGroup", "geometry"]], how="left", predicate="within")
plan, why = [], {}
for r in inside.itertuples():
    cands = []
    if not np.isnan(r.pid):
        cands = [(int(r.pid), 0.0)]; rule = "inside"
    else:
        same = poly[poly.shapeGroup == r.countrycode3]
        if len(same) == 0: why[r.locationid] = "no polygons for country"; continue
        dists = []
        for p in same.itertuples():
            from shapely.ops import nearest_points
            a, b = nearest_points(r.geometry, p.geometry)
            dists.append((p.pid, geod.inv(a.x, a.y, b.x, b.y)[2]))
        dists.sort(key=lambda x: x[1])
        best = dists[0]; runner = dists[1][1] if len(dists) > 1 else float("inf")
        if best[1] > 50000: why[r.locationid] = "nearest polygon > 50 km"; continue
        if not (runner - best[1] >= 5000 or runner >= 2 * best[1]): why[r.locationid] = "ambiguous nearest"; continue
        cands = [best]; rule = "clearly nearest"
    pid, d = cands[0]
    dv = learned.get(pid)
    if dv is None:
        dv = byname.get((r.countryid, fold(poly.loc[pid, "shapeName"])))
        if dv is not None: rule += " + name match"
    if dv is None or dv_country.get(dv) != r.countryid: why[r.locationid] = "no confident division for polygon"; continue
    plan.append((r.locationid, r.countryname, poly.loc[pid, "shapeName"], dv, round(d), rule))
plan = pd.DataFrame(plan, columns=["locationid", "country", "polygon", "divisionid", "distance_m", "rule"])
out = HERE / f"division_leftovers_plan_{STAMP}.csv"; plan.to_csv(out, index=False)
print("assignable", len(plan), "| by rule", plan.rule.value_counts().to_dict())
print("not assigned", len(why), pd.Series(why).value_counts().to_dict())
print(plan.groupby("country").size().sort_values(ascending=False).head(15).to_dict())
if APPLY and len(plan):
    bk = HERE / "finland_fix_backups" / f"locations_divisionid_before_leftover_fix_{STAMP}.csv"
    plan.assign(old_divisionid=None)[["locationid", "old_divisionid"]].to_csv(bk, index=False)
    cur = con.cursor()
    for r in plan.itertuples():
        cur.execute("UPDATE locations SET divisionid = %s WHERE locationid = %s AND divisionid IS NULL", (int(r.divisionid), int(r.locationid)))
    con.commit(); print("APPLIED", len(plan), "backup", bk)
