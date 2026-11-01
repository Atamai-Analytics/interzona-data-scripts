#!/usr/bin/env python3
"""Read-only survey: where else do `locations.divisionid` values look wrong or missing, the way Finland's Lapland was?
Cells (0.01 deg) of all locations are matched to geoBoundaries CGAZ ADM1 polygons. Two symptoms are reported:
  A. a division whose locations are spread over unrelated polygons (the dominant polygon holds < 85 % of its locations)
  B. a polygon holding many locations with divisionid NULL
"""
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad")
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 40)


def main():
    cells = pd.read_csv(SP / "cells.csv")
    divs = pd.read_csv(SP / "divisions_all.csv").set_index("divisionid")
    ctry = pd.read_csv(SP / "countries.csv").set_index("countryid")["countryname"].to_dict()
    print("cells:", len(cells), "locations:", int(cells.n.sum()))
    pts = gpd.GeoDataFrame(cells, geometry=gpd.points_from_xy(cells.lon, cells.lat), crs="EPSG:4326")
    poly = gpd.read_file(SHP, engine="pyogrio")[["shapeName", "shapeGroup", "geometry"]]
    print("polygons:", len(poly))
    j = gpd.sjoin(pts, poly, how="left", predicate="within")
    # a cell on a shared border may match twice: keep the first
    j = j.drop_duplicates(subset=["countryid", "divisionid", "lat", "lon"], keep="first")
    j["poly"] = j.shapeGroup.fillna("-") + "/" + j.shapeName.fillna("(no polygon)")
    j["country"] = j.countryid.map(ctry)
    j["divname"] = j.divisionid.map(lambda d: divs.divisionname.get(int(d)) if pd.notna(d) else None)
    j["divcode"] = j.divisionid.map(lambda d: divs.divisioncode.get(int(d)) if pd.notna(d) else None)

    # --- A. divisions spread over several polygons
    nz = j[j.divisionid.notna()]
    tot = nz.groupby("divisionid").n.sum()
    per = nz.groupby(["divisionid", "poly"]).n.sum().reset_index()
    dom = per.sort_values("n", ascending=False).drop_duplicates("divisionid").set_index("divisionid")
    rep = pd.DataFrame({"total": tot, "dominant_poly": dom.poly, "dominant_n": dom.n})
    rep["share"] = rep.dominant_n / rep.total
    rep["misfiled"] = rep.total - rep.dominant_n
    rep["division"] = [f"{divs.divisioncode.get(int(i))} {divs.divisionname.get(int(i))}" for i in rep.index]
    rep["country"] = [ctry.get(int(divs.countryid.get(int(i)))) for i in rep.index]
    sus = rep[(rep.total >= 200) & (rep.share < 0.85)].sort_values("misfiled", ascending=False)
    print(f"\n== A. divisions whose locations are spread over unrelated polygons (share of dominant polygon < 85 %, total >= 200): {len(sus)} of {len(rep)}")
    print(sus[["country", "division", "total", "share", "dominant_poly", "misfiled"]].head(30).to_string(float_format=lambda x: f"{x:.2f}"))
    # for the worst ones, where do the misfiled locations actually sit?
    for i in sus.index[:6]:
        sub = per[per.divisionid == i].sort_values("n", ascending=False).head(6)
        print(f"   {rep.division[i]} ({rep.country[i]}): " + "; ".join(f"{r.poly} {int(r.n):,}" for r in sub.itertuples()))

    # --- B. polygons with many NULL-division locations
    nul = j[j.divisionid.isna()].groupby(["country", "poly"]).n.sum().reset_index().sort_values("n", ascending=False)
    allp = j.groupby(["country", "poly"]).n.sum().rename("all_n").reset_index()
    nul = nul.merge(allp, on=["country", "poly"])
    print("\n== B. polygons with the most locations that have NO division (top 25):")
    print(nul.head(25).to_string(index=False))
    print("\nNULL-division locations by country (top 12):")
    print(j[j.divisionid.isna()].groupby("country").n.sum().sort_values(ascending=False).head(12).to_string())
    sus.to_csv(SP / "division_survey_suspicious.csv")
    nul.to_csv(SP / "division_survey_null_polygons.csv", index=False)


if __name__ == "__main__":
    main()
