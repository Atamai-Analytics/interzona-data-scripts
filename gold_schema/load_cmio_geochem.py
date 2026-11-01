"""Critical Minerals in Ores - geochemistry database (Critical Minerals Mapping Initiative: Geoscience Australia with the Geological Survey of Canada and the USGS)
-> interzona_cm gold (geochem). Source file D:\\CriticalMineralsDB\\Global\\CriticalMineralDepositsGeochemistry.csv (29,087 analyses of 26,837 samples from 1,652 deposits).
Same lean layout as load_vic_gsv.py, plus geochem.sample_deposit_context (deposit type/group/environment and sample descriptors) and links to core.occurrences.
NOT added to geochem.sample_chemistry_wide on purpose (ore-deposit samples would distort the new-leads anomaly screen); results are in analytical_results only.
Rules (see cmio_common.py): negative values = below detection (stored as '<' with the absolute value), exact zeros = NULL_RESULT, impossible values (>100 wt%, >1e6 ppm)
and 9999/99999/999999 sentinels = inactive, exact duplicates (same sample/analyte/method/value) = inactive after the first; the derived sums REE, HREE, LREE, REE_Y, REST and RE are not loaded.
Usage: python load_cmio_geochem.py [--dry]    (--dry = load + verify, then ROLLBACK)
"""
import os, sys, io, csv, time, collections, datetime
import psycopg2
from cmio_common import *

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def clip(s, n):
    s = (s or "").strip()
    return s[:n] if s else None


def null(x):
    return "\\N" if x is None else x


