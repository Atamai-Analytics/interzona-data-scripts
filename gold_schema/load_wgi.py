"""World Bank Worldwide Governance Indicators (WGI 2026 update, data 1996-2025) -> core.country_governance.

Only the six COMBINED indicators are loaded (Voice and Accountability VA, Political Stability and Absence of Violence/Terrorism PV,
Government Effectiveness GE, Regulatory Quality RQ, Rule of Law RL, Control of Corruption CC): estimate (about -2.5 to +2.5), governance
score (0-100) with its 90% confidence bounds, and standard error. The per-source data file (which includes rescaled values from five
proprietary sources: EIU, Gallup, PRS, S&P Global, WEF - restricted by the WGI Usage Advisory) is NOT loaded.
Licence: World Bank Data Catalog lists WGI as Creative Commons Attribution 4.0. Credit: "Worldwide Governance Indicators, 2026 Update,
World Bank (www.govindicators.org)". Usage Advisory: not to be used as definitive criteria for credit ratings, investment risk or other
critical financial decisions - shown as a caveat wherever the app uses these values. Confirmation of commercial display requested from
the WGI team 20 Nov 2026 (user to send).
Source: World Bank API v2, source 3 (lastupdated 2026-09-25). Raw JSON kept in D:/CriticalMineralsDB/WorldBank/WGI_2026/.
Usage: python -P load_wgi.py [--dry] | --undo (drops the table)
"""
import json, os, sys, time
import psycopg2, requests
from psycopg2.extras import execute_values

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
RAW = "D:/CriticalMineralsDB/WorldBank/WGI_2026"
DIMS = {"VA": "Voice and Accountability", "PV": "Political Stability and Absence of Violence/Terrorism", "GE": "Government Effectiveness",
        "RQ": "Regulatory Quality", "RL": "Rule of Law", "CC": "Control of Corruption"}
FIELDS = {"EST": "estimate", "SC": "score", "SC_LB": "score_lb", "SC_UB": "score_ub", "SE": "std_error"}
API = "https://api.worldbank.org/v2"
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
if "--undo" in sys.argv:
    c.execute("DROP TABLE IF EXISTS core.country_governance"); g.commit(); sys.exit("dropped core.country_governance")


def get(url):
    for attempt in range(6):
        r = requests.get(url, timeout=120, headers={"User-Agent": "interzona-data-loader"})
        if r.status_code == 200:
            return r.json()
        time.sleep(5 * (attempt + 1))
    r.raise_for_status()


os.makedirs(RAW, exist_ok=True)
# real countries only (the API also returns regional and income aggregates)
countries = get(f"{API}/country?format=json&per_page=400")[1]
REAL = {x["id"] for x in countries if x["region"]["id"] != "NA"}
json.dump(countries, open(f"{RAW}/countries.json", "w", encoding="utf-8"))
vals = {}
for d in DIMS:
    for f, col in FIELDS.items():
        ind = f"GOV_WGI_{d}.{f}"
        j = get(f"{API}/country/all/indicator/{ind}?source=3&format=json&per_page=20000")
        meta, rows = j[0], j[1] or []
        assert meta["pages"] == 1, f"{ind} paged"
        json.dump(j, open(f"{RAW}/{ind}.json", "w", encoding="utf-8"))
        k = 0
        for r in rows:
            iso = r.get("countryiso3code")
            if not iso or iso not in REAL or r["value"] is None: continue
            vals.setdefault((iso, int(r["date"]), d), {})[col] = float(r["value"]); k += 1
        print(f"{ind}: {k} country-year values (last updated {meta.get('lastupdated')})")
        time.sleep(0.5)

rows = [(iso, y, d, v.get("estimate"), v.get("score"), v.get("score_lb"), v.get("score_ub"), v.get("std_error")) for (iso, y, d), v in vals.items()]
print("rows", len(rows), "countries", len({r[0] for r in rows}), "years", min(r[1] for r in rows), "-", max(r[1] for r in rows))
c.execute("SELECT count(DISTINCT r.iso) FROM (SELECT unnest(%s::text[]) AS iso) r WHERE NOT EXISTS (SELECT 1 FROM core.country_aliases a WHERE a.iso3 = r.iso)", ([r[0] for r in rows],))
print("WGI countries not in core.country_aliases:", c.fetchone()[0])
if "--dry" in sys.argv: sys.exit("DRY")
c.execute("""CREATE TABLE IF NOT EXISTS core.country_governance (iso3 char(3) NOT NULL, year int NOT NULL, dimension char(2) NOT NULL,
             estimate numeric, score numeric, score_lb numeric, score_ub numeric, std_error numeric, release text NOT NULL DEFAULT 'WGI 2026 update',
             created_date timestamptz DEFAULT now(), PRIMARY KEY (iso3, year, dimension))""")
c.execute("TRUNCATE core.country_governance")
execute_values(c, "INSERT INTO core.country_governance (iso3, year, dimension, estimate, score, score_lb, score_ub, std_error) VALUES %s", rows, page_size=5000)
c.execute("""COMMENT ON TABLE core.country_governance IS 'World Bank Worldwide Governance Indicators, 2026 update (combined indicators only; dimension VA/PV/GE/RQ/RL/CC; score 0-100). CC BY 4.0 - credit: Worldwide Governance Indicators, 2026 Update, World Bank (www.govindicators.org). Not definitive criteria for investment decisions (WGI Usage Advisory). load_wgi.py'""")
c.execute("GRANT SELECT ON core.country_governance TO cm_app_readonly")
g.commit(); print("COMMITTED")
