"""EU Critical Raw Materials Act strategic projects (106: EU lists 2025 + 2026, non-EU list 2025) -> interzona_cm.

Reads the dry-run tables in eu_crma/dryrun/ (built by eu_crma/crma_dryrun.py from the EC project table, the EC map GeoJSON and
the OCR'd project factsheets), then in ONE transaction:
  * creates core.project_designations (if missing) - CRMA-specific fields: approval date, decision, UNFC, start of production ...;
  * core.data_sources: EU_CRMA_STRATEGIC_PROJECTS;
  * docs.documents: one 'Factsheet' row per project factsheet (59);
  * core.occurrences: NEW sites (position_accuracy REGIONAL - the EC map says locations are regional-scale) + external_ids
    + occurrence_commodities; LINKED sites (incl. the 7 reviewed and accepted 2026-10-29) keep everything except project_id,
    which is set only where it is NULL (an occurrence holds one project, so GePETO gets Olen 446949, ReGAIN just points at it);
  * core.projects (106) + core.project_ownership (promoter as owner_name; company_id only for Umicore / Rio Tinto / Sibanye)
    + core.project_designations + external_ids (PROJECT);
  * fixes the few OCR typos found in the factsheet text.
Idempotent: aborts if EU_CRMA_STRATEGIC_PROJECTS external ids already exist.
Usage: python load_eu_crma.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import csv, os, sys, time
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_eu_crma_20261029"
SRC = "EU_CRMA_STRATEGIC_PROJECTS"
HERE = os.path.dirname(os.path.abspath(__file__))
DRYDIR = os.path.join(HERE, "eu_crma", "dryrun")
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
OCR_FIXES = {"C02GRAPHlTE": "CO2GRAPHITE", "ReGAlN": "ReGAIN", "LIFE22-ENV-lT-lNSPlREE": "LIFE22-ENV-IT-INSPIREE",
             "T e Pulawy": "The Pulawy"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fix(s):
    for a, b in OCR_FIXES.items():
        s = s.replace(a, b)
    return s


def read(name):
    return list(csv.DictReader(open(os.path.join(DRYDIR, name + ".csv"), encoding="utf-8-sig")))


def nz(v):
    return None if v in ("", None) else v


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                     user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")


def one(sql, args=()):
    c.execute(sql, args); return c.fetchall()


if one("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,))[0][0]:
    sys.exit("EU_CRMA external ids already present - already loaded, aborting")

projects, docs, occ_new = read("projects"), read("documents"), read("occurrences_new")
occ_link, occ_comm, own = read("occurrences_linked"), read("occurrence_commodities"), read("project_ownership")
desig, ds, sites = read("project_designations"), read("data_sources")[0], read("site_decisions")

# 1. designations table
c.execute(open(os.path.join(DRYDIR, "project_designations_ddl.sql")).read().replace(
    "CREATE TABLE core.project_designations", "CREATE TABLE IF NOT EXISTS core.project_designations"))
c.execute("COMMENT ON TABLE core.project_designations IS 'Official programme designations of a project (e.g. EU CRMA strategic project): approval, decision reference and programme-specific attributes as published'")

# 2. data source
LICENCE_STATUS = ("Factsheets: CC BY 4.0 stated on each factsheet (checked 2026-10-28). Web table and map: covered by the "
                  "Commission reuse policy (Decision 2011/833/EU, CC BY 4.0 by default under the europa.eu legal notice) - "
                  "not separately confirmed for this page. Loaded 2026-10-29 (106 projects).")
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required,
             attribution_text, is_loaded, licence_status, caveats, evidence_location, evidence_date, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (SRC, ds["publisher"], ds["dataset_name"], ds["licence"], "https://creativecommons.org/licenses/by/4.0/", True,
           ds["attribution_text"], True, LICENCE_STATUS, ds["caveats"], ds["evidence_location"], ds["evidence_date"], TAG))

# 3. factsheet documents
doc_id = {}
for d in docs:
    c.execute("""INSERT INTO docs.documents (title, domain, document_type, company_id, commodity_id, jurisdiction_id, source_url,
                 page_count, language, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING document_id""",
              (fix(d["title"]), d["domain"], d["document_type"], nz(d["company_id"]), nz(d["commodity_id"]),
               nz(d["jurisdiction_id"]), d["source_url"], 1, "en", TAG))
    doc_id[d["tmp_key"]] = c.fetchone()[0]
log("documents", len(doc_id))

# 4. new occurrences + external ids + commodities
occ_id = {}
for o in occ_new:
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, geom, jurisdiction_id, company_id, status, workings_type,
                 position_accuracy, commodities, comments, created_by)
                 VALUES (%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,%s,%s,%s::text[],%s,%s) RETURNING occurrence_id""",
              (fix(o["name"]), o["is_deposit"] == "True", float(o["lon"]), float(o["lat"]), int(o["jurisdiction_id"]),
               nz(o["company_id"]), o["status"], nz(o["workings_type"]), o["position_accuracy"], o["commodities"],
               fix(o["comments"]), TAG))
    occ_id[o["tmp_key"]] = c.fetchone()[0]
