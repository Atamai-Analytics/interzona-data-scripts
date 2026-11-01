import re, unicodedata
import pandas as pd, geopandas as gpd, numpy as np
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
l = pd.read_csv(SP + "/division_assign_leftovers.csv")
g = l[(l.country == "Sweden")].copy()
print("Sweden leftovers:", len(g), g.reason.value_counts().to_dict(), "| datasources:", g.datasource.str[:40].value_counts().head(4).to_dict())
poly = gpd.read_file(SHP, bbox=(8, 54, 26, 71), engine="pyogrio")
print("polygons in bbox:", dict(poly.shapeGroup.value_counts()))
P = poly.to_crs(3006).reset_index(drop=True)
pts = gpd.GeoDataFrame(g, geometry=gpd.points_from_xy(g.longitude, g.latitude), crs=4326).to_crs(3006)
D = np.vstack([pts.geometry.distance(P.geometry[i]).values for i in range(len(P))]).T / 1000.0
order = np.argsort(D, axis=1)
lab = lambda i: P.shapeGroup[i] + "/" + P.shapeName[i]
g["nearest"] = [lab(i) for i in order[:, 0]]; g["d1_km"] = D[np.arange(len(g)), order[:, 0]]
g["second"] = [lab(i) for i in order[:, 1]]; g["d2_km"] = D[np.arange(len(g)), order[:, 1]]
g["gap_km"] = g.d2_km - g.d1_km
g["clear"] = (g.gap_km >= 5) | (g.d2_km >= 2 * g.d1_km)
g["swedish"] = g.nearest.str.startswith("SWE/")
print("\nnearest polygon country:", g.nearest.str[:3].value_counts().to_dict())
print("distance to nearest km quantiles:", g.d1_km.quantile([.1, .25, .5, .75, .9, 1]).round(1).to_dict())
print("bands:", pd.cut(g.d1_km, [0, 5, 10, 20, 50, 1e9]).value_counts().sort_index().to_dict())
print("clear:", int(g.clear.sum()), "| clear and Swedish nearest:", int((g.clear & g.swedish).sum()))
print(pd.crosstab(g.nearest, g.clear).to_string())
# division lookup
d = pd.read_csv(SP + "/divisions_all.csv"); c = pd.read_csv(SP + "/countries.csv")
se = int(c[c.countryname == "Sweden"].countryid.iloc[0])
def norm(s): return ''.join(ch for ch in unicodedata.normalize('NFKD', re.sub(r"\s*\[.*?\]", "", str(s)).lower()) if ch.isalnum())
dmap = {norm(r.divisionname): r.divisionid for r in d[d.countryid == se].itertuples()}
swe_names = sorted(set(n.split("/", 1)[1] for n in g.nearest if n.startswith("SWE/")))
miss = [n for n in swe_names if norm(n) not in dmap]
print("Swedish polygons needing a division:", len(swe_names), "| without a name match:", miss)
g["new_divisionid"] = [dmap.get(norm(n.split("/", 1)[1])) if n.startswith("SWE/") else None for n in g.nearest]
ok = g[g.clear & g.swedish & g.new_divisionid.notna()].copy()
ok["new_divisionid"] = ok.new_divisionid.astype(int)
ok[["locationid", "countryid", "new_divisionid"]].assign(reason="sweden_nearest_clear").to_csv(SP + "/division_assign_sweden.csv", index=False)
rev = g[~g.index.isin(ok.index)]
rev[["locationid", "datasource", "latitude", "longitude", "nearest", "d1_km", "second", "d2_km"]].round(2).to_csv("sweden_division_review_leftovers.csv", index=False)
print("\nASSIGN:", len(ok), "| left for review:", len(rev), "| bands assigned:", pd.cut(ok.d1_km, [0, 5, 10, 20, 50]).value_counts().sort_index().to_dict())
print(ok.nearest.value_counts().head(8).to_dict())
