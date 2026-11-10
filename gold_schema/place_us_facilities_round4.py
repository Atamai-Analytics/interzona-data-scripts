"""Round 4 (2026-11-10): place the last 9 US facilities that rounds 1-3 left UNPLACED, from facility-specific research
(company addresses, regulator permits, technical reports, press releases). READ-ONLY: writes a proposal CSV for load_us_facilities.py
(PROP_IN=<this file>) with a hand-written position_note per facility saying exactly where the position comes from.

Positions:
  * USA0004 Advanced Chemical Company Refinery: the company is at 105 Bellows Street, WARWICK, RI (not Greenwich) -> US Census geocoder.
  * USA0169 College Grove Plant (secondary lead, Ye Chiu): no current evidence of the smelter; USGS's own source is "Lead in 1998" -> town
    point of College Grove (GNIS populated place, Williamson Co.; ZIP 37046), TOWN_CENTROID; status kept as published but flagged.
  * USA0416 Little Valley Mine (gypsum, Progressive Contracting Inc.): the PCI gypsum mine is in the Little Valley area of St. George
    (St. George News; on SITLA land) -> GNIS 'Little Valley' basin, Washington Co., AREA_CENTROID.
  * USA0471 Midland Basin Carbonate Facility (LibertyStream / Select Water): Stage 1 is at Select's operating site in Howard County, north of
    Midland (company releases, Feb 2026); exact site not published -> GNIS Howard County point, COUNTY_CENTROID.
  * USA0651/0652 Reward Mine / Recovery Plant (gold, Augusta Gold): about 11.3 km SSE of Beatty and 3.2 km east of US-95, Nye Co.
    (2022 NI 43-101 / S-K 1300 summary) -> point computed from Beatty along that bearing, AREA_CENTROID ("Lone Pine, NV" in the source is wrong).
  * USA0659 Riverside facility (synthetic graphite anodes, NOVONIX): NOVONIX's Chattanooga address 1029 West 19th Street (filings); the
    Riverside plant is the former GE site on the Tennessee River in Chattanooga -> Census geocoder on that address, AREA_CENTROID.
  * USA0740 St. Clair Plant (lime, US Lime & Minerals): EPA TRI facility point 35.58222, -94.82077 (Marble City, Sequoyah Co.) - precise.
  * USA0741 St. Clair Quarry: Oklahoma DEQ permit, Sec. 14 T13N R23E, 1 mile NW of Marble City on County Road 17, ~35.601, -94.831;
    the mine is underground (SEC S-K 1300 exhibit, 2021) - precise to the permit point.
Usage: python -P place_us_facilities_round4.py
"""
import json, math, time, urllib.request, urllib.parse
import pandas as pd

OUT = r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal_9_round4.csv"
TEMPLATE = r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal_19_round3.csv"
GNIS = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer"
UA = {"User-Agent": "interzona-research/1.0"}


def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))


def gnis(name, st, county=None, cls=None):
    hits = []
    for layer in (3, 2, 1, 5, 0, 4):
        where = f"UPPER(gaz_name) = UPPER('{name}') AND state_alpha = '{st}'"
        url = f"{GNIS}/{layer}/query?" + urllib.parse.urlencode({"where": where, "outFields": "gaz_name,gaz_featureclass,county_name",
                                                                 "returnGeometry": "true", "outSR": "4326", "f": "json"})
        try: j = get(url)
        except Exception: j = {}
        time.sleep(0.2)
        for f in j.get("features", []):
            pts = f.get("geometry", {}).get("points") or ([[f["geometry"]["x"], f["geometry"]["y"]]] if "x" in f.get("geometry", {}) else None)
            if pts:
                a = f["attributes"]; hits.append((a.get("county_name") or "", a.get("gaz_featureclass") or "", pts[0][1], pts[0][0]))
    if county: hits = [h for h in hits if h[0].lower().startswith(county.lower())]
    if cls: hits = [h for h in hits if h[1].lower() == cls.lower()]
    return hits


def census(addr):
    url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + urllib.parse.urlencode(
        {"address": addr, "benchmark": "Public_AR_Current", "format": "json"})
    m = get(url)["result"]["addressMatches"]
    return (m[0]["coordinates"]["y"], m[0]["coordinates"]["x"], m[0]["matchedAddress"]) if m else None


