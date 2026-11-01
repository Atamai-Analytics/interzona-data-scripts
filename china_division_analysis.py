import pandas as pd, geopandas as gpd, numpy as np
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
c = pd.read_csv(SP + "/cn_locations.csv")
d = pd.read_csv(SP + "/divisions_all.csv").set_index("divisionid")
cn = int(pd.read_csv(SP + "/countries.csv").query("countryname=='China'").countryid.iloc[0])
code_to_id = {r.divisioncode: r.Index for r in d[d.countryid == cn].itertuples()}
poly = gpd.read_file(SHP, bbox=(70, 15, 136, 55), engine="pyogrio").reset_index(drop=True)
poly["pid"] = poly.index
# polygon -> division learned from assigned locations
a = c[c.divisionid.notna()]
j = gpd.sjoin(gpd.GeoDataFrame(a, geometry=gpd.points_from_xy(a.longitude, a.latitude), crs=4326), poly[["pid", "geometry"]], how="inner", predicate="within")
per = j.groupby(["pid", "divisionid"]).size().reset_index(name="n")
tot = per.groupby("pid").n.sum().rename("tot")
top = per.sort_values("n", ascending=False).drop_duplicates("pid").set_index("pid").join(tot)
top["share"] = top.n / top.tot
learned = top[(top.share >= 0.9) & (top.tot >= 20)].divisionid.astype(int).to_dict()
hk = poly.index[poly.shapeName.str.contains("Hong Kong")][0]
learned.setdefault(int(hk), code_to_id["CN-HK"])
print("polygons with a mapping:", len(learned))
n = c[c.divisionid.isna()].copy()
P = poly.to_crs("ESRI:102025")                      # Asia North Albers equal-area conic
pts = gpd.GeoDataFrame(n, geometry=gpd.points_from_xy(n.longitude, n.latitude), crs=4326).to_crs("ESRI:102025")
D = np.vstack([pts.geometry.distance(P.geometry[i]).values for i in range(len(P))]).T / 1000.0
order = np.argsort(D, axis=1)
lab = lambda i: f"{P.shapeGroup[i]}/{P.shapeName[i]}"
n["pid"] = order[:, 0]; n["nearest"] = [lab(i) for i in order[:, 0]]; n["d1_km"] = D[np.arange(len(n)), order[:, 0]]
n["second"] = [lab(i) for i in order[:, 1]]; n["d2_km"] = D[np.arange(len(n)), order[:, 1]]
n["clear"] = ((n.d2_km - n.d1_km) >= 5) | (n.d2_km >= 2 * n.d1_km)
n["chinese"] = n.nearest.str.startswith("CHN/")
n["new_divisionid"] = [learned.get(int(p)) if ch else None for p, ch in zip(n.pid, n.chinese)]
print("\nnearest polygon:", n.nearest.value_counts().head(14).to_dict())
print("non-Chinese nearest:", n[~n.chinese].nearest.value_counts().to_dict())
print("distance km quantiles:", n.d1_km.quantile([.1, .5, .9, 1]).round(1).to_dict())
print("clear:", int(n.clear.sum()), "| mapped:", int(n.new_divisionid.notna().sum()))
ok = n[n.clear & n.chinese & n.new_divisionid.notna()].copy()
ok["new_divisionid"] = ok.new_divisionid.astype(int)
print("\nASSIGN:", len(ok), "| bands km:", pd.cut(ok.d1_km, [-1, 2, 5, 10, 20, 50]).value_counts().sort_index().to_dict())
print(ok.groupby("new_divisionid").size().sort_values(ascending=False).rename(index=lambda i: f"{d.divisioncode[i]} {d.divisionname[i]}").to_string())
ok[["locationid", "countryid", "new_divisionid"]].assign(reason="china_nearest_clear").to_csv(SP + "/division_assign_china.csv", index=False)
rev = n[~n.index.isin(ok.index)]
rev[["locationid", "datasource", "latitude", "longitude", "nearest", "d1_km", "second", "d2_km"]].round(2).to_csv("china_division_review_leftovers.csv", index=False)
print("\nleft for review:", len(rev)); print(rev[["locationid", "latitude", "longitude", "nearest", "d1_km", "second", "d2_km"]].round(1).head(25).to_string(index=False))
