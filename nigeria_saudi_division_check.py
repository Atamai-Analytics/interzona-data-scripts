import pandas as pd, geopandas as gpd
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
pd.set_option("display.width", 220)
a = pd.read_csv(SP + "/ngsa_locations.csv")
poly = gpd.read_file(SHP, bbox=(2, 3, 47, 33), engine="pyogrio")
poly = poly[poly.shapeGroup.isin(["NGA", "SAU"])]
g = gpd.GeoDataFrame(a, geometry=gpd.points_from_xy(a.longitude, a.latitude), crs=4326)
j = gpd.sjoin(g, poly[["shapeName", "shapeGroup", "geometry"]], how="left", predicate="within").drop_duplicates("locationid")
j["ds"] = j.datasource.str[:35]
for country, grp in (("Nigeria", "NGA"), ("Saudi Arabia", "SAU")):
    s = j[j.countryname == country]
    print(f"\n===== {country}: {len(s)} locations; datasources {s.ds.value_counts().head(4).to_dict()}")
    ct = pd.crosstab(s.divisionname.fillna("(none)"), s.shapeName.fillna("(no polygon)"))
    # only divisions that are not (almost) entirely inside a single polygon
    for div, row in ct.iterrows():
        tot = row.sum(); top = row.sort_values(ascending=False)
        if top.iloc[0] / tot < 0.95 and tot >= 20:
            print(f"  {div} ({tot}): " + "; ".join(f"{k} {v}" for k, v in top[top > 0].head(6).items()))
    # which datasets/locationcodes hold the mismatches?
    bad = s[(s.divisionname.notna()) & (s.apply(lambda r: isinstance(r.shapeName, str) and r.divisionname.lower().replace(" state", "")[:5] != r.shapeName.lower().replace(" state", "")[:5], axis=1))]
    print(f"  name-mismatch locations: {len(bad)}; by division: {bad.divisionname.value_counts().head(8).to_dict()}")
    print("  by dataset:", bad.ds.value_counts().head(5).to_dict(), "| locationcode prefixes:", bad.locationcode.str.extract(r'^([A-Za-z]+)')[0].value_counts().head(5).to_dict())
j.drop(columns="geometry").to_csv(SP + "/ngsa_check.csv", index=False)
