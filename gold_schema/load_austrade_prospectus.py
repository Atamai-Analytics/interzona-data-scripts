"""Australian Critical Minerals Prospectus (Austrade, October 2026): 94 projects -> interzona_cm (part 2: structured data; part 1, the library chunks, is ingest_austrade_prospectus.py).

In ONE transaction:
  * creates core.project_prospectus (if missing): each project's facts AS PUBLISHED (status, offtake, mine life, IRR, capital cost, NPV, products, resource / reserve tables as printed, no unit
    conversion, source and licence) - 94 rows;
  * core.data_sources: AUSTRADE_CRITICAL_MINERALS_PROSPECTUS;
  * core.companies: the companies not already held (a single named company only; joint ventures keep the published text as owner_name);
  * core.projects: NEW projects for those not already held; 5 Prospectus entries link to existing projects (see EXISTING) and create nothing;
  * core.project_ownership (owner_name as published, company_id where there is one), core.external_ids (PROJECT), core.occurrences.project_id for the 2 unambiguous catalogue matches;
  * docs.document_chunks of the Prospectus document (370): project_id / company_id filled in.
Not done (stated in the review): no coordinates (the Prospectus gives none), so new projects have no geometry; status is left empty (the published status text is in core.project_prospectus).
Idempotent: aborts if the external ids already exist. Usage: python load_austrade_prospectus.py --dry | --run   (--dry = load, verify, ROLLBACK)
"""
import sys, os, re, json, csv, time
sys.stdout.reconfigure(encoding="utf8")
import psycopg2
from psycopg2.extras import execute_values, Json

DRY = "--dry" in sys.argv
if not DRY and "--run" not in sys.argv:
    sys.exit(__doc__)
TAG = "migration_austrade_prospectus_20261029"
SRC = "AUSTRADE_CRITICAL_MINERALS_PROSPECTUS"
DOC_ID = 370
HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(HERE, "austrade")   # inputs kept with the script (prospectus_projects_all.json, austrade_company_boxes_vision.json); the plan CSV is written here too
SOURCE_URL = "https://international.austrade.gov.au/en/do-business-with-australia/sectors/energy-and-resources/critical-minerals/prospectus"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


pj = json.load(open(os.path.join(SP, "prospectus_projects_all.json"), encoding="utf8"))
vis = {r["project"]: r for r in json.load(open(os.path.join(SP, "austrade_company_boxes_vision.json"), encoding="utf8"))["projects"]}

# Prospectus entries that ARE projects we already hold (checked by hand against core.projects, 2026-10-29): (stage, name) -> project_id
EXISTING = {("upstream", "Nolans Rare Earths Project"): 34, ("midstream", "Nolans Rare Earths Project – Processing Facility"): 34,
            ("upstream", "Donald Rare Earth and Mineral Sands Project"): 136, ("midstream", "Eneabba Rare Earths Refinery"): 127,
            ("midstream", "Lynas Rare Earths Processing Facilities"): 22}
# unambiguous catalogue matches (one occurrence only): (stage, name) -> occurrence_id.  Mount Carbine (322577 / 488411) and Mt Mulgine (488967 / 576176) have two records each and are left for review.
OCC = {("upstream", "Dubbo Project"): 3809, ("upstream", "North Stanmore"): 3811}
# companies already held although the published name differs: normalised published name -> company_id
COMPANY_ALIAS = {"albemarlecorporatio": 9, "albemarlecorporation": 9, "riotinto": 32}
COMMODITY = {"antimony": 1146, "bismuth": 1081, "cobalt": 1105, "nickel": 1107, "fluorine": 991, "graphite": 994, "high purity alumina": 1051, "lithium": 1089, "manganese": 1112,
             "platinum group elements": 1126, "rare earth elements": 1123, "scandium": 1096, "silicon": 974, "titanium": 1113, "tungsten": 1103, "vanadium": 1114, "zircon": 1021,
             "gallium": 1084, "germanium": 1145, "magnesium": 1090, "niobium": 1092, "tin": 1097, "silica": 974}
clean_ws = lambda s: re.sub(r"\s+", " ", (s or "").replace("\t", " ")).strip()


def clean_company(n):
    n = clean_ws(n)
    n = re.sub(r"\s*\((?:Core|Atlantic|Wyloo|UltraHPQ|ASM|[A-Z]{2,5})\)\s*", " ", n).strip()
    return clean_ws(n)


