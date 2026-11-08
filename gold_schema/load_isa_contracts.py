"""ISA exploration contracts (International Seabed Authority) -> interzona_cm core.isa_exploration_contracts (new table).

Source: the ISA's public contractor pages (https://www.isa.org.jm/exploration-contracts/ and the nodule, sulphide and cobalt-crust pages),
saved 2026-11-07 to D:/CriticalMineralsDB/Seabed/download_20261107/isa and parsed to isa_contracts_parsed.csv (32 rows).
Only the factual particulars are taken (contractor, sponsoring state, dates, location). Pages were last modified 2025-11-17 (nodules),
2025-11-14 (crusts) and 2026-03-13 (sulphides), so extensions decided after those dates are not shown: a listed expiry that has passed is
recorded as 'EXPIRY_PASSED_AS_LISTED', never as 'expired'.
Usage: python load_isa_contracts.py [--dry]   (--dry = create + load + verify, ROLLBACK; DDL is transactional)
"""
import csv, os, re, sys, time, datetime
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_isa_contracts_20261107"
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = "D:/CriticalMineralsDB/Seabed/download_20261107/isa/isa_contracts_parsed.csv"
TODAY = datetime.date(2026, 11, 7)
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


RES = {"polymetallic-nodules": ("POLYMETALLIC_NODULES", "2025-11-17"), "polymetallic-sulphides": ("POLYMETALLIC_SULPHIDES", "2026-03-13"),
       "cobalt-rich-ferromanganese-crusts": ("COBALT_RICH_CRUSTS", "2025-11-14")}
URL = "https://www.isa.org.jm/exploration-contracts/{}/"
STATE_CONTRACTOR = [(r"russian federation", "Russian Federation"), (r"republic of korea", "Republic of Korea"), (r"\bindia\b", "India"), (r"poland", "Poland")]
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def dates(s):
    out = []
    for d, m, y in re.findall(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", s or ""):
        out.append(datetime.date(int(y), MON[m[:3].lower()], int(d)))
    return out


def ocean(loc):
    l = loc.lower()
    if "clarion" in l: return "Clarion-Clipperton Zone, Pacific Ocean"
    if "pacific" in l or "magellan" in l: return "Western Pacific Ocean"
    if "indian" in l: return "Indian Ocean"
    if "atlantic" in l or "rio grande" in l: return "Atlantic Ocean"
    return loc


rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
recs = []
for r in rows:
    res, page_date = RES[r["resource"]]
    contractor = r["Contractor"].strip()
    sp = (r["Sponsoring State"] or "").strip()
    is_state = sp in ("", "–", "-")
    if is_state:
        states = [v for rx, v in STATE_CONTRACTOR if re.search(rx, contractor, re.I)]
        assert states, contractor
    else:
        sp = sp.replace("United Kingdom of Great Britain and Northern Ireland", "United Kingdom")
        states = [s.strip() for s in re.split(r",| and ", sp) if s.strip()]
    start = dates(r["Contract Date"])[0]
    exp_txt = r["Expiration Date"].strip()
    terminated = "termination" in exp_txt.lower()
    exp = dates(exp_txt)
    ext_txt = (r.get("Contract Extension Expiration") or "").strip()
    ext = dates(ext_txt)
    latest = max(exp + ext)
    if terminated: st = "TERMINATED"
    elif latest >= TODAY: st = "ACTIVE_AS_LISTED"
    else: st = "EXPIRY_PASSED_AS_LISTED"
    recs.append(dict(contractor=contractor, resource_type=res, sponsoring_states=states, contractor_is_state=is_state, location=r["Location"].strip(),
                     ocean_region=ocean(r["Location"]), contract_date=start, original_expiry=None if terminated else exp[0],
                     terminated_date=exp[0] if terminated else None, extensions_as_listed=ext_txt or None, latest_listed_expiry=None if terminated else latest,
                     listed_status=st, source_url=URL.format(r["resource"]), source_page_modified=page_date))
log("contracts", len(recs), {s: sum(1 for x in recs if x["listed_status"] == s) for s in ("ACTIVE_AS_LISTED", "EXPIRY_PASSED_AS_LISTED", "TERMINATED")})

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT to_regclass('core.isa_exploration_contracts')"); assert c.fetchone()[0] is None, "table already exists"
c.execute("""
CREATE TABLE core.isa_exploration_contracts (
  contract_id            serial PRIMARY KEY,
  contractor             text NOT NULL,
  resource_type          text NOT NULL CHECK (resource_type IN ('POLYMETALLIC_NODULES','POLYMETALLIC_SULPHIDES','COBALT_RICH_CRUSTS')),
  sponsoring_states      text[] NOT NULL,
  contractor_is_state    boolean NOT NULL,
  location               text,
  ocean_region           text,
  contract_date          date NOT NULL,
  original_expiry        date,
  extensions_as_listed   text,
  latest_listed_expiry   date,
  terminated_date        date,
  listed_status          text NOT NULL CHECK (listed_status IN ('ACTIVE_AS_LISTED','EXPIRY_PASSED_AS_LISTED','TERMINATED')),
  source_url             text NOT NULL,
  source_page_modified   date NOT NULL,
  retrieved_date         date NOT NULL DEFAULT '2026-11-07',
  is_active              boolean NOT NULL DEFAULT true,
  created_by             text NOT NULL,
  created_date           timestamptz NOT NULL DEFAULT now()
)""")
c.execute("""COMMENT ON TABLE core.isa_exploration_contracts IS 'International Seabed Authority exploration contracts in the Area (international seabed), as listed on the ISA contractor pages retrieved 2026-11-07. listed_status is relative to the page: ISA pages were last modified before some 2026 expiry/extension decisions, so EXPIRY_PASSED_AS_LISTED means the listed expiry has passed and any later extension is not shown. Exploration contracts only; no exploitation contract has been issued.'""")
c.execute("GRANT SELECT ON core.isa_exploration_contracts TO cm_app_readonly")
execute_values(c, """INSERT INTO core.isa_exploration_contracts (contractor, resource_type, sponsoring_states, contractor_is_state, location, ocean_region, contract_date,
                     original_expiry, extensions_as_listed, latest_listed_expiry, terminated_date, listed_status, source_url, source_page_modified, created_by) VALUES %s""",
               [(r["contractor"], r["resource_type"], r["sponsoring_states"], r["contractor_is_state"], r["location"], r["ocean_region"], r["contract_date"],
                 r["original_expiry"], r["extensions_as_listed"], r["latest_listed_expiry"], r["terminated_date"], r["listed_status"], r["source_url"],
                 r["source_page_modified"], TAG) for r in recs])
c.execute("SELECT resource_type, listed_status, count(*) FROM core.isa_exploration_contracts GROUP BY 1, 2 ORDER BY 1, 2"); log("by type/status", c.fetchall())
c.execute("SELECT contractor, resource_type, latest_listed_expiry, listed_status FROM core.isa_exploration_contracts WHERE listed_status <> 'ACTIVE_AS_LISTED' ORDER BY latest_listed_expiry")
for x in c.fetchall(): log("   ", x)
c.execute("SELECT s, count(*) FROM core.isa_exploration_contracts, unnest(sponsoring_states) s WHERE listed_status <> 'TERMINATED' GROUP BY 1 ORDER BY 2 DESC"); log("sponsoring states", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back (table not created)")
else:
    g.commit(); log("COMMITTED")
