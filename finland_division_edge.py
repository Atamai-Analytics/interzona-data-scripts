import pandas as pd, geopandas as gpd
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/39a17559-2b27-4a0d-992d-48fc9b6665db/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
a = pd.read_csv(SP + "/fi_division_analysis.csv")
a = a.drop(columns=[c for c in a.columns if c.startswith("index_")])
edge = a[a.cls.isin(["outside_all_polygons", "in_SWE", "in_NOR", "in_RUS"])].copy()
poly = gpd.read_file(SHP, bbox=(17.0, 58.0, 35.0, 72.0), engine="pyogrio")
fin = poly[poly.shapeGroup == "FIN"].to_crs(3067)
pts = gpd.GeoDataFrame(edge, geometry=gpd.points_from_xy(edge.longitude, edge.latitude), crs=4326).to_crs(3067)
nn = gpd.sjoin_nearest(pts, fin[["shapeName", "geometry"]].rename(columns={"shapeName": "nearest_fi"}), how="left", distance_col="dist_m").drop_duplicates("locationid")
bins = [0, 100, 500, 1000, 2000, 5000, 20000, 1e9]
nn["bin"] = pd.cut(nn.dist_m, bins, labels=["<=100 m", "<=500 m", "<=1 km", "<=2 km", "<=5 km", "<=20 km", ">20 km"])
print(pd.crosstab(nn.cls, nn.bin).to_string())
print("\nrock locations among them:", int(nn.is_rock_loc.sum()))
print(pd.crosstab(nn[nn.is_rock_loc].cls, nn[nn.is_rock_loc].bin).to_string())
print("\nnearest FI region of the edge points (<=2 km):", nn[nn.dist_m <= 2000].nearest_fi.value_counts().to_dict())
nn.drop(columns="geometry").to_csv(SP + "/fi_division_edge.csv", index=False)
far = nn[nn.dist_m > 5000]
print("\nfar points (>5 km) sample:"); print(far[["locationid","locationcode","latitude","longitude","cls","dist_m"]].head(12).to_string())
