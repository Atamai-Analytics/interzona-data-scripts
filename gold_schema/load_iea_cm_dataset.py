"""IEA Critical Minerals Dataset 2026 (Global Critical Minerals Outlook 2026 / Critical Minerals Data Explorer) -> markets.iea_cm_supply, markets.iea_cm_demand.

Source file: D:/CriticalMineralsDB/IEA/IEA Critical Minerals Dataset 2026.xlsx (downloaded by the user 2026-11-21 from iea.org).
Licence (Notice sheet): Creative Commons Attribution 4.0 (CC BY 4.0). Credit: "IEA (2026), Critical Minerals Data Explorer / Global Critical Minerals
Outlook 2026, IEA, Paris, https://www.iea.org/data-and-statistics/data-tools/critical-minerals-data-explorer, Licence: CC BY 4.0"
(the file's notice still says "IEA (2024)", an old template).

markets.iea_cm_supply  - sheet "2 Total supply": base-case PROJECTED supply (kt) by country, 2025/2030/2035/2040, for copper, cobalt, lithium,
                         nickel, graphite and magnet rare earths, mining and refining (graphite: natural mining and battery-grade). Top six countries,
                         'Rest of world' and 'Total' rows as published, plus the published top-3 share. Base case = operating and announced
                         projects weighted by their probability of coming online (financing, permitting, feasibility).
markets.iea_cm_demand  - sheets "1 Total demand" (key minerals by sector incl. other uses and total demand), "3.1 by tech" (all minerals x
                         technology) and "3.2 by mineral" (energy-technology demand for ~35 minerals): kt by scenario (Current Policies, Stated
                         Policies, High Demand) and year 2030-2050, plus the 2025 base year. Sheets 4.x (technology cases) are not loaded.
Usage: python -P load_iea_cm_dataset.py [--dry] | --undo
"""
import os, re, sys
import openpyxl, psycopg2
from psycopg2.extras import execute_values

SRC = "D:/CriticalMineralsDB/IEA/IEA Critical Minerals Dataset 2026.xlsx"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
if "--undo" in sys.argv:
    c.execute("DROP TABLE IF EXISTS markets.iea_cm_supply"); c.execute("DROP TABLE IF EXISTS markets.iea_cm_demand"); g.commit(); sys.exit("dropped")

wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
MINERAL_KEY = {"Copper": "copper", "Cobalt": "cobalt", "Lithium": "lithium", "Nickel": "nickel", "Graphite": "graphite", "Magnet rare earth elements": "rare_earths"}

# ---- supply ---------------------------------------------------------------------------------------------------------------------------
rows = [list(r) for r in wb["2 Total supply for key minerals"].iter_rows(values_only=True)]
years = [v for v in rows[3] if num(v)][:4]
supply = []
cur = {}
for r in rows:
    if not any(v not in (None, "") for v in r): continue
    for side, off in (("L", 0), ("R", 6)):
        label = r[off] if off < len(r) else None
        if isinstance(label, str) and " - " in label and not any(num(v) for v in r[off + 1:off + 5]):
            m, st = label.split(" - ", 1)
            cur[side] = (MINERAL_KEY.get(m.strip(), m.strip().lower()), m.strip(), st.strip())
            continue
        if side in cur and isinstance(label, str) and all(num(v) for v in r[off + 1:off + 5]):
            key, mname, st = cur[side]
            kind = "top3_share" if label.startswith("Top 3 share") else "total" if label.startswith("Total") else "rest_of_world" if label == "Rest of world" else "country"
            for y, v in zip(years, r[off + 1:off + 5]):
                supply.append((key, mname, st, label.strip(), kind, int(y), float(v)))
print("supply rows", len(supply), "groups", len({(s[0], s[2]) for s in supply}))

