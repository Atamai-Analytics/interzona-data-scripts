"""Downloads the 8 public views of the EITI database (https://eiti-database.eiti.org, Datasette; download approved by the user 2026-11-12)
page by page as JSON (CSV streaming is disabled on the server), about one request per second, and writes one CSV per view to
D:/CriticalMineralsDB/World/eiti_database_20261112/<view>.csv. Checks the row count of each view against a count(*) query.
Usage: python fetch_eiti_database.py
"""
import csv, os, time
import requests

BASE = "https://eiti-database.eiti.org/eiti_database"
OUT = r"D:/CriticalMineralsDB/World/eiti_database_20261112"
VIEWS = ["view_countries", "view_commodities", "view_projects", "view_companies", "view_production_and_exports",
         "view_project_production", "view_revenues_detailed", "view_payments_detailed"]
os.makedirs(OUT, exist_ok=True)
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (research data client)"})


def count(v):
    r = s.get(BASE + "/-/query.json", params={"sql": f"select count(*) as n from {v}", "_shape": "array"}, timeout=120)
    return r.json()[0]["n"]


for v in VIEWS:
    expected = count(v); time.sleep(1)
    url, params, rows, cols = f"{BASE}/{v}.json", {"_size": "max", "_shape": "objects"}, [], None
    while url:
        r = s.get(url, params=params, timeout=120); r.raise_for_status(); d = r.json()
        batch = d.get("rows") or []
        if batch and cols is None: cols = list(batch[0].keys())
        rows += batch
        url, params = d.get("next_url"), None
        time.sleep(1)
    with open(os.path.join(OUT, v + ".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols or []); w.writeheader(); w.writerows(rows)
    print(v, "rows", len(rows), "expected", expected, "OK" if len(rows) == expected else "MISMATCH", flush=True)
