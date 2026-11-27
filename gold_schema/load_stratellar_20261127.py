"""Load the licensed Stratellar (formerly SMPT) controls package into schema `stratellar` (2026-11-27).

Licence: Stratellar LLC <-> Interzona.ai L.L.C. Data License Agreement (26 Nov 2026), effective 2026-11-27, expires 2027-11-26 11:59 pm ET.
Evidence: D:/CriticalMineralsDB/Documents/Licence_Evidence/SMPT_Yang (agreement, receipt, delivery zip).
Licence rules built in here:
- The app role (cm_app_readonly) gets NO read access to the tables: it can only call two SECURITY DEFINER functions:
  stratellar.controls(material, issuer, measure_type)  -> at most 25 clause records per call, each with its dated status history, sources and credit
  stratellar.material_summary(material)                -> counts only (no record content), for the supply-risk tool
  So the AI's free SQL cannot list the dataset in bulk (agreement s.5: no bulk / reconstructable access, 25 records per extract).
- Every returned record carries the dataset version, curated-release date and legal-status as-of date (agreement s.5 attribution).
- Status "as of" the legal-status date follows the package rules: the latest DATED entry starting on or before the as-of date wins; if its
  stated end ('until') has passed with no later entry the status is 'unresolved_end_passed'; undated entries never establish a start.
- On expiry or termination: python load_stratellar_20261127.py --undo  (drops the whole schema = data, functions; no embeddings were made).

Usage: python load_stratellar_20261127.py <extracted package dir> [--dry]   |   python load_stratellar_20261127.py --undo
"""
import hashlib, json, os, sys, psycopg2
from psycopg2.extras import Json

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()

if "--undo" in sys.argv:
    c.execute("DROP SCHEMA IF EXISTS stratellar CASCADE")
    c.execute("UPDATE core.data_sources SET is_loaded = false, is_active = false WHERE source_system = 'STRATELLAR_CONTROLS'")
    g.commit(); print("schema stratellar dropped; data_sources row marked not loaded"); sys.exit()

PKG = sys.argv[1]
man = json.load(open(os.path.join(PKG, "manifest.json"), encoding="utf-8"))
data = {}
for fn, meta in man["datasets"].items():
    raw = open(os.path.join(PKG, fn), "rb").read()
    assert hashlib.sha256(raw).hexdigest() == meta["sha256"], f"checksum mismatch {fn}"
    data[fn] = json.loads(raw.decode("utf-8"))
    assert len(data[fn]) == meta["rows"], (fn, len(data[fn]), meta["rows"])
cl, ev, sh, so = (data[k] for k in ("control-clauses.json", "policy-events.json", "control-status-history.json", "sources.json"))
ev_ids, so_ids, cl_ids = {e["id"] for e in ev}, {s["id"] for s in so}, {x["id"] for x in cl}
assert len(ev_ids) == len(ev) and len(so_ids) == len(so) and len(cl_ids) == len(cl)
assert all(x["eventId"] in ev_ids for x in cl) and all(h["measureId"] in cl_ids for h in sh)
assert all(s in so_ids for x in cl for s in x["sourceIds"]) and all(h["sourceId"] in so_ids for h in sh if h.get("sourceId"))
print(f"package {man['datasetVersion'][:60]}... as of {man['legalStatusAsOf']}: {len(cl)} clauses, {len(ev)} events, {len(sh)} status rows, {len(so)} sources")
if "--dry" in sys.argv: sys.exit("dry run")

