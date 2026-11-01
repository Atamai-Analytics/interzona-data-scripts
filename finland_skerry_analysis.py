import pandas as pd, geopandas as gpd, numpy as np
from finland_division_analysis import FI_MAP
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
l = pd.read_csv(SP + "/division_assign_leftovers.csv")
g = l[l.country == "Finland"].copy()
print("Finland leftovers:", len(g), g.reason.value_counts().to_dict(), "| datasources:", g.datasource.str[:40].value_counts().to_dict())
poly = gpd.read_file(SHP, bbox=(17, 58, 35, 72), engine="pyogrio")
fin = poly[poly.shapeGroup == "FIN"].to_crs(3067).reset_index(drop=True)
pts = gpd.GeoDataFrame(g, geometry=gpd.points_from_xy(g.longitude, g.latitude), crs=4326).to_crs(3067)
D = np.vstack([pts.geometry.distance(fin.geometry[i]).values for i in range(len(fin))]).T / 1000.0
order = np.argsort(D, axis=1)
g["nearest"] = [fin.shapeName[i] for i in order[:, 0]]; g["d1_km"] = D[np.arange(len(g)), order[:, 0]]
g["second"] = [fin.shapeName[i] for i in order[:, 1]]; g["d2_km"] = D[np.arange(len(g)), order[:, 1]]
g["clear"] = ((g.d2_km - g.d1_km) >= 5) | (g.d2_km >= 2 * g.d1_km)
print("\nnearest region:", g.nearest.value_counts().to_dict())
print("distance km quantiles:", g.d1_km.quantile([.1, .5, .9, 1]).round(1).to_dict())
print("clear winner:", int(g.clear.sum()), "| ambiguous:", int((~g.clear).sum()))
print(pd.crosstab(g.nearest, g.clear).to_string())
g["new_divisionid"] = g.nearest.map(FI_MAP)
assert g.new_divisionid.notna().all()
ok = g[g.clear].copy(); ok["new_divisionid"] = ok.new_divisionid.astype(int)
print("\nASSIGN:", len(ok), "| bands km:", pd.cut(ok.d1_km, [-1, 2, 5, 10, 20, 50]).value_counts().sort_index().to_dict())
ok[["locationid", "countryid", "new_divisionid"]].assign(reason="finland_skerry_nearest_clear").to_csv(SP + "/division_assign_finland_skerry.csv", index=False)
rev = g[~g.clear]
rev[["locationid", "datasource", "latitude", "longitude", "nearest", "d1_km", "second", "d2_km"]].round(2).to_csv("finland_skerry_division_review_leftovers.csv", index=False)
print("\nambiguous (left for review):"); print(rev[["locationid", "latitude", "longitude", "nearest", "d1_km", "second", "d2_km"]].round(1).to_string(index=False))
