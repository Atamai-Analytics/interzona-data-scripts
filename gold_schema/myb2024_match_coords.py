"""Read-only: give each facility in the USGS 2024 Minerals Yearbook vol. III global facilities table (doi:10.5066/P1KEQASH, CC0) a position by
matching it to the point layers of the USGS regional GIS compilations (Africa 2021, China 2023, Southwest Asia 2022, Indo-Pacific 2024, Latin America
and the Caribbean 2017). Writes D:/CriticalMineralsDB/World/usgs_facilities_20261110/myb2024_facility_positions.csv and prints match rates.

Match order per MYB facility (one USGS Facility ID = one facility, possibly many commodity rows):
  1. ID: same country code + same number after removing zero padding (CHN0012 = CHN012), AND the names agree (similarity >= 0.6 after removing
     words such as mine/plant/smelter) - the regional files and the yearbook number facilities independently in places, so an ID alone is not trusted.
  2. NAME: same country, name similarity >= 0.85 (only one candidate above the threshold, or the best clearly ahead).
Unmatched facilities keep no position (reported by country).
"""
import re, difflib, collections, warnings
import pandas as pd, pyogrio
warnings.filterwarnings("ignore")

W = "D:/CriticalMineralsDB/World/usgs_facilities_20261110"
LAYERS = [("AFR", "D:/CriticalMineralsDB/Africa/download_20261110/gdb/Africa_GIS.gdb", "AFR_Mineral_Facilities", 2018),
          ("CHN", f"{W}/china/CHN_GIS.gdb", "CHN_Mineral_Facilities", 2020),
          ("SWA", f"{W}/swasia/SWAsia_GIS.gdb", "SWA_Mineral_Facilties", 2018),
          ("IDP", f"{W}/indopac/INDOPAC_GIS.gdb", "INDOPAC_Mineral_Facilities", 2021)]
STOP = r"\b(mine|mines|plant|plants|smelter|refinery|works|quarry|quarries|deposit|project|operation|operations|complex|facility|factory|company|co|ltd|the|and|of|no|site)\b"
norm = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", (s or "").lower()))
def nid(x):
    m = re.match(r"^([A-Z]{2,3})_?0*(\d+)$", str(x).strip())
    return (m.group(1), int(m.group(2))) if m else None
sim = lambda a, b: difflib.SequenceMatcher(None, norm(a), norm(b)).ratio() if norm(a) and norm(b) else 0.0

pts = []
for reg, gdb, lay, yr in LAYERS:
    d = pyogrio.read_dataframe(gdb, layer=lay, read_geometry=False)
    for r in d.itertuples():
        if r.Latitude is None or r.Longitude is None: continue
        conf = getattr(r, "LocConfid", None) or getattr(r, "LocConf", None)
        pts.append(dict(region=reg, uid=str(r.FeatureUID), nid=nid(r.FeatureUID), country=str(r.Country), name=str(r.FeatureNam),
                        lat=float(r.Latitude), lon=float(r.Longitude), conf=str(conf or ""), year=yr))
lac = pd.read_csv(f"{W}/lac/MINFAC_LAC.csv", dtype=str, encoding="latin-1")
for r in lac.itertuples():
    try: pts.append(dict(region="LAC", uid=r.FACID, nid=None, country=str(r.COUNTRY), name=str(r.LOCNAME or ""), lat=float(r.DDLAT), lon=float(r.DDLONG),
                         conf=str(r.LOCACC or ""), year=int(r.YEAR or 2014)))
    except (TypeError, ValueError): pass
pts = pd.DataFrame(pts).drop_duplicates(subset=["region", "uid", "lat", "lon"])
print("regional points", len(pts), dict(pts.region.value_counts()))

f = pd.read_csv(f"{W}/myb2024/2024MYBv3_Facilities_table.csv", dtype=str, encoding="latin-1")
f.columns = [c.replace("ï»¿", "") for c in f.columns]
fac = f.groupby("USGS Facility ID").agg(name=("Facility Name", "first"), country=("Country (Short Form) or Locality", "first"),
                                         ftype=("Feature Type", "first"), loc=("Location Description", "first")).reset_index()
CMAP = {"Burma": "Burma", "Korea, North": "Korea, North", "Korea, South": "Korea, South", "Congo (Kinshasa)": "Congo (Kinshasa)"}
by_nid = collections.defaultdict(list)
for i, p in pts.iterrows():
    if p.nid: by_nid[p.nid].append(i)
by_country = collections.defaultdict(list)
for i, p in pts.iterrows(): by_country[p.country.strip().lower()].append(i)

out, how = [], collections.Counter()
for r in fac.itertuples():
    hit, method = None, None
    k = nid(r._1)
    for i in by_nid.get(k, []):
        if sim(r.name, pts.at[i, "name"]) >= 0.6: hit, method = i, "id+name"; break
    if hit is None:
        cands = sorted(((sim(r.name, pts.at[i, "name"]), i) for i in by_country.get(str(r.country).strip().lower(), [])), reverse=True)
        if cands and cands[0][0] >= 0.85 and (len(cands) == 1 or cands[0][0] - cands[1][0] >= 0.05 or
                                              (abs(pts.at[cands[0][1], "lat"] - pts.at[cands[1][1], "lat"]) < 0.05 and abs(pts.at[cands[0][1], "lon"] - pts.at[cands[1][1], "lon"]) < 0.05)):
            hit, method = cands[0][1], "name"
    how[method or "unmatched"] += 1
    p = pts.loc[hit] if hit is not None else None
    out.append([r._1, r.name, r.country, r.ftype, r.loc, method or "", p.region if p is not None else "", p.uid if p is not None else "",
                p["name"] if p is not None else "", p.lat if p is not None else None, p.lon if p is not None else None,
                p.conf if p is not None else "", p.year if p is not None else None])
res = pd.DataFrame(out, columns=["facility_id", "name", "country", "feature_type", "location_text", "match", "region", "regional_uid", "regional_name",
                                 "lat", "lon", "loc_confidence", "regional_year"])
res.to_csv(f"{W}/myb2024_facility_positions.csv", index=False, encoding="utf-8")
print("MYB facilities", len(res), dict(how))
unm = res[res.match == ""]
print("matched by region", dict(res[res.match != ""].region.value_counts()))
print("unmatched by country (top 25)", dict(unm.country.value_counts().head(25)))
print("matched share in regional-coverage countries:")
cov = set(pts.country.str.strip().str.lower())
sub = res[res.country.str.strip().str.lower().isin(cov)]
print("  facilities in covered countries", len(sub), "| matched", int((sub.match != "").sum()))