c.execute("DROP SCHEMA IF EXISTS stratellar CASCADE")
c.execute("""
CREATE SCHEMA stratellar;
COMMENT ON SCHEMA stratellar IS 'LICENSED Stratellar controls data (Stratellar LLC, agreement 26 Nov 2026, term 2026-11-27 to 2027-11-26). App role may only call the capped functions. Delete on expiry: load_stratellar_20261127.py --undo.';
CREATE TABLE stratellar.release (dataset_version text PRIMARY KEY, source_dataset_version text, source_release_id text, curated_release_date date,
  legal_status_as_of date, packaged_on date, licence_effective date, licence_expires date, attribution text, attribution_url text, coverage text, manifest jsonb);
CREATE TABLE stratellar.sources (id text PRIMARY KEY, title text, publisher text, url text, language text, date_published text, date_accessed text,
  source_type text, confidence text);
CREATE TABLE stratellar.events (id text PRIMARY KEY, event_date date, jurisdiction text, issuing_body text, document_number text, document_label text,
  policy_status text, mechanism text, affected_material_ids text[], verification_status text, superseded_by_event_id text, source_ids text[]);
CREATE TABLE stratellar.clauses (id text PRIMARY KEY, event_id text REFERENCES stratellar.events(id), issuer text, clause text, measure_type text,
  direction text, target_scopes text[], target_jurisdictions text[], material_ids text[], material_attribution text, product_codes jsonb,
  controlled_item_types text[], controlled_stages text[], legal_basis_event_ids text[], modifies_measure_ids text[], source_ids text[],
  scope_limitations jsonb);
CREATE TABLE stratellar.status_history (measure_id text REFERENCES stratellar.clauses(id), sequence int, status text, start_date date, until date,
  source_id text, PRIMARY KEY (measure_id, sequence));
""")
asof = man["legalStatusAsOf"]
c.execute("INSERT INTO stratellar.release VALUES (%s,%s,%s,%s,%s,%s,'2026-11-27','2027-11-26',%s,%s,%s,%s)",
          (man["datasetVersion"], man["sourceDatasetVersion"], man["sourceReleaseId"], man["curatedReleaseDate"], asof, man["packagedOn"],
           man["attribution"]["name"], man["attribution"]["url"], man["coverage"], Json(man)))
for s in so:
    c.execute("INSERT INTO stratellar.sources VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (s["id"], s["title"], s["publisher"], s["url"], s["language"],
              s["datePublished"], s["dateAccessed"], s["sourceType"], s["confidence"]))
for e in ev:
    c.execute("INSERT INTO stratellar.events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (e["id"], e["date"], e["jurisdiction"], e["issuingBody"],
              e["documentNumber"], e["documentLabel"], e["policyStatus"], e["mechanism"], e["affectedMaterialIds"], e["verificationStatus"],
              e["supersededByEventId"], e["sourceIds"]))
for x in cl:
    c.execute("INSERT INTO stratellar.clauses VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (x["id"], x["eventId"], x["issuer"], x["clause"],
              x["measureType"], x["direction"], x["targetScopes"], x["targetJurisdictions"], x["materialIds"], x["materialAttribution"],
              Json(x["productCodes"]), x["controlledItemTypes"], x["controlledStages"], x["legalBasisEventIds"], x["modifiesMeasureIds"],
              x["sourceIds"], Json(x["scopeLimitations"])))
for h in sh:
    c.execute("INSERT INTO stratellar.status_history VALUES (%s,%s,%s,%s,%s,%s)", (h["measureId"], h["sequence"], h["status"], h.get("date"), h.get("until"), h.get("sourceId")))

