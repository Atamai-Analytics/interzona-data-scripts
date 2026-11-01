import pandas as pd, geopandas as gpd, difflib, unicodedata
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
cells = pd.read_csv(SP + "/cells.csv"); divs = pd.read_csv(SP + "/divisions_all.csv").set_index("divisionid")
ctry = pd.read_csv(SP + "/countries.csv").set_index("countryid")["countryname"].to_dict()
pts = gpd.GeoDataFrame(cells[cells.divisionid.notna()], geometry=gpd.points_from_xy(cells[cells.divisionid.notna()].lon, cells[cells.divisionid.notna()].lat), crs=4326)
poly = gpd.read_file(SHP, engine="pyogrio")[["shapeName", "shapeGroup", "geometry"]]
j = gpd.sjoin(pts, poly, how="left", predicate="within").drop_duplicates(subset=["countryid", "divisionid", "lat", "lon"])
def norm(s):
    s = ''.join(ch for ch in unicodedata.normalize('NFKD', str(s).lower()) if ch.isalnum() or ch == ' ')
    for w in (" sheng", " shi", " zizhiqu", " lan", " province", " state", " county", " kommune", " kommunia", " autonomous region", " lan"):
        s = s.replace(w, "")
    return s.strip()
rows = []
for did, g in j.groupby("divisionid"):
    tot = g.n.sum()
    if tot < 200: continue
    dom = g.groupby("shapeName").n.sum().sort_values(ascending=False)
    if dom.index.empty: continue
    shape, dn = dom.index[0], dom.iloc[0]
    dname = divs.divisionname[int(did)]
    sim = difflib.SequenceMatcher(None, norm(shape), norm(dname)).ratio()
    rows.append((ctry.get(int(divs.countryid[int(did)])), divs.divisioncode[int(did)], dname, shape, int(tot), round(dn / tot, 2), round(sim, 2)))
r = pd.DataFrame(rows, columns=["country", "code", "division", "dominant_polygon", "total", "share", "name_sim"])
bad = r[r.name_sim < 0.45].sort_values("total", ascending=False)
print(f"divisions with >=200 locations: {len(r)}; dominant polygon name very different from division name (sim<0.45): {len(bad)}")
print(bad.head(40).to_string(index=False))
