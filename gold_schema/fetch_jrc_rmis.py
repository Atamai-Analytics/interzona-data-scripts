"""Fetches the JRC RMIS raw-material profiles from its public JSON API (read-only; approved by the user 2026-11-11) and saves the raw JSON
per material to D:/CriticalMineralsDB/World/jrc_rmis_20261111/<Material>/<endpoint>.json as the source copy. Paced at about one request per
second. Endpoints: dashboard, trade, recycling (production and res are third-party series and are NOT fetched - user chose EU-owned
figures only). Also saves the dashboard indicator definitions from the profile app's script (indicator_definitions.json).
Usage: python fetch_jrc_rmis.py
"""
import json, os, re, time, urllib.parse
import requests

BASE = "https://rmis.jrc.ec.europa.eu/includes/public/api/rmprofiles/v2/"
OUT = r"D:/CriticalMineralsDB/World/jrc_rmis_20261111"
HDR = {"User-Agent": "Mozilla/5.0 (research data client)"}
os.makedirs(OUT, exist_ok=True)
s = requests.Session(); s.headers.update(HDR)

mats = s.get(BASE + "available", timeout=60).json()
json.dump(mats, open(os.path.join(OUT, "available.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("materials", len(mats))

# indicator definitions live in the profile app bundle (module with the dsb_ind_* list)
page = s.get("https://rmis.jrc.ec.europa.eu/rmp/", timeout=60).text
js_path = re.search(r'src="([^"]*scripts/rmp/index-prod[^"]*\.js)"', page).group(1)
js = s.get(urllib.parse.urljoin("https://rmis.jrc.ec.europa.eu/rmp/", js_path), timeout=60).text
m = re.search(r"JSON\.parse\('(\[\{\"ind\":\"dsb_ind_wldres\".*?\])'\)", js)
defs = json.loads(m.group(1).encode().decode("unicode_escape")) if m else []
json.dump(defs, open(os.path.join(OUT, "indicator_definitions.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("indicator definitions", len(defs))

bad = []
for mat in mats:
    d = os.path.join(OUT, mat.replace("/", "_")); os.makedirs(d, exist_ok=True)
    for ep in ("dashboard", "trade", "recycling"):
        f = os.path.join(d, ep + ".json")
        if os.path.exists(f) and os.path.getsize(f) > 2:
            continue
        r = s.get(BASE + ep + "/" + urllib.parse.quote(mat), timeout=60)
        if r.status_code != 200:
            bad.append((mat, ep, r.status_code))
        else:
            open(f, "w", encoding="utf-8").write(r.text)
        time.sleep(1)
print("done; failures:", bad)