# ---- demand ---------------------------------------------------------------------------------------------------------------------------
def demand_sheet(name, table, mineral_from_header):
    out = []
    rs = [list(r) for r in wb[name].iter_rows(values_only=True)]
    hdr_i = next(i for i, r in enumerate(rs) if any(isinstance(v, str) and "Current Policies" in v for v in r))
    scen_row, year_row = rs[hdr_i], rs[hdr_i + 1]
    cols = {}
    scen = "Base year"
    for j, y in enumerate(year_row):
        if isinstance(scen_row[j] if j < len(scen_row) else None, str) and "scenario" in scen_row[j].lower(): scen = scen_row[j].strip()
        if num(y): cols[j] = ("Base year 2025" if j == 1 else scen, int(y))
    mineral = None
    for r in rs[hdr_i + 2:]:
        lab = r[0]
        if not isinstance(lab, str): continue
        vals = {j: r[j] for j in cols if j < len(r) and num(r[j])}
        if lab.startswith("Notes"): break
        if not vals:
            if mineral_from_header: mineral = re.sub(r"\s*\(.*\)$", "", lab.strip())
            continue
        unit = "share" if lab.lower().startswith("share") else "kt"
        if mineral_from_header:
            min_name, sector = mineral, lab.strip()
        else:
            min_name, sector = lab.strip(), "Total energy technologies"
        for j, v in vals.items():
            s, y = cols[j]
            out.append((table, min_name, sector, s, y, float(v), unit))
    return out

demand = demand_sheet("1 Total demand for key minerals", "key minerals: total demand by sector", True)
demand += demand_sheet("3.1 Energy demand by tech", "energy technologies: by mineral and technology", True)
demand += demand_sheet("3.2 Energy demand by mineral", "energy technologies: by mineral", False)
print("demand rows", len(demand), "minerals", len({d[1] for d in demand}), "scenarios", sorted({d[3] for d in demand}))
for chk in [("Lithium", "Total demand", "Stated Policies scenario", 2040), ("Copper", "Total demand", "Base year 2025", 2025)]:
    print("check", chk, [d[5] for d in demand if d[1] == chk[0] and d[2] == chk[1] and d[3] == chk[2] and d[4] == chk[3]])
if "--dry" in sys.argv: sys.exit("DRY")

c.execute("""CREATE TABLE IF NOT EXISTS markets.iea_cm_supply (mineral_key text NOT NULL, mineral text NOT NULL, stage text NOT NULL, country text NOT NULL,
             iso3 char(3), row_kind text NOT NULL, year int NOT NULL, value float8 NOT NULL, unit text NOT NULL DEFAULT 'kt', case_name text NOT NULL DEFAULT 'base case',
             release text NOT NULL DEFAULT 'IEA Global Critical Minerals Outlook 2026', PRIMARY KEY (mineral_key, stage, country, year))""")
c.execute("""CREATE TABLE IF NOT EXISTS markets.iea_cm_demand (source_table text NOT NULL, mineral text NOT NULL, sector text NOT NULL, scenario text NOT NULL,
             year int NOT NULL, value float8 NOT NULL, unit text NOT NULL, release text NOT NULL DEFAULT 'IEA Global Critical Minerals Outlook 2026',
             PRIMARY KEY (source_table, mineral, sector, scenario, year))""")
c.execute("TRUNCATE markets.iea_cm_supply, markets.iea_cm_demand")
execute_values(c, "INSERT INTO markets.iea_cm_supply (mineral_key, mineral, stage, country, row_kind, year, value, unit) VALUES %s",
               [(k, m, st, ctry, kind, y, v, "share" if kind == "top3_share" else "kt") for (k, m, st, ctry, kind, y, v) in supply])
c.execute("UPDATE markets.iea_cm_supply SET iso3 = core.iso3_of(CASE country WHEN 'Korea' THEN 'South Korea' ELSE country END) WHERE row_kind = 'country'")
c.execute("SELECT DISTINCT country FROM markets.iea_cm_supply WHERE row_kind = 'country' AND iso3 IS NULL"); miss = c.fetchall()
assert not miss, f"unmapped countries: {miss}"
execute_values(c, "INSERT INTO markets.iea_cm_demand (source_table, mineral, sector, scenario, year, value, unit) VALUES %s", demand, page_size=2000)
credit = "IEA (2026), Critical Minerals Data Explorer / Global Critical Minerals Outlook 2026, IEA, Paris, Licence: CC BY 4.0"
c.execute(f"COMMENT ON TABLE markets.iea_cm_supply IS 'IEA base-case projected mining and refining supply by country 2025-2040 (top 6 + rest of world + total). {credit}. load_iea_cm_dataset.py'")
c.execute(f"COMMENT ON TABLE markets.iea_cm_demand IS 'IEA mineral demand by scenario (CPS/STEPS/High Demand) and sector/technology, 2025-2050. {credit}. load_iea_cm_dataset.py'")
for t in ("markets.iea_cm_supply", "markets.iea_cm_demand"): c.execute(f"GRANT SELECT ON {t} TO cm_app_readonly")
g.commit(); print("COMMITTED")
