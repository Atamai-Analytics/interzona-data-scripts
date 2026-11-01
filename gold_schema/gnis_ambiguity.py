"""For the 74 never-loaded facilities: list ALL GNIS matches (populated/unincorporated/incorporated places, landforms) per town+state, so ambiguous names can be seen."""
import json, math, time, urllib.request, urllib.parse
import pandas as pd
BASE = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer"
UA = {"User-Agent": "interzona-research/1.0 (dean@atamaianalytics.com)"}
def get(url): return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371 * 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
TYPOS = {"ceder city": "Cedar City", "humbolt": "Humboldt", "lehmi": "Lemhi", "evaleth": "Eveleth", "northwest artic borough": "Northwest Arctic"}
p = pd.read_csv(r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal.csv", dtype=str).fillna("")
u = pd.read_csv("_facilities_unplaced.csv", dtype=str)
m = p[p.facility_id.isin(set(u.facility_id))].drop_duplicates(["town_text", "st"])
out = []
for r in m.itertuples():
    town = r.town_text.split(",")[0].strip()
    names = [town]
    for k, v in TYPOS.items():
        if k in town.lower(): names.append(v)
    hits = []
    for nm in dict.fromkeys(names):
        for layer in (3, 2, 1, 5):
            where = f"gaz_name = '{nm.replace(chr(39), chr(39)*2)}' AND state_alpha = '{r.st}'"
            url = f"{BASE}/{layer}/query?" + urllib.parse.urlencode({"where": where, "outFields": "gaz_name,gaz_featureclass,county_name", "returnGeometry": "true", "outSR": "4326", "f": "json", "resultRecordCount": 25})
            try: j = get(url)
            except Exception: j = {}
            time.sleep(0.2)
            for f in j.get("features", []):
                if f.get("geometry", {}).get("points"):
                    pt = f["geometry"]["points"][0]
                    hits.append((f["attributes"]["gaz_name"], f["attributes"].get("county_name") or "", f["attributes"].get("gaz_featureclass") or "", round(pt[1], 4), round(pt[0], 4)))
    uniq = []
    for h in hits:
        if not any(hav((h[3], h[4]), (x[3], x[4])) < 15 for x in uniq): uniq.append(h)
    out.append((r.town_text, r.st, len(uniq), uniq[:6]))
amb = [o for o in out if o[2] > 1]; one = [o for o in out if o[2] == 1]; none = [o for o in out if o[2] == 0]
print(f"{len(out)} distinct town/state texts: unique {len(one)}, AMBIGUOUS {len(amb)}, none {len(none)}")
print("\n--- AMBIGUOUS (candidates: county, class, lat, lon)")
for o in amb: print(o[0], "|", o[1], "|", [(h[1], h[2], h[3], h[4]) for h in o[3]])
print("\n--- NO GNIS MATCH:", [(o[0]) for o in none])
json.dump(out, open("_gnis_candidates.json", "w"), indent=1)
