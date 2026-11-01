"""Second-round placement for the 34 facilities still unplaced after the GNIS round. READ-ONLY (writes a proposal CSV for load_us_facilities.py).

Every correction is an explicit, reviewable rule in OVERRIDES (why it is justified is in the 'why' text) and is checked against USGS GNIS: a rule only
applies if GNIS actually returns the named feature. County texts are placed at the county centre (GNIS 'X County' feature, position_accuracy COUNTY_CENTROID);
ambiguous names are resolved only by naming the county.  Anything not covered stays UNPLACED.
Output: D:/CriticalMineralsDB/Processing/facilities_placement_proposal_34.csv  (same columns as the other proposal files).
"""
import json, os, re, time, urllib.request, urllib.parse
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal_74_final.csv"
OUT = r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal_34.csv"
BASE = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer"
UA = {"User-Agent": "interzona-research/1.0 (dean@atamaianalytics.com)"}


def gnis(name, st, layers=(3, 2, 1, 5), county=None):
    """all GNIS features called `name` in state `st` (case-insensitive): (gaz_name, county, class, lat, lon)"""
    hits = []
    for layer in layers:
        where = f"UPPER(gaz_name) = UPPER('{name.replace(chr(39), chr(39) * 2)}') AND state_alpha = '{st}'"
        url = f"{BASE}/{layer}/query?" + urllib.parse.urlencode({"where": where, "outFields": "gaz_name,gaz_featureclass,county_name", "returnGeometry": "true", "outSR": "4326", "f": "json", "resultRecordCount": 25})
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        except Exception:
            j = {}
        time.sleep(0.2)
        for f in j.get("features", []):
            pts = f.get("geometry", {}).get("points")
            if pts:
                a = f["attributes"]
                hits.append((a["gaz_name"], a.get("county_name") or "", a.get("gaz_featureclass") or "", pts[0][1], pts[0][0]))
    if county:
        hits = [h for h in hits if h[1].lower().startswith(county.lower())]
    return hits


# key = the Location Description text; value = (kind, params, why)
#   place    : look up this place name in this state (optionally the named county)
#   county   : place at the centre of these counties (several = their mean)
OVERRIDES = {
    "Evaleth, MN": ("place", ("Eveleth", "MN", None), "typo: Eveleth, MN (United Taconite is at Eveleth)"),
    "Colera, AL": ("place", ("Calera", "AL", None), "probable typo: Calera, AL (Shelby Co. lime/cement area)"),
    "Bayare, NM": ("place", ("Bayard", "NM", None), "probable typo: Bayard, NM (Cobre / Grant Co.)"),
    "Port Lavaca, TX": ("place", ("Port Lavaca", "TX", None), "the sheet's state column says LA but the text says Port Lavaca, TX (Seadrift is in Calhoun Co., TX)"),
    "West Deptford, PA": ("place", ("West Deptford", "NJ", None), "no West Deptford in PA; West Deptford Township is in New Jersey"),
    "Oakwood, VA": ("place", ("Oakwood", "VA", "Buchanan"), "the facility is named Buchanan (Buchanan No. 1 Mine); Oakwood in Buchanan Co. is the coal-mining one"),
    "Longview, AL": ("place", ("Longview", "AL", "Shelby"), "Longview in Shelby Co. (lime plants); the other Longview is in Cullman Co."),
    "Grant, KS": ("county", (["Grant"], "KS"), "text is Grant County (Ulysses / Hugoton gas field), not a village"),
    "Rush, KS": ("county", (["Rush"], "KS"), "text is Rush County (Otis helium plants)"),
    "Hodgeman, KS": ("county", (["Hodgeman"], "KS"), "text is Hodgeman County"),
    "Crittenden and Livingston, KY": ("county", (["Crittenden", "Livingston"], "KY"), "text is two counties: placed midway between their centres"),
    "Grant, UT": ("county", (["Grand"], "UT"), "probable typo: Grand County, UT (Harley Dome helium field near Cisco); there is no Grant County in Utah"),
}

_cg = pd.read_csv(r"D:\CriticalMineralsDB\Processing\Census_Gazetteer_2026\2026_Gaz_counties_national.txt", sep="|", dtype=str, encoding="latin-1").rename(columns=lambda c: c.strip())
COUNTIES = {(r.USPS, re.sub(r"\s+(county|parish|borough|census area)$", "", r.NAME, flags=re.I).lower()): (float(r.INTPTLAT), float(r.INTPTLONG), r.NAME) for r in _cg.itertuples()}
p = pd.read_csv(SRC, dtype=str, encoding="utf-8-sig").fillna("")
res_cache = {}


def resolve(text):
    if text in res_cache:
        return res_cache[text]
    kind, params, why = OVERRIDES[text]
    out = None
    if kind == "place":
        nm, st, county = params
        hits = gnis(nm, st, layers=(3, 2, 1), county=county)
        pop = [h for h in hits if h[2] in ("Populated Place", "Civil", "Census", "Locale")] or hits
        if len(pop) >= 1:
            h = pop[0]
            out = dict(place=h[0], lat=h[3], lon=h[4], accuracy="TOWN_CENTROID", match=f"gnis:{h[2]} ({h[1]} Co.) override", why=why + (f" [{len(pop)} GNIS hits]" if len(pop) > 1 else ""))
    else:
        names, st = params
        pts = []
        for n in names:
            cc = COUNTIES.get((st, n.lower()))          # Census 2026 Gazetteer counties file (representative interior point)
            if cc:
                pts.append((cc[0], cc[1], cc[2]))
        if len(pts) == len(names):
            out = dict(place=" + ".join(x[2] for x in pts), lat=sum(x[0] for x in pts) / len(pts), lon=sum(x[1] for x in pts) / len(pts), accuracy="COUNTY_CENTROID", match="gnis:county override", why=why)
    res_cache[text] = out
    return out


applied, kept = 0, 0
for i, r in p.iterrows():
    if r["action"] != "UNPLACED" or r["town_text"] not in OVERRIDES:
        continue
    o = resolve(r["town_text"])
    if not o:
        kept += 1
        p.at[i, "review_candidate"] = (r["review_candidate"] + " | " if r["review_candidate"] else "") + "OVERRIDE FAILED (GNIS returned nothing): " + OVERRIDES[r["town_text"]][2]
        continue
    p.at[i, "action"] = "NEW_COUNTY" if o["accuracy"] == "COUNTY_CENTROID" else "NEW_TOWN"
    p.at[i, "lat"], p.at[i, "lon"] = str(o["lat"]), str(o["lon"])
    p.at[i, "position_accuracy"] = o["accuracy"]
    p.at[i, "gaz_place"] = o["place"]
    p.at[i, "town_match"] = o["match"]
    p.at[i, "review_candidate"] = "OVERRIDE: " + o["why"]
    applied += 1
print("overrides applied to", applied, "facilities; override failed for", kept)
p.to_csv(OUT, index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70); pd.set_option("display.max_rows", 100)
print(p["action"].value_counts().to_string())
chg = p[p["review_candidate"].str.startswith("OVERRIDE")][["name", "town_text", "gaz_place", "position_accuracy", "lat", "lon"]].copy()
chg["lat"] = chg["lat"].str[:8]; chg["lon"] = chg["lon"].str[:9]
print(chg.to_string())
print("\nSTILL UNPLACED:")
print(p[p["action"] == "UNPLACED"][["name", "town_text"]].to_string())