def nkey(n):
    n = clean_company(n).lower()
    n = re.sub(r"\b(limited|ltd|pty|inc|corp|corporation|nl|plc|the)\b", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def is_multi(n):
    return bool(re.search(r"\band\b|,|joint venture|\bjv\b|\bplc\b.*—|unincorporated| & ", n, re.I)) or len(n) > 70


def ticker_of(own):
    m = re.search(r"(ASX|NYSE|TSXV|TSX-V|TSX)[^()]*\(([A-Z0-9]{2,5})\)", own or "")
    return (m.group(2), "ASX" if m.group(1) == "ASX" else m.group(1).replace("-", "")) if m else (None, None)


def stage_asset(p):
    n = p["name"].lower()
    if p["stage"] == "upstream":
        return "PROJECT"
    if "recycl" in n:
        return "RECYCLING"
    return "REFINERY" if "refin" in n else "PROCESSING"


def first_commodity(p):
    s = (p["commodities"] or "").lower() or ""
    if not s:  # midstream: from the company table
        t = next((t for t in p["tables"] if t and t[0] and t[0][0].lower().startswith("company name")), None)
        s = ({r[0].rstrip(":").lower(): r[1] for r in (t or []) if len(r) >= 2}).get("critical mineral(s)", "").lower()
    first = re.split(r"[,\n]", s)[0].strip()
    return COMMODITY.get(first) or COMMODITY.get(re.sub(r"\s+", " ", first))


def kv_status(tables):
    out = {}
    for t in tables:
        if t and len(t[0]) == 2 and (t[0][0].lower().startswith("project status") or any(r[0].lower().startswith(("offtake", "irr", "npv", "capital")) for r in t)):
            for r in t:
                if len(r) >= 2 and r[0]:
                    out[r[0].strip().lower()] = r[1].strip()
    return out


recs = []
for p in pj:
    midd = {}
    if p["stage"] == "midstream":
        t = next((t for t in p["tables"] if t and t[0] and t[0][0].lower().startswith("company name")), None)
        midd = {r[0].rstrip(":").lower(): r[1] for r in (t or []) if len(r) >= 2}
        company, own, web = midd.get("company name", ""), midd.get("company ownership", ""), (t[-1][0] if t and "." in t[-1][0] and len(t[-1]) >= 1 and ":" not in t[-1][0] else "")
        state = midd.get("state or territory", "")
        commod = midd.get("critical mineral(s)", "")
    else:
        v = vis.get(p["name"], {})
        company, own, web, state, commod = v.get("company", ""), v.get("listing_ownership", ""), v.get("website", ""), v.get("state_box") or p["state"], p["commodities"]
    st = kv_status(p["tables"])
    res = [t for t in p["tables"] if t and t[0] and re.match(r"resource", t[0][0], re.I)]
    rsv = [t for t in p["tables"] if t and t[0] and re.match(r"reserve", t[0][0], re.I)]
    oth = [t for t in p["tables"] if t not in res and t not in rsv and not (t and len(t[0]) == 2 and (t[0][0].lower().startswith("project status") or t[0][0].lower().startswith("company name") or any(r[0].lower().startswith(("offtake", "irr", "npv", "capital")) for r in t)))]
    sec = p["sections"]
    recs.append(dict(p=p, stage=p["stage"], name=p["name"], company=clean_company(company), own=clean_ws(own), web=clean_ws(web), state=clean_ws(state or p["state"]), commod=clean_ws(commod),
                     status=st.get("project status", ""), offtake=st.get("offtake", ""), life=st.get("min mine life (yrs)", ""), irr=st.get("irr", ""), capex=st.get("capital cost", ""), npv=st.get("npv", ""),
                     products=st.get("product & average annual production rate", "") or st.get("product and average annual production rate", "") or sec.get("Midstream Products & Annual Production Rate", "").strip(),
                     summary=(sec.get("Investment summary", "") or sec.get("Midstream summary", "")).strip(), descr=(sec.get("Project description", "") or sec.get("Midstream Project Description", "")).strip(),
                     res=res, rsv=rsv, oth=oth, page=None))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")


def one(sql, args=()):
    c.execute(sql, args); return c.fetchall()


if one("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,))[0][0]:
    sys.exit("Austrade Prospectus external ids already present - already loaded, aborting")

# 1. facts table ----------------------------------------------------------------------------------------------------------------------------------
c.execute("""CREATE TABLE IF NOT EXISTS core.project_prospectus (
  prospectus_project_id serial PRIMARY KEY, project_id integer REFERENCES core.projects(project_id), edition text NOT NULL, stage text NOT NULL,
  name_as_published text NOT NULL, state_as_published text, commodities_as_published text, company_as_published text, ownership_as_published text, website text, page_number integer,
  project_status text, offtake text, min_mine_life text, irr text, capital_cost text, npv text, products text, investment_summary text, project_description text,
  resource_tables jsonb, reserve_tables jsonb, other_tables jsonb, source_document_id bigint, source_url text, licence text, attribution text,
  created_by varchar NOT NULL DEFAULT CURRENT_USER, created_date timestamptz NOT NULL DEFAULT now())""")
c.execute("COMMENT ON TABLE core.project_prospectus IS 'Project facts exactly as published in the Austrade Australian Critical Minerals Prospectus (company-supplied, not verified by Austrade); tables as printed, no unit conversion.'")
c.execute("GRANT SELECT ON core.project_prospectus TO cm_app_readonly")
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded, licence_status, caveats, evidence_location, evidence_date, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (SRC, "Australian Trade and Investment Commission (Austrade)", "Australian Critical Minerals Prospectus, October 2026 (94 projects)", "CC BY 4.0",
           "https://creativecommons.org/licenses/by/4.0/", True, "Austrade, Australian Critical Minerals Prospectus (October 2026), Commonwealth of Australia, CC BY 4.0",
           True, "Site disclaimer (austrade.gov.au/en/site-information/site-disclaimer, read 2026-10-29): unless otherwise noted, content is licensed CC BY 4.0, excluding the Coat of Arms, logos, third-party material, trademarks, images and photographs. Company-supplied data may include third-party material.",
           "Company-supplied figures, not verified by Austrade; Austrade states there are more projects than listed. No coordinates published. AUD unless stated.", SOURCE_URL, "2026-10-29", TAG))

# 2. companies --------------------------------------------------------------------------------------------------------------------------------------
c.execute("SELECT company_id, name FROM core.companies WHERE is_active")
held = {nkey(n): i for i, n in c.fetchall()}
held.update(COMPANY_ALIAS)
new_co, co_id = {}, {}
for r in recs:
    if not r["company"] or is_multi(r["company"]):
        continue
    k = nkey(r["company"])
    if k in held:
        co_id[k] = held[k]
    elif k not in new_co:
        tk, ex = ticker_of(r["own"])
        new_co[k] = (r["company"], tk, ex, r["web"] or None, "ASX-listed" in r["own"] or "Australian" in r["own"])
for k, (name, tk, ex, web, au) in new_co.items():
    c.execute("INSERT INTO core.companies (name, ticker, exchange, website, hq_jurisdiction_id, created_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING company_id",
              (name, tk, ex, web, 771 if au else None, TAG))
    co_id[k] = c.fetchone()[0]
log("companies new", len(new_co), "| existing used", len({v for v in co_id.values()} - set(co_id[k] for k in new_co)))

# 3. projects -----------------------------------------------------------------------------------------------------------------------------------------
proj = {}
for r in recs:
    key = (r["stage"], r["name"])
    if key in EXISTING:
        proj[key] = EXISTING[key]
        continue
    cid = co_id.get(nkey(r["company"])) if r["company"] and not is_multi(r["company"]) else None
    c.execute("""INSERT INTO core.projects (company_id, name, jurisdiction_id, status, primary_commodity_id, description, occurrence_id, asset_type, source_document_id, created_by)
                 VALUES (%s,%s,771,NULL,%s,%s,%s,%s,%s,%s) RETURNING project_id""",
              (cid, r["name"], first_commodity(r["p"]), (r["summary"][:600] or None), OCC.get(key), stage_asset(r["p"]), DOC_ID, TAG))
    proj[key] = c.fetchone()[0]
n_new = sum(1 for k, v in proj.items() if k not in EXISTING)
log("projects new", n_new, "| linked to existing", len(EXISTING))
for key, oid in OCC.items():
    c.execute("UPDATE core.occurrences SET project_id = %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s AND project_id IS NULL", (proj[key], TAG, oid))

# 4. facts rows, ownership, external ids --------------------------------------------------------------------------------------------------------------------
for r in recs:
    key = (r["stage"], r["name"])
    c.execute("""INSERT INTO core.project_prospectus (project_id, edition, stage, name_as_published, state_as_published, commodities_as_published, company_as_published, ownership_as_published, website, page_number,
                 project_status, offtake, min_mine_life, irr, capital_cost, npv, products, investment_summary, project_description, resource_tables, reserve_tables, other_tables,
                 source_document_id, source_url, licence, attribution, created_by)
                 VALUES (%s,'October 2026',%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'CC BY 4.0',%s,%s)""",
              (proj[key], r["stage"], r["name"], r["state"] or None, r["commod"] or None, r["company"] or None, r["own"] or None, r["web"] or None,
               r["status"] or None, r["offtake"] or None, r["life"] or None, r["irr"] or None, r["capex"] or None, r["npv"] or None, r["products"] or None, r["summary"] or None, r["descr"] or None,
               Json(r["res"]), Json(r["rsv"]), Json(r["oth"]), DOC_ID, SOURCE_URL, "Austrade, Australian Critical Minerals Prospectus (October 2026), CC BY 4.0; company-supplied, not verified by Austrade", TAG))
    k = nkey(r["company"]) if r["company"] else ""
    owner = r["company"] or None
    if key in EXISTING:
        continue          # the existing project keeps its own ownership rows
    if owner:
        c.execute("INSERT INTO core.project_ownership (project_id, company_id, owner_name, as_of_year, source_document_id, created_by) VALUES (%s,%s,%s,2026,%s,%s)",
                  (proj[key], co_id.get(k) if not is_multi(r["company"]) else None, (r["company"] + (f" ({r['own']})" if r["own"] and len(r["own"]) < 140 else ""))[:300], DOC_ID, TAG))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s",
               [("PROJECT", pid, SRC, f"{k[0]}:{k[1]}", "EXACT" if k in EXISTING else "EXACT", TAG) for k, pid in proj.items() if k not in EXISTING])

