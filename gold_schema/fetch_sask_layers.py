"""Pull Saskatchewan Geological Survey open layers from the province's ArcGIS map service into CSV (one file per layer) plus the layer metadata as licence evidence.

Layers: drill-hole collars (Mineral_Exploration/3) and the survey geochemistry layers in Analytical_and_Rock_Property_Data (lake water, lake sediment,
GSC lake sediment, till). Coordinates are requested in WGS84 (outSR=4326) next to the source UTM fields.

Usage: python fetch_sask_layers.py D:/CriticalMineralsDB/Canada/Saskatchewan_geochem_drillholes
"""
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://gis.saskatchewan.ca/arcgis/rest/services/Economy"
LAYERS = {
    "drillholes": f"{BASE}/Mineral_Exploration/MapServer/3",
    "lake_water": f"{BASE}/Analytical_and_Rock_Property_Data/MapServer/2",
    "lake_sediment_sgs": f"{BASE}/Analytical_and_Rock_Property_Data/MapServer/3",
    "lake_sediment_gsc": f"{BASE}/Analytical_and_Rock_Property_Data/MapServer/4",
    "till": f"{BASE}/Analytical_and_Rock_Property_Data/MapServer/6",
}
PAGE = 1000


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))


def fetch(name, url, out):
    meta = get(url, {"f": "json"})
    (out / f"{name}_metadata.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    page = min(PAGE, meta.get("maxRecordCount") or PAGE)
    ids = sorted(get(f"{url}/query", {"where": "1=1", "returnIdsOnly": "true", "f": "json"})["objectIds"] or [])
    oid = next(f["name"] for f in meta["fields"] if f["type"] == "esriFieldTypeOID")
    fields = [f["name"] for f in meta["fields"] if f["type"] not in ("esriFieldTypeGeometry",)]
    rows = []
    for i in range(0, len(ids), page):
        chunk = ids[i:i + page]
        d = get(f"{url}/query", {"where": f"{oid} >= {chunk[0]} AND {oid} <= {chunk[-1]}", "outFields": "*", "returnGeometry": "true",
                                 "outSR": "4326", "f": "json"})
        for f in d["features"]:
            a = f["attributes"]
            g = f.get("geometry") or {}
            a["lon_wgs84"], a["lat_wgs84"] = g.get("x"), g.get("y")
            rows.append(a)
    with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields + ["lon_wgs84", "lat_wgs84"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} of {len(ids)} records")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for n, u in LAYERS.items():
        fetch(n, u, out)
