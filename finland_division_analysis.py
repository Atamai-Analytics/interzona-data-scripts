#!/usr/bin/env python3
"""Read-only analysis: are the divisionid values of Finnish locations (countryid 83) in criticialmineralsexp right?
Truth = point-in-polygon against geoBoundaries CGAZ ADM1 (D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1), the layer used for the
earlier divisions work. Compares against the stored divisionid and writes per-location results to the scratchpad."""
import collections
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/39a17559-2b27-4a0d-992d-48fc9b6665db/scratchpad")
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"

# CGAZ shapeName -> divisions.divisionid (None = no such division in the DB yet)
FI_MAP = {
    "Uusimaa": 3264, "Finland Proper": 3368, "Southern Savonia": 3373, "Northern Savonia": 3370, "Tavastia Proper": 3376,
    "Central Finland": 3367, "Pirkanmaa": 2985, "South Ostrobothnia": 3375, "Keski-Pohjanmaa": 1321, "Päijät-Häme": 1982,
    "Lapland": 3450, "Northern Ostrobothnia": 3369, "Kainuu": 2910, "North Karelia": 3371, "Ostrobothnia": 3372,
    "Satakunta": 3253, "South Karelia": 3374, "Kymenlaakso": 3095, "Åland Islands": 1621,
}


def main():
    loc = pd.read_csv(SP / "fi_locations.csv")
    loc["is_rock_loc"] = loc["is_rock_loc"].astype(str).str.lower().isin(["t", "true"])
    div = pd.read_csv(SP / "fi_divisions.csv").set_index("divisionid")
    divname = div["divisionname"].to_dict()
    pts = gpd.GeoDataFrame(loc, geometry=gpd.points_from_xy(loc.longitude, loc.latitude), crs="EPSG:4326")
    poly = gpd.read_file(SHP, bbox=(17.0, 58.0, 35.0, 72.0), engine="pyogrio")
    print("polygons in bbox:", len(poly), dict(poly.shapeGroup.value_counts()))
    j = gpd.sjoin(pts, poly[["shapeName", "shapeGroup", "geometry"]], how="left", predicate="within")
    j = j.drop_duplicates("locationid")                     # a point on a shared border could match two polygons
    print("locations:", len(j), "| in some polygon:", j.shapeGroup.notna().sum())

    def classify(r):
        cur = r.divisionid
        cur = None if pd.isna(cur) else int(cur)
        g = r.shapeGroup
        if pd.isna(g):
            return "outside_all_polygons"
        if g != "FIN":
            return f"in_{g}"
        want = FI_MAP.get(r.shapeName)
        if want is None:
            return "FIN_lapland_no_division_exists" if r.shapeName == "Lapland" else "FIN_unmapped"
        if cur is None:
            return "FIN_division_null_fixable"
        return "FIN_correct" if cur == want else "FIN_wrong"

    j["cls"] = j.apply(classify, axis=1)
    j["expected_divisionid"] = j.shapeName.map(FI_MAP)
    for name, sub in (("ALL Finnish locations", j), ("ROCK locations (locationcode rock_*)", j[j.is_rock_loc])):
        print(f"\n== {name}: {len(sub)}")
        print(sub.cls.value_counts().to_string())
    # what are the wrong ones currently tagged as, per truth region?
    w = j[j.cls == "FIN_wrong"]
    cur_names = w.divisionid.map(lambda d: divname.get(int(d), str(d)))
    print("\nFIN_wrong: current division -> count:")
    print(cur_names.value_counts().head(8).to_string())
    print("\nFIN_wrong: true region -> count:")
    print(w.shapeName.value_counts().to_string())
    lap = j[j.cls == "FIN_lapland_no_division_exists"]
    print("\nLapland points currently tagged:", lap.divisionid.map(lambda d: divname.get(int(d), str(d)) if pd.notna(d) else "NULL").value_counts().to_dict())
    for cls in ("outside_all_polygons", "in_SWE", "in_NOR", "in_RUS", "in_EST"):
        sub = j[j.cls == cls]
        if len(sub):
            print(f"\n{cls}: {len(sub)}; current divisions:", sub.divisionid.map(lambda d: divname.get(int(d), str(d)) if pd.notna(d) else "NULL").value_counts().head(5).to_dict(),
                  "| datasources:", sub.datasource.str[:25].value_counts().head(3).to_dict())
    # by dataset (locationcode prefix)
    j["prefix"] = j.locationcode.str.extract(r"^([A-Za-z]+)")[0]
    print("\nby dataset prefix x class (FIN only):")
    print(pd.crosstab(j.prefix, j.cls).to_string())
    j.drop(columns="geometry").to_csv(SP / "fi_division_analysis.csv", index=False)
    print("\nwrote fi_division_analysis.csv")


if __name__ == "__main__":
    main()