# 5. library chunks -> project / company ----------------------------------------------------------------------------------------------------------------------------
c.execute("SELECT chunk_id, content FROM docs.document_chunks WHERE document_id = %s", (DOC_ID,))
upd = 0
names = {(r["stage"], r["name"]): r for r in recs}
for cid_, content in c.fetchall():
    m = re.match(r"Australian Critical Minerals Prospectus \(Austrade, October 2026\): (.+)\nStage: (upstream|midstream) project", content)
    if not m:
        continue
    key = (m.group(2), m.group(1).strip())
    if key not in proj:
        continue
    r = names[key]
    ccid = co_id.get(nkey(r["company"])) if r["company"] and not is_multi(r["company"]) else None
    c.execute("UPDATE docs.document_chunks SET project_id = %s, company_id = %s WHERE chunk_id = %s", (proj[key], ccid, cid_))
    upd += c.rowcount
log("library chunks tagged", upd)

# 6. verify ------------------------------------------------------------------------------------------------------------------------------------------------------------
checks = {
    "project_prospectus rows": ("SELECT count(*) FROM core.project_prospectus WHERE created_by = %s", 94),
    "new projects": ("SELECT count(*) FROM core.projects WHERE created_by = %s", n_new),
    "new companies": ("SELECT count(*) FROM core.companies WHERE created_by = %s", len(new_co)),
    "external ids": ("SELECT count(*) FROM core.external_ids WHERE created_by = %s", n_new),
    "occurrences linked": ("SELECT count(*) FROM core.occurrences WHERE modified_by = %s", len(OCC)),
    "projects without a company": ("SELECT count(*) FROM core.projects WHERE created_by = %s AND company_id IS NULL", None),
    "chunks with project_id": ("SELECT count(*) FROM docs.document_chunks WHERE document_id = %s AND project_id IS NOT NULL", None),
}
ok = True
for name, (sql, want) in checks.items():
    got = one(sql, (TAG,) if "document_id" not in sql else (DOC_ID,))[0][0]
    flag = ""
    if want is not None and got != want:
        ok = False; flag = "  <-- MISMATCH"
    log(f"check {name}: {got}" + (f" (expected {want})" if want is not None else "") + flag)
with open(os.path.join(SP, "austrade_load_plan.csv"), "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh); w.writerow(["stage", "project", "state", "company", "ownership", "action", "existing_project_id", "occurrence_link", "primary_commodity_id", "status_text"])
    for r in recs:
        key = (r["stage"], r["name"])
        w.writerow([r["stage"], r["name"], r["state"], r["company"], r["own"][:80], "link existing project" if key in EXISTING else "new project", EXISTING.get(key, ""), OCC.get(key, ""), first_commodity(r["p"]) or "", r["status"][:80]])
if DRY or not ok:
    g.rollback(); log("DRY RUN - rolled back" if DRY else "CHECK FAILED - rolled back")
    log("after rollback: tagged projects (must be 0):", one("SELECT count(*) FROM core.projects WHERE created_by = %s", (TAG,))[0][0],
        "| prospectus table exists:", one("SELECT to_regclass('core.project_prospectus') IS NOT NULL")[0][0])
else:
    g.commit(); log("COMMITTED")