c.execute("""
-- status of each clause at the legal-status as-of date (package rules; see module docstring)
CREATE VIEW stratellar.clause_status_asof AS
WITH r AS (SELECT legal_status_as_of AS asof FROM stratellar.release),
dated AS (
  SELECT DISTINCT ON (h.measure_id) h.measure_id, h.status, h.start_date, h.until
  FROM stratellar.status_history h, r WHERE h.start_date IS NOT NULL AND h.start_date <= r.asof
  ORDER BY h.measure_id, h.start_date DESC, h.sequence DESC)
SELECT cl.id AS measure_id,
       CASE WHEN d.measure_id IS NULL THEN 'undated_or_not_started'
            WHEN d.until IS NOT NULL AND d.until < r.asof THEN 'unresolved_end_passed'
            ELSE d.status END AS status_asof,
       d.status AS last_dated_status, d.start_date AS status_since, d.until AS status_until
FROM stratellar.clauses cl CROSS JOIN r LEFT JOIN dated d ON d.measure_id = cl.id;

CREATE FUNCTION stratellar._match(p_material text, mats text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $f$
  SELECT p_material IS NULL OR trim(p_material) = '' OR EXISTS (
    SELECT 1 FROM unnest(mats) m WHERE replace(m, '-', ' ') ILIKE '%' || replace(lower(trim(p_material)), '-', ' ') || '%'
       OR (lower(trim(p_material)) IN ('rare earths', 'rare earth', 'ree', 'rees') AND m IN ('rare-earth-elements', 'dysprosium', 'terbium', 'neodymium', 'praseodymium', 'ndfeb-magnets'))
       OR (lower(trim(p_material)) IN ('magnets', 'magnet', 'permanent magnets') AND m = 'ndfeb-magnets'))
$f$;

-- At most 25 clause records per call (licence s.5), newest event first, each with dated status history, sources and the required credit.
CREATE FUNCTION stratellar.controls(p_material text DEFAULT NULL, p_issuer text DEFAULT NULL, p_measure_type text DEFAULT NULL)
RETURNS TABLE (total_matching int, clause_id text, issuer text, event_date date, document_label text, issuing_body text, event_policy_status text,
  clause text, measure_type text, direction text, materials text[], target_jurisdictions text[], controlled_stages text[], controlled_item_types text[],
  product_code_count int, status_asof text, status_since date, status_until date, status_history jsonb, scope_limitations jsonb, sources jsonb,
  credit text, dataset_version text, curated_release_date date, legal_status_as_of date)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = stratellar, pg_temp AS $f$
  WITH m AS (
    SELECT cl.*, e.event_date, e.document_label, e.issuing_body, e.policy_status
    FROM stratellar.clauses cl JOIN stratellar.events e ON e.id = cl.event_id
    WHERE stratellar._match(p_material, cl.material_ids)
      AND (p_issuer IS NULL OR trim(p_issuer) = '' OR cl.issuer ILIKE trim(p_issuer) OR (lower(trim(p_issuer)) IN ('united states','usa','u.s.') AND cl.issuer = 'us'))
      AND (p_measure_type IS NULL OR trim(p_measure_type) = '' OR cl.measure_type ILIKE '%' || trim(p_measure_type) || '%'))
  SELECT (SELECT count(*) FROM m)::int, m.id, m.issuer, m.event_date, m.document_label, m.issuing_body, m.policy_status, m.clause, m.measure_type,
         m.direction, m.material_ids, m.target_jurisdictions, m.controlled_stages, m.controlled_item_types, jsonb_array_length(m.product_codes),
         s.status_asof, s.status_since, s.status_until,
         (SELECT jsonb_agg(jsonb_build_object('status', h.status, 'from', h.start_date, 'until', h.until) ORDER BY h.sequence)
            FROM stratellar.status_history h WHERE h.measure_id = m.id),
         m.scope_limitations,
         (SELECT jsonb_agg(jsonb_build_object('title', so.title, 'publisher', so.publisher, 'url', so.url, 'type', so.source_type))
            FROM stratellar.sources so WHERE so.id = ANY(m.source_ids)),
         'Stratellar - stratellar.com (Strategic Materials Policy Tracker, Benjamin Yang)', r.dataset_version, r.curated_release_date, r.legal_status_as_of
  FROM m JOIN stratellar.clause_status_asof s ON s.measure_id = m.id CROSS JOIN stratellar.release r
  ORDER BY m.event_date DESC NULLS LAST, m.id
  LIMIT 25
$f$;

-- Counts only (no record content) for the supply-risk tool: clauses touching the material by issuer, measure type and status at the as-of date.
CREATE FUNCTION stratellar.material_summary(p_material text)
RETURNS TABLE (issuer text, measure_type text, status_asof text, clauses int, latest_event_date date, legal_status_as_of date, dataset_version text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = stratellar, pg_temp AS $f$
  SELECT cl.issuer, cl.measure_type, s.status_asof, count(*)::int, max(e.event_date), r.legal_status_as_of, r.dataset_version
  FROM stratellar.clauses cl JOIN stratellar.events e ON e.id = cl.event_id JOIN stratellar.clause_status_asof s ON s.measure_id = cl.id
  CROSS JOIN stratellar.release r
  WHERE p_material IS NOT NULL AND trim(p_material) <> '' AND stratellar._match(p_material, cl.material_ids)
  GROUP BY 1, 2, 3, 6, 7 ORDER BY 4 DESC
$f$;

REVOKE ALL ON ALL TABLES IN SCHEMA stratellar FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA stratellar FROM PUBLIC;
GRANT USAGE ON SCHEMA stratellar TO cm_app_readonly;
GRANT EXECUTE ON FUNCTION stratellar.controls(text, text, text), stratellar.material_summary(text) TO cm_app_readonly;
""")
g.commit()
c.execute("SELECT status_asof, count(*) FROM stratellar.clause_status_asof GROUP BY 1 ORDER BY 2 DESC")
print("status as of", asof, c.fetchall())
