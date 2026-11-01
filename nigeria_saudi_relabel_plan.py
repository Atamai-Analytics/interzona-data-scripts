import difflib, unicodedata
import pandas as pd, geopandas as gpd, numpy as np
pd.set_option("display.width", 230)
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
SHP = r"D:/CriticalMineralsDB/GIS/geoBoundariesCGAZ_ADM1/geoBoundariesCGAZ_ADM1.shp"
MARGIN_M = 1000.0
a = pd.read_csv(SP + "/ngsa_locations.csv")
d = pd.read_csv(SP + "/divisions_all.csv"); c = pd.read_csv(SP + "/countries.csv")
def norm(s):
    s = ''.join(ch for ch in unicodedata.normalize('NFKD', str(s).lower()) if ch.isalnum() or ch == ' ')
    for w in (" region", " province", " state"): s = s.replace(w, "")
    return s.strip()
poly = gpd.read_file(SHP, bbox=(2, 3, 47, 33), engine="pyogrio").reset_index(drop=True)
out = []
for country, grp, crs in (("Nigeria", "NGA", 32632), ("Saudi Arabia", "SAU", 32637)):
    cid = int(c[c.countryname == country].countryid.iloc[0])
    dv = d[d.countryid == cid]
    P = poly[poly.shapeGroup == grp].to_crs(crs).reset_index(drop=True)
    # polygon -> division by name
    m = {}
    for r in P.itertuples():
        best = max(((difflib.SequenceMatcher(None, norm(r.shapeName), norm(n)).ratio(), i) for i, n in zip(dv.divisionid, dv.divisionname)))
        m[r.shapeName] = best[1] if best[0] >= 0.6 else None
    if country == "Saudi Arabia":                      # CGAZ English names -> division names (transliterated)
        explicit = {"Makkah Region": "makkah", "Al Madinah Region": "madinah", "Eastern Region": "sharq"}
        for shp, key in explicit.items():
            hits = [i for i, n in zip(dv.divisionid, dv.divisionname) if key in unicodedata.normalize("NFKD", n.lower()).encode("ascii", "ignore").decode()]
            assert len(hits) == 1, (shp, hits)
            m[shp] = hits[0]
        # "Northern Borders Region" has no division row in the database
    names = dv.set_index("divisionid").divisionname.to_dict()
    print(f"\n===== {country}: polygon -> division mapping (name similarity >= 0.6)")
    print("  unmapped polygons:", [k for k, v in m.items() if v is None])
    print("  ", "; ".join(f"{k}->{names[v]}" for k, v in list(m.items())[:40] if v is not None)[:900])
    s = a[a.countryname == country].copy()
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.longitude, s.latitude), crs=4326).to_crs(crs)
    j = gpd.sjoin(g, P[["shapeName", "geometry"]], how="left", predicate="within").drop_duplicates("locationid")
    # distance to the polygon's boundary (margin)
    pm = P.set_index("shapeName").geometry
    j["margin_m"] = [pm[sn].boundary.distance(pt) if isinstance(sn, str) else np.nan for sn, pt in zip(j.shapeName, j.geometry)]
    j["target"] = j.shapeName.map(m)
    j["country"] = country
    ch = j[(j.target.notna()) & (j.divisionid != j.target)]
    safe = ch[ch.margin_m >= MARGIN_M]
    print(f"  locations: {len(s)} | in a mapped polygon: {int(j.target.notna().sum())} | label differs from the polygon's division: {len(ch)} | of those >= {MARGIN_M:.0f} m inside the polygon (would relabel): {len(safe)}; near a border (left): {len(ch) - len(safe)}")
    ct = safe.groupby([safe.divisionname.fillna("(none)"), safe.target.map(names)]).size().sort_values(ascending=False)
    print("  relabel old -> new (count):"); print(ct.head(14).to_string())
    print("  by dataset:", safe.datasource.str[:32].value_counts().head(4).to_dict())
    nul = j[(j.divisionid.isna())]
    print("  currently no division:", len(nul), "| outside every polygon:", int(j.shapeName.isna().sum()))
    out.append(safe.assign(new_divisionid=safe.target.astype(int))[["locationid", "divisionid", "new_divisionid", "country", "margin_m"]])
    ch.drop(columns="geometry").to_csv(SP + f"/relabel_all_{grp}.csv", index=False)
pd.concat(out).to_csv(SP + "/relabel_plan.csv", index=False)
print("\nTOTAL would relabel:", sum(len(o) for o in out))
