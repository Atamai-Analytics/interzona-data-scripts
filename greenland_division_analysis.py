import pandas as pd, geopandas as gpd, numpy as np
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
l = pd.read_csv(SP + "/division_assign_leftovers.csv")
g = l[(l.country == "Greenland")].copy()
print("Greenland leftovers:", len(g), g.reason.value_counts().to_dict(), "| datasources:", g.datasource.str[:40].value_counts().head(4).to_dict())
poly = gpd.read_file(SHP, bbox=(-75, 58, 5, 86), engine="pyogrio")
print("polygons in bbox:", dict(poly.shapeGroup.value_counts()))
P = poly.to_crs(3413).reset_index(drop=True)
pts = gpd.GeoDataFrame(g, geometry=gpd.points_from_xy(g.longitude, g.latitude), crs=4326).to_crs(3413)
D = np.vstack([pts.geometry.distance(P.geometry[i]).values for i in range(len(P))]).T / 1000.0   # km
order = np.argsort(D, axis=1)
g["nearest"] = [P.shapeGroup[i] + "/" + P.shapeName[i] for i in order[:, 0]]
g["d1_km"] = D[np.arange(len(g)), order[:, 0]]
g["second"] = [P.shapeGroup[i] + "/" + P.shapeName[i] for i in order[:, 1]]
g["d2_km"] = D[np.arange(len(g)), order[:, 1]]
g["gap_km"] = g.d2_km - g.d1_km
print("\nnearest polygon:"); print(g.nearest.value_counts().to_string())
print("\ndistance to nearest (km) quantiles:", g.d1_km.quantile([.1, .25, .5, .75, .9, .99]).round(1).to_dict(), "max", round(g.d1_km.max(), 1))
bins = pd.cut(g.d1_km, [0, 5, 10, 20, 50, 1e9], labels=["<=5", "<=10", "<=20", "<=50", ">50"])
print(bins.value_counts().sort_index().to_dict())
# is the nearest polygon clearly closer than the runner-up (different region)?
diff = g[g.nearest != g.second]
g["clear"] = (g.gap_km >= 5) | (g.d2_km >= 2 * g.d1_km)
print("\nclear winner (runner-up >=5 km farther or >=2x farther):", int(g.clear.sum()), "of", len(g), "| ambiguous:", int((~g.clear).sum()))
print(pd.crosstab(g.nearest, g.clear).to_string())
print("\nsample of points (lat, lon, nearest, d1 km):")
print(g.sample(8, random_state=3)[["locationid", "latitude", "longitude", "nearest", "d1_km", "gap_km"]].round(2).to_string(index=False))
print("\nwhere are they? lat/lon summary:", g[["latitude", "longitude"]].describe().loc[["min", "50%", "max"]].round(1).to_dict())
g.to_csv(SP + "/greenland_leftover_analysis.csv", index=False)
