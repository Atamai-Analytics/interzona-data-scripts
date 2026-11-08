"""Geocode the localities in curated_lithium_20261108.csv with OpenStreetMap Nominatim (1 request/s, identified client) and apply the
published offsets (km, bearing). Writes curated_lithium_20261108_geocoded.csv for review before loading. Positions are APPROXIMATE
(locality-level, about 5-15 km).
"""
import csv, json, math, os, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "curated_lithium_20261108.csv")
OUT = os.path.join(HERE, "curated_lithium_20261108_geocoded.csv")
UA = "interzona-data-scripts/1.0 (Atamai Analytics geocoding of mine localities)"
cache = {}


def geocode(q):
    if q in cache: return cache[q]
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    time.sleep(1.1)
    with urllib.request.urlopen(req, timeout=30) as r:
        js = json.loads(r.read().decode("utf-8"))
    cache[q] = (float(js[0]["lat"]), float(js[0]["lon"]), js[0].get("display_name", "")) if js else None
    return cache[q]


def offset(lat, lon, km, bearing):
    if not km: return lat, lon
    R, b = 6371.0, math.radians(bearing)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(km / R) + math.cos(la1) * math.sin(km / R) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(km / R) * math.cos(la1), math.cos(km / R) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
for r in rows:
    g = geocode(r["locality_query"])
    if not g:
        r["lat"] = r["lon"] = r["geocoded_as"] = ""; print("NOT FOUND", r["name"], r["locality_query"]); continue
    lat, lon = offset(g[0], g[1], float(r["offset_km"] or 0), float(r["bearing_deg"] or 0))
    r["lat"], r["lon"], r["geocoded_as"] = round(lat, 5), round(lon, 5), g[2][:120]
    print(f"{r['name'][:38]:38s} {r['lat']:>10} {r['lon']:>10} | {g[2][:80]}")
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("wrote", OUT)