def pdate(s):
    s = (s or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(s).isoformat() if len(s) == 10 else None
    except ValueError:
        return None


# ---------------------------------------------------------------- parse
rows = load_rows(); cols = list(rows[0].keys()); acols = analyte_columns(cols)
log("csv rows", len(rows), "| analyte columns", len(acols))
results = list(parse_results(rows, acols))
log("results parsed", len(results))

first = {}
for r in rows:
    first.setdefault(r["SAMPLE_UID"], r)
log("samples", len(first))

# exact duplicates: keep the first, later ones are inactive
seen = set()
for r in results:
    k = (rows[r["row"]]["SAMPLE_UID"], r["analyte_id"], r["analyte"], r["method"], r["value"], r["qual"])
    if k in seen:
        r["active"], r["stats"], r["dup"] = False, False, True
    else:
        seen.add(k); r["dup"] = False
log("duplicates made inactive", sum(1 for r in results if r["dup"]), "| inactive in total", sum(1 for r in results if not r["active"]))

methods = sorted({r["method"] for r in results})
log("methods", len(methods))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '256MB'")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SOURCE,)); assert c.fetchone()[0] == 0, "source already loaded"

# ---------------------------------------------------------------- deposit -> occurrence matching (read-only part)
deps = {}
for r in rows:
    deps.setdefault(r["DEPOSIT_UID"], r)
match = {}
for uid, r in deps.items():
    name = (r["DEPOSIT_NAME"] or "").strip(); lat = float(r["DEPOSIT_LATITUDE_WGS84"]); lon = float(r["DEPOSIT_LONGITUDE_WGS84"])
    syms = {x.strip() for x in ((r["PRIMARY_COMMODITIES"] or "") + "," + (r["SECONDARY_COMMODITIES"] or "")).split(",") if x.strip()}
    c.execute("""SELECT occurrence_id, name, commodities, round(ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography))::int d,
                        similarity(lower(name), lower(%s)) sim
                 FROM core.occurrences WHERE is_active AND position_accuracy IS NULL AND geom IS NOT NULL
                   AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 2000)""", (lon, lat, name, lon, lat))
    cands = c.fetchall()
    named = [x for x in cands if x[4] >= 0.45]
    if named:
        x = sorted(named, key=lambda x: (-x[4], x[3]))[0]; match[uid] = (x[0], "NAME_AND_DISTANCE", x[3])
    else:
        com = [x for x in cands if x[3] <= 1000 and syms & set(x[2] or [])]
        if com:
            x = sorted(com, key=lambda x: x[3])[0]; match[uid] = (x[0], "COMMODITY_NEAREST_1KM", x[3])
log("deposits", len(deps), "matched to an occurrence", len(match), dict(collections.Counter(v[1] for v in match.values())))


# ---------------------------------------------------------------- stage
def copy(table, ddl, data):
    c.execute(f"CREATE TABLE geochem.{table} ({ddl})")
    buf = io.StringIO(); w = csv.writer(buf)
    for r in data:
        w.writerow([null(x) for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY geochem.{table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


samples = []
for uid, r in first.items():
    stype = (r["SAMPLE_TYPE"] or "").strip() or "unknown"
    tid, ctx = SAMPLE_TYPE.get(stype, (4, "OTHER"))
    samples.append((uid, clip(r["SAMPLE_NAME"], 100), clip(r["SAMPLE_LOCAL_ID"], 100), float(r["SAMPLE_LATITUDE_WGS84"]), float(r["SAMPLE_LONGITUDE_WGS84"]),
                    tid, clip(stype, 100), ctx, fnum(r["TOP_DEPTH_M"]), fnum(r["BASE_DEPTH_M"]), r["DEPOSIT_UID"],
                    r["DEPOSIT_ANALYSIS_ID"], clip(r["SAMPLE_SOURCE"], 100), clip(r["SUBMITTER"], 300), clip(r["DEPOSIT_SOURCE"], 100), bool(COMPANY.search(r["SUBMITTER"] or ""))))
copy("_stage_cmio_samples", """sample_uid text, sample_name text, local_id text, lat double precision, lon double precision, type_id int, type_local text, context text,
  dfrom numeric, dto numeric, deposit_uid text, analysis_id text, sample_source text, submitter text, deposit_source text, third_party boolean""", samples)

ctxrows = []
for uid, r in first.items():
    ctxrows.append((uid, r["DEPOSIT_UID"], clip(r["DEPOSIT_NAME"], 300), clip(r["DEPOSIT_LOCAL_ID"], 100), clip(r["DEPOSIT_ENVIRONMENT"], 200), clip(r["DEPOSIT_GROUP"], 200),
                    clip(r["DEPOSIT_TYPE"], 300), clip(r["PRIMARY_COMMODITIES"], 300), clip(r["SECONDARY_COMMODITIES"], 300), clip(r["ALL_COMMODITIES"], 500),
                    clip(r["DEPOSIT_SOURCE"], 200), fnum(r["DEPOSIT_LATITUDE_WGS84"]), fnum(r["DEPOSIT_LONGITUDE_WGS84"]), clip(r["COUNTRY"], 100), clip(r["STATE"], 200),
                    clip(r["PROVINCE"], 200), clip(r["SAMPLE_DEPOSIT_RELATION"], 100), clip(r["MATERIAL_CLASS"], 100), clip(r["EARTH_MATERIAL_GROUP"], 200),
                    clip(r["EARTH_MATERIAL"], 300), clip(r["EARTH_MATERIAL_QUALIFIER"], 300), clip(r["MODE_OCCURRENCE"], 300), clip(r["ALTERATION"], 500), clip(r["TEXTURE"], 300),
                    clip(r["MINERALS"], 1000), clip(r["STRAT_UNIT_NAME"], 300), clip(r["SAMPLING_METHOD"], 200), clip(r["SAMPLE_PREPARATION"], 500), clip(r["SAMPLE_DESCRIPTION"], 1500),
                    int(fnum(r["LOCATION_ACCURACY"])) if fnum(r["LOCATION_ACCURACY"]) is not None else None,
                    match.get(r["DEPOSIT_UID"], (None, None, None))[0], match.get(r["DEPOSIT_UID"], (None, None, None))[1], match.get(r["DEPOSIT_UID"], (None, None, None))[2]))
copy("_stage_cmio_ctx", """sample_uid text, deposit_uid text, deposit_name text, deposit_local_id text, env text, grp text, dtype text, prim text, sec text, allc text, dsource text,
  dlat double precision, dlon double precision, country text, state text, province text, relation text, material_class text, em_group text, em text, em_qual text,
  mode_occ text, alteration text, texture text, minerals text, strat text, sampling_method text, prep text, descr text, loc_acc int, occ_id int, match_method text, match_dist int""", ctxrows)

resrows = []
for r in results:
    src = rows[r["row"]]
    dl_source = "NEGATIVE_CONVENTION" if r["qual"] == "<" else None
    resrows.append((src["SAMPLE_UID"], r["analyte_id"], r["unit_id"], r["qual"], "CMIO-" + r["method"][:44], r["value"], r["dl"], clip(src["SAMPLE_SOURCE"], 100), pdate(src["ANALYSIS_DATETIME"]),
                    VARIANT_NAME.get(r["analyte"]), r["method"], r["active"], r["status"], r["dl_value"], dl_source, r["stats"]))
copy("_stage_cmio_results", """sample_uid text, analyte_id int, unit_id int, qual text, pkg_code text, value numeric, ldl numeric, report text, date_analysed date,
  variant text, method_code text, active boolean, status text, dl_value numeric, dl_source text, stats boolean""", resrows)
log("staged", len(samples), "samples,", len(resrows), "results")

# ---------------------------------------------------------------- packages
for m in methods:
    code = "CMIO-" + m[:44]
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, package_type, source_method, description, is_active, created_by, created_date)
                 VALUES (%s, %s, 428, 'Geochemical', %s, %s, true, %s, now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, clip("Critical Minerals in Ores database - method " + m, 150), clip(m, 100),
               "Analytical method code as supplied in the Critical Minerals in Ores geochemistry database (Geoscience Australia / CMMI); the code is kept as given and not decoded here. "
               "Several methods can report the same element for one sample: never pool values across packages without saying so.", TAG))
c.execute("SELECT count(*) FROM geochem.analytical_packages WHERE created_by = %s", (TAG,)); log("packages created", c.fetchone()[0])

# ---------------------------------------------------------------- samples, provenance, context, external ids
c.execute(f"""
INSERT INTO geochem.samples (occurrence_id, sampling_line_id, geom, field_id, sample_number, sample_number_alt, sample_type_id, sample_type_local,
  sample_context, depth_from_m, depth_to_m, is_active, created_by, created_date, source_system)
SELECT NULL, NULL, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.sample_uid, s.sample_name, CASE WHEN s.local_id IS DISTINCT FROM s.sample_name THEN s.local_id END,
  s.type_id, s.type_local, s.context, s.dfrom, s.dto, true, '{TAG}', now(), '{SOURCE}'
FROM geochem._stage_cmio_samples s ORDER BY s.sample_uid""")
c.execute(f"SELECT count(*) FROM geochem.samples WHERE source_system = '{SOURCE}'"); ns = c.fetchone()[0]; log("gold samples", ns); assert ns == len(samples)

c.execute(f"""
INSERT INTO geochem.sample_provenance (sample_id, source_system, source_record_id, source_prov_id, third_party_likely, third_party_basis, ext_id, reference, laboratory, source_note, created_by)
SELECT g.sample_id, '{SOURCE}', s.sample_uid, s.analysis_id, s.third_party, CASE WHEN s.third_party THEN 'SUBMITTER_NAME' END, s.local_id, s.sample_source, NULL,
  s.deposit_source || '; submitter: ' || coalesce(s.submitter, 'unknown'), '{TAG}'
FROM geochem._stage_cmio_samples s JOIN geochem.samples g ON g.source_system = '{SOURCE}' AND g.field_id = s.sample_uid""")

c.execute(f"""
INSERT INTO geochem.sample_deposit_context (sample_id, source_system, deposit_uid, deposit_name, deposit_local_id, deposit_environment, deposit_group, deposit_type,
  primary_commodities, secondary_commodities, all_commodities, deposit_source, deposit_lat, deposit_lon, country, state_province, tectonic_province, sample_deposit_relation,
  material_class, earth_material_group, earth_material, earth_material_qualifier, mode_of_occurrence, alteration, texture, minerals, stratigraphic_unit, sampling_method,
  sample_preparation, sample_description, location_accuracy_m, matched_occurrence_id, match_method, match_distance_m, created_by)
SELECT g.sample_id, '{SOURCE}', x.deposit_uid, x.deposit_name, x.deposit_local_id, x.env, x.grp, x.dtype, x.prim, x.sec, x.allc, x.dsource, x.dlat, x.dlon, x.country, x.state,
  x.province, x.relation, x.material_class, x.em_group, x.em, x.em_qual, x.mode_occ, x.alteration, x.texture, x.minerals, x.strat, x.sampling_method, x.prep, x.descr,
  x.loc_acc, x.occ_id, x.match_method, x.match_dist, '{TAG}'
FROM geochem._stage_cmio_ctx x JOIN geochem.samples g ON g.source_system = '{SOURCE}' AND g.field_id = x.sample_uid""")

c.execute(f"""
INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
SELECT 'SAMPLE', sample_id, '{SOURCE}', field_id, '{TAG}', now() FROM geochem.samples WHERE source_system = '{SOURCE}'""")

# ---------------------------------------------------------------- results (lean layout, labels filled here)
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol, unit_id, unit_code, qualifier_id, qualifier_code,
  laboratory, method_code, method_name, digest_name, value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date)
SELECT g.sample_id, NULL, '{SOURCE}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, r.method_code, r.variant, NULL, r.value, r.ldl, NULL, r.report, r.date_analysed, false, r.active, '{TAG}', now()
FROM geochem._stage_cmio_results r
JOIN geochem.samples g ON g.source_system = '{SOURCE}' AND g.field_id = r.sample_uid
JOIN geochem.analytes a ON a.analyte_id = r.analyte_id
JOIN geochem.units u ON u.unit_id = r.unit_id
JOIN geochem.analytical_packages p ON p.package_code = r.pkg_code
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual
ORDER BY g.sample_id""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results WHERE source_system = '{SOURCE}'"); ngr = c.fetchone()[0]
log("gold results", ngr, "in", round(time.time() - t0), "s"); assert ngr == len(resrows), (ngr, len(resrows))

# classification: the stage table already carries the status; join back on the insertion order is not stable, so classify by the same rules from the stored columns
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN NOT r.is_active AND r.value > 0 AND r.value IN (9999, 99999, 999999) THEN 'SENTINEL'
       WHEN r.qualifier_code = '<' THEN CASE WHEN r.lower_detection_limit IS NOT NULL AND abs(r.value - r.lower_detection_limit) <= 0.01 * r.lower_detection_limit THEN 'BELOW_DL_CERTAIN' ELSE 'BELOW_DL_PROBABLE' END
       WHEN r.value = 0 THEN 'NULL_RESULT'
       WHEN NOT r.is_active AND (r.unit_code = 'wt%' AND r.value > CASE WHEN r.analyte_name = 'Sum of Oxides' THEN 110 ELSE 100 END OR r.unit_code = 'ppm' AND r.value > 1000000 OR r.unit_code = 'ppb' AND r.value > 1000000000) THEN 'SUSPECT'
       ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN coalesce(r.lower_detection_limit, r.value) END,
  CASE WHEN r.qualifier_code = '<' THEN 'NEGATIVE_CONVENTION' END,
  r.is_active AND r.qualifier_code IS NULL AND r.value > 0
FROM geochem.analytical_results r WHERE r.source_system = '{SOURCE}'""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_cmio_20261023', now(), now(), count(*), 'rule-based classification at load (negative values = below detection)' FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SOURCE,))
c.execute(f"SELECT result_status, use_in_statistics, count(*) FROM geochem.result_classifications WHERE source_system = '{SOURCE}' GROUP BY 1,2 ORDER BY 3 DESC"); log("classification", c.fetchall())

# ---------------------------------------------------------------- links to occurrences (same rules as link_samples_to_occurrences.py)
c.execute(f"""
INSERT INTO geochem.sample_occurrence_links (sample_id, occurrence_id, distance_m, is_nearest)
SELECT sample_id, occurrence_id, d::int, row_number() OVER (PARTITION BY sample_id ORDER BY d, occurrence_id) = 1
FROM (SELECT s.sample_id, o.occurrence_id, ST_Distance(s.geog, o.geog) AS d FROM geochem.samples s
      JOIN core.occurrences o ON o.is_active AND o.position_accuracy IS NULL AND ST_DWithin(o.geog, s.geog, 2000)
      WHERE s.source_system = '{SOURCE}') x""")
log("links inserted", c.rowcount)

# ---------------------------------------------------------------- data source record
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded, licence_status, caveats,
  evidence_location, evidence_date, is_active, created_by, created_date)
VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, %s, true, %s, now())""",
          (SOURCE, "Commonwealth of Australia (Geoscience Australia), with the Geological Survey of Canada, the USGS and the Geological Survey of Queensland (Critical Minerals Mapping Initiative)",
           "Critical Minerals in Ores - geochemistry database (eCat 145496), CSV download CriticalMineralDepositsGeochemistry.csv obtained 2026-10-22; 29,087 analyses, 26,837 samples, 1,652 deposits",
           "Creative Commons Attribution 4.0 International (CC BY 4.0), as stated on the Research Data Australia record", "http://creativecommons.org/licenses/",
           "Champion, D., Raymond, O., Huston, D., and others (2021): Critical Minerals in Ores - geochemistry database. Geoscience Australia, Critical Minerals Mapping Initiative (with the Geological Survey of Canada and the USGS). https://pid.geoscience.gov.au/dataset/ga/145496. Licensed CC BY 4.0.",
           "CC BY 4.0 stated on the Research Data Australia record (read 2026-10-23); the eCat page's own licence field was not confirmed verbatim. The published 2021 record describes 'over 7000 samples from 60 countries'; the file loaded here is larger (LAST_UPDATE up to 2025-07), so it is a later update of the same database.",
           "Compilation of USGS (USMIN, MRDS, LONG, ARDF), Geoscience Australia (OZMIN, GEOCHEM), Geological Survey of Canada (open files 8727, 7766, 5432), Geological Survey of Queensland and Curtin University (OSNACA) data. Sample values are as supplied: negative values are below detection (stored as '<' with the absolute value); several methods can report the same element for one sample. Not in geochem.sample_chemistry_wide by design.",
           "https://researchdata.edu.au/critical-minerals-ores-geochemistry-database/3407769 (RDA record) and https://ecat.ga.gov.au/geonetwork/srv/api/records/3c876198-5f78-4f6a-836e-da7f22c3333e",
           datetime.date(2026, 10, 23), TAG))

# ---------------------------------------------------------------- verification
c.execute(f"SELECT count(DISTINCT sample_id), count(DISTINCT analyte_id), count(*) FILTER (WHERE is_active) FROM geochem.analytical_results WHERE source_system = '{SOURCE}'"); log("samples with results, analytes, active results", c.fetchone())
c.execute(f"SELECT count(*) FROM geochem.analytical_results r LEFT JOIN geochem.result_classifications c ON c.result_id = r.result_id AND c.source_system = r.source_system WHERE r.source_system = '{SOURCE}' AND c.result_id IS NULL"); log("results without classification (must be 0)", c.fetchone()[0])
c.execute(f"SELECT count(*) FROM geochem.analytical_results WHERE source_system = '{SOURCE}' AND (analyte_name IS NULL OR unit_code IS NULL)"); log("results missing labels (must be 0)", c.fetchone()[0])
c.execute(f"SELECT count(DISTINCT sample_id), count(*), count(DISTINCT sample_id) FILTER (WHERE distance_m <= 500) FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) WHERE s.source_system = '{SOURCE}'"); log("links: samples, links, samples within 500 m", c.fetchone())
c.execute(f"SELECT count(*) FROM (SELECT sample_id FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) WHERE s.source_system = '{SOURCE}' AND is_nearest GROUP BY 1 HAVING count(*) <> 1) x"); log("samples with not exactly one nearest row (must be 0)", c.fetchone()[0])
c.execute(f"SELECT deposit_group, count(*) FROM geochem.sample_deposit_context WHERE source_system = '{SOURCE}' GROUP BY 1 ORDER BY 2 DESC LIMIT 5"); log("top deposit groups", c.fetchall())
c.execute(f"SELECT count(*) FILTER (WHERE matched_occurrence_id IS NOT NULL), count(DISTINCT deposit_uid) FILTER (WHERE matched_occurrence_id IS NOT NULL), count(DISTINCT deposit_uid) FROM geochem.sample_deposit_context WHERE source_system = '{SOURCE}'"); log("context: samples with matched occurrence, deposits matched, deposits", c.fetchone())
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SOURCE,)); log("external ids", c.fetchone()[0])

for t in ("_stage_cmio_samples", "_stage_cmio_ctx", "_stage_cmio_results"):
    c.execute(f"DROP TABLE geochem.{t}")
c.execute("ANALYZE geochem.analytical_results_global_deposit_geochem_ga")
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