execute_values(c, """INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by)
                     VALUES %s""", [("OCCURRENCE", v, SRC, k, "EXACT", TAG) for k, v in occ_id.items()])
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, created_by) VALUES %s",
               [(occ_id[x["occurrence"]], int(x["commodity_id"]), x["commodity_role"], TAG) for x in occ_comm])
log("occurrences new", len(occ_id))


def resolve(ref):
    kind, key = ref.split(":", 1)
    return int(key) if kind == "occ" else occ_id[key]


# 5. projects (row order = proj_idx in site_decisions / occurrences_linked)
proj_id = {}
for i, p in enumerate(projects):
    c.execute("""INSERT INTO core.projects (company_id, name, jurisdiction_id, status, primary_commodity_id, description,
                 occurrence_id, asset_type, source_document_id, source_page, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING project_id""",
              (nz(p["company_id"]), fix(p["name"]), int(p["jurisdiction_id"]), p["status"], nz(p["primary_commodity_id"]),
               nz(fix(p["description"])), resolve(p["occurrence"]) if p["occurrence"] else None, p["asset_type"],
               doc_id.get(p["source_document"]), 1 if p["source_document"] else None, TAG))
    proj_id[p["tmp_key"]] = c.fetchone()[0]
pkeys = [p["tmp_key"] for p in projects]
log("projects", len(proj_id))

# 6. occurrences -> project_id (new: all sites; linked: only where still NULL, in project order)
for k, v in occ_id.items():
    c.execute("UPDATE core.occurrences SET project_id = %s WHERE occurrence_id = %s", (proj_id[k.split("#")[0]], v))
linked_set = 0
for x in occ_link:
    c.execute("""UPDATE core.occurrences SET project_id = %s, modified_by = %s, modified_date = now()
                 WHERE occurrence_id = %s AND project_id IS NULL""", (proj_id[pkeys[int(x["proj_idx"])]], TAG, int(x["occurrence_id"])))
    linked_set += c.rowcount
log("linked occurrences given a project_id", linked_set, "of", len(occ_link))

# 7. documents -> project, ownership, designations, project external ids
for d in docs:
    c.execute("UPDATE docs.documents SET project_id = %s WHERE document_id = %s", (proj_id[d["project"]], doc_id[d["tmp_key"]]))
execute_values(c, """INSERT INTO core.project_ownership (project_id, company_id, owner_name, as_of_year, source_document_id,
                     source_page, created_by) VALUES %s""",
               [(proj_id[o["project"]], nz(o["company_id"]), o["owner_name"], int(o["as_of_year"]),
                 doc_id.get(o["source_document"]), 1 if o["source_document"] else None, TAG) for o in own])
cols = ["programme", "scope", "approval_date", "decision_ref", "value_chain_stage", "materials_as_published",
        "promoter_as_published", "promoter_factsheet", "countries_as_published", "unfc_classification",
        "est_start_production", "website", "eu_benefit", "factsheet_doi", "factsheet_url"]
doc_by_url = {d["source_url"]: doc_id[d["tmp_key"]] for d in docs}
execute_values(c, f"""INSERT INTO core.project_designations (project_id, {', '.join(cols)}, source_document_id, created_by) VALUES %s""",
               [tuple([proj_id[x["project"]]] + [nz(fix(x[k])) for k in cols] + [doc_by_url.get(x["factsheet_url"]), TAG])
                for x in desig])
execute_values(c, """INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by)
                     VALUES %s""", [("PROJECT", v, SRC, k, "EXACT", TAG) for k, v in proj_id.items()])

# 8. verify
checks = {
    "projects": ("SELECT count(*) FROM core.projects WHERE created_by = %s", 106),
    "projects with occurrence": ("SELECT count(*) FROM core.projects WHERE created_by = %s AND occurrence_id IS NOT NULL", 106),
    "designations": ("SELECT count(*) FROM core.project_designations WHERE created_by = %s", 106),
    "ownership": ("SELECT count(*) FROM core.project_ownership WHERE created_by = %s", 106),
    "documents": ("SELECT count(*) FROM docs.documents WHERE created_by = %s AND project_id IS NOT NULL", 59),
    "occurrences new": ("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND project_id IS NOT NULL", len(occ_new)),
    "occurrences new w/o country": ("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND country_name IS NULL", 0),
    "linked modified": ("SELECT count(*) FROM core.occurrences WHERE modified_by = %s", len(occ_link) - 1),
    "external ids": ("SELECT count(*) FROM core.external_ids WHERE created_by = %s", len(occ_new) + 106),
    "occurrence_commodities": ("SELECT count(*) FROM core.occurrence_commodities WHERE created_by = %s", len(occ_comm)),
}
ok = True
for name, (sql, want) in checks.items():
    got = one(sql, (TAG,))[0][0]
    ok &= got == want
    log(f"check {name}: {got} (expected {want})", "" if got == want else "  <-- MISMATCH")

if DRY or not ok:
    g.rollback(); log("DRY RUN - rolled back" if DRY else "CHECK FAILED - rolled back")
    log("after rollback: tagged projects (must be 0)", one("SELECT count(*) FROM core.projects WHERE created_by = %s", (TAG,))[0][0])
else:
    g.commit(); log("COMMITTED")