def offset(lat, lon, km, bearing_deg):
    b = math.radians(bearing_deg)
    return lat + km * math.cos(b) / 111.32, lon + km * math.sin(b) / (111.32 * math.cos(math.radians(lat)))


P = {}
a = census("105 Bellows Street, Warwick, RI 02888"); print("Advanced Chemical", a)
P["USA0004"] = (a[0], a[1], "", f"US Census geocoder on the company address ({a[2]}); the source says Greenwich, RI but the refinery is in Warwick")
h = gnis("College Grove", "TN", county="Williamson"); print("College Grove", h)
P["USA0169"] = (h[0][2], h[0][3], "TOWN_CENTROID", "USGS GNIS populated place College Grove (Williamson Co., ZIP 37046), a locality point; the plant's site "
                "was not found and USGS's own source is the 1998 lead report, so the facility may no longer operate")
h = gnis("Little Valley", "UT", county="Washington"); print("Little Valley", h)
P["USA0416"] = (h[0][2], h[0][3], "AREA_CENTROID", "USGS GNIS 'Little Valley' (Washington Co.); the Progressive Contracting gypsum mine is in the "
                "Little Valley area of St. George on state trust land (St. George News)")
t = get("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query?" + urllib.parse.urlencode(
    {"where": "NAME = 'Howard County' AND STATE = '48'", "outFields": "NAME,INTPTLAT,INTPTLON", "returnGeometry": "false", "f": "json"}))
h = t["features"][0]["attributes"]; print("Howard County", h)
P["USA0471"] = (float(h["INTPTLAT"]), float(h["INTPTLON"]), "COUNTY_CENTROID", "Census TIGER internal point of Howard County, TX; the first LibertyStream unit is at Select Water Solutions' "
                "operating site in Howard County north of Midland (company releases, Feb 2026), exact site not published")
b = gnis("Beatty", "NV", county="Nye", cls="Populated Place"); print("Beatty", b)
rl = offset(b[0][2], b[0][3], 11.3, 157.5)
note = ("computed about 11.3 km south-south-east of Beatty (GNIS) and about 3 km east of US-95, Nye Co., from the Reward technical report "
        "summary (2022); the source's 'Lone Pine, NV' is wrong")
P["USA0651"] = (rl[0], rl[1], "AREA_CENTROID", note)
P["USA0652"] = (rl[0], rl[1], "AREA_CENTROID", note + "; the recovery plant is on the same site")
a = census("1029 West 19th Street, Chattanooga, TN 37408"); print("NOVONIX", a)
P["USA0659"] = (a[0], a[1], "AREA_CENTROID", f"US Census geocoder on NOVONIX's Chattanooga address ({a[2]}, from its filings); the Riverside "
                "plant is the former GE site on the Tennessee River in Chattanooga, so the plant may be up to ~2 km away")
P["USA0740"] = (35.58222, -94.82077, "", "EPA Toxics Release Inventory facility point for US Lime Co. - St. Clair, Marble City (Sequoyah Co.)")
P["USA0741"] = (35.601, -94.831, "", "Oklahoma DEQ permit location, Sec. 14 T13N R23E, 1 mile north-west of Marble City on County Road 17 "
                "(Sequoyah Co.); the St. Clair mine is underground (US Lime S-K 1300 exhibit, 2021)")

r3 = pd.read_csv(TEMPLATE, dtype=str).fillna("")
src = pd.read_csv(r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal.csv", dtype=str).fillna("")
rows = src[src.facility_id.isin(P)].copy()
assert len(rows) == 9, len(rows)
for col in r3.columns:
    if col not in rows.columns: rows[col] = ""
act = {"TOWN_CENTROID": "NEW_TOWN", "COUNTY_CENTROID": "NEW_COUNTY"}
for i, r in rows.iterrows():
    lat, lon, acc, note = P[r.facility_id]
    rows.loc[i, ["lat", "lon", "position_accuracy", "position_note", "town_match"]] = [f"{lat:.6f}", f"{lon:.6f}", acc, note, "round4"]
    rows.loc[i, "action"] = act.get(acc, "NEW_AREA")
    rows.loc[i, ["occ_id", "review_candidate"]] = ["", ""]
rows[r3.columns].to_csv(OUT, index=False, encoding="utf-8")
print(rows[["facility_id", "name", "action", "lat", "lon", "position_accuracy"]].to_string())
print("wrote", OUT)
