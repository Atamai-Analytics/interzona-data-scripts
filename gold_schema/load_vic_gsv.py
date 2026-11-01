"""Geological Survey of Victoria geochemistry data collection (G172012, soil/stream-sediment/rock samples; bronze datasource 'Resources Victoria') -> interzona_cm gold (geochem).
Same lean layout as load_usgs_ngdb.py. All active bronze samples of the datasource; samples already present in gold (core.external_ids) are skipped.
Classification: qualifier < = below detection; NULL value = NULL_RESULT; everything else DETECTED.
Usage: python load_vic_gsv.py [--dry]    (--dry = load + verify, then ROLLBACK)
"""
import os, sys, io, csv, time
import psycopg2

DRY = "--dry" in sys.argv
TAG = "migration_vic_gsv_20261013"
SRC = "AUSTRALIA_VIC_GSV_GEOCHEMISTRY"
DATASOURCE = "Resources Victoria"

ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def connect(db):
    return psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db,
                            user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


b = connect("criticialmineralsexp")
bc = b.cursor()
bc.execute("SET statement_timeout = 0")
log("bronze connected")

# ---------------------------------------------------------------- bronze extracts
bc.execute("""
SELECT s.sampleid, l.latitude, l.longitude, l.elevation, st.sample_type_code, s.sampletypelocal, s.sample_context,
       s.samplenumber, s.samplenumberalt, s.fieldid, s.sampledate, s.sample_weight_kg, s.depthfrom_m, s.depthto_m, s.comments
FROM samples s JOIN locations l ON l.locationid = s.locationid JOIN sample_types st ON st.sample_type_id = s.sample_type_id
WHERE s.isactive AND l.datasource = %s ORDER BY s.sampleid""", (DATASOURCE,))
samples = bc.fetchall()
log("bronze samples", len(samples))
# bronze samples already in gold under another source label (USGS-origin points inside the Argentina/Greenland sets) are NOT loaded again
_g0 = connect("interzona_cm"); _c0 = _g0.cursor()
_c0.execute("SELECT source_id::bigint FROM core.external_ids WHERE entity_type = 'SAMPLE' AND source_system = 'BRONZE_CRITICIALMINERALSEXP'")
SKIP = {r[0] for r in _c0.fetchall()}; _g0.close()
_n0 = len(samples)
samples = [r for r in samples if r[0] not in SKIP]
log("samples to load:", len(samples), "| excluded as already in gold:", _n0 - len(samples))
ids = [r[0] for r in samples]

bc.execute("""
SELECT lo.sampleid, lit.lithology_code, lo.lithologylocal, lo.observation_context, lo.depthfrom_m, lo.depthto_m, lo.logged_by, lo.logged_date,
       lo.stratgroup, lo.stratformation, lo.stratmember, lo.stratbed, lo.alterationlocal, lo.comments
FROM lithology_observations lo JOIN locations l ON l.locationid = lo.locationid
LEFT JOIN lithology lit ON lit.lithology_id = lo.lithology_id
WHERE l.datasource = %s AND lo.isactive AND lo.sampleid IS NOT NULL""", (DATASOURCE,))
litho = [r for r in bc.fetchall() if r[0] not in SKIP]
log("bronze lithology obs", len(litho))

# results -> CSV file (streamed)
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vic_results.csv")
t0 = time.time(); n = 0
cur_name = "vic_results_cur"
rc = b.cursor(name=cur_name)
rc.itersize = 50000
rc.execute("""
SELECT r.result_id, r.sampleid, a.analyte_code, u.unitcode, q.qualifier_code, p.package_code, r.value, r.report_number,
       r.date_analysed, r.lower_detection_limit, r.upper_detection_limit, r.reviewed
FROM analytical_results r JOIN analytes a ON a.analyte_id = r.analyte_id JOIN units u ON u.unitid = r.unitid
JOIN analytical_packages p ON p.package_id = r.package_id LEFT JOIN qualifiers q ON q.qualifier_id = r.qualifier_id
JOIN samples s2 ON s2.sampleid = r.sampleid JOIN locations l2 ON l2.locationid = s2.locationid
WHERE r.isactive AND s2.isactive AND l2.datasource = %s""", (DATASOURCE,))
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for row in rc:
        if row[1] in SKIP:
            continue
        w.writerow(["\\N" if x is None else x for x in row]); n += 1
rc.close()
log("bronze results", n, "in", round(time.time() - t0), "s")
b.rollback(); b.close()

# ---------------------------------------------------------------- gold load
g = connect("interzona_cm")
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '256MB'")

c.execute("""CREATE TABLE geochem._stage_vic_samples (bronze_sampleid bigint, lat double precision, lon double precision, elev numeric,
 sample_type_code text, sampletypelocal text, sample_context text, samplenumber text, samplenumberalt text, fieldid text,
 sampledate timestamptz, weight numeric, dfrom numeric, dto numeric, comments text)""")
buf = io.StringIO()
w = csv.writer(buf)
for r in samples:
    w.writerow(["\\N" if x is None else x for x in r])
buf.seek(0)
c.copy_expert("COPY geochem._stage_vic_samples FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)

c.execute("""CREATE TABLE geochem._stage_vic_litho (bronze_sampleid bigint, lithology_code text, lithology_local text, observation_context text,
 dfrom numeric, dto numeric, logged_by text, logged_date timestamptz, strat_group text, strat_formation text, strat_member text, strat_bed text,
 alteration_local text, comments text)""")
buf = io.StringIO(); w = csv.writer(buf)
for r in litho:
    w.writerow(["\\N" if x is None else x for x in r])
buf.seek(0)
c.copy_expert("COPY geochem._stage_vic_litho FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)

c.execute("""CREATE TABLE geochem._stage_vic_results (bronze_result_id bigint, bronze_sampleid bigint, analyte_code text, unit_code text,
 qualifier_code text, package_code text, value numeric, report_number text, date_analysed date, ldl numeric, udl numeric, reviewed boolean)""")
with open(csv_path, "r", encoding="utf-8") as f:
    c.copy_expert("COPY geochem._stage_vic_results FROM STDIN WITH (FORMAT csv, NULL '\\N')", f)
log("staged into gold")

c.execute("SELECT count(*) FROM geochem._stage_vic_samples"); ns = c.fetchone()[0]
c.execute("SELECT count(*) FROM geochem._stage_vic_results"); nr = c.fetchone()[0]
assert ns == len(samples) and nr == n, (ns, nr, len(samples), n)

# mapping completeness checks (nothing may silently drop)
c.execute("""SELECT count(*) FROM geochem._stage_vic_results r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte_code WHERE a.analyte_id IS NULL""")
miss_a = c.fetchone()[0]
c.execute("""SELECT count(*) FROM geochem._stage_vic_results r LEFT JOIN geochem.units u ON u.unit_code = r.unit_code WHERE u.unit_id IS NULL""")
miss_u = c.fetchone()[0]
c.execute("""SELECT count(*) FROM geochem._stage_vic_results r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.package_code WHERE p.package_id IS NULL""")
miss_p = c.fetchone()[0]
c.execute("""SELECT count(*) FROM geochem._stage_vic_results r LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qualifier_code WHERE r.qualifier_code IS NOT NULL AND q.qualifier_id IS NULL""")
miss_q = c.fetchone()[0]
c.execute("""SELECT count(*) FROM geochem._stage_vic_samples s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.sample_type_code WHERE t.sample_type_id IS NULL""")
miss_t = c.fetchone()[0]
log("unmapped: analyte", miss_a, "unit", miss_u, "package", miss_p, "qualifier", miss_q, "sample_type", miss_t)
assert miss_a == miss_u == miss_p == miss_q == miss_t == 0, "unmapped dictionary codes"

# partitions
c.execute(f"CREATE TABLE geochem.analytical_results_australia_vic_gsv_geochemistry PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
c.execute(f"CREATE TABLE geochem.result_classifications_australia_vic_gsv_geochemistry PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")

# samples (no Finnish occurrences exist in gold yet -> occurrence_id NULL)
c.execute("ALTER TABLE geochem.samples ADD COLUMN _bronze_sampleid bigint")
c.execute(f"""
INSERT INTO geochem.samples (occurrence_id, sampling_line_id, geom, field_id, sample_number, sample_number_alt, sample_type_id, sample_type_local,
  sample_context, depth_from_m, depth_to_m, sample_date, sample_weight_kg, elevation_m, comments, is_active, created_by, created_date, source_system, _bronze_sampleid)
-- 2026-10-15: GSV sample-method code PAN ('SED | PAN2 ...') = panned concentrate, loaded as Heavy Mineral Concentrate (see fix_vic_pan_concentrates.py)
SELECT NULL, NULL, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.fieldid, s.samplenumber, s.samplenumberalt,
  CASE WHEN s.sampletypelocal ILIKE 'SED | PAN%' THEN (SELECT sample_type_id FROM geochem.sample_types WHERE sample_type_name = 'Heavy Mineral Concentrate') ELSE t.sample_type_id END, s.sampletypelocal,
  s.sample_context, s.dfrom, s.dto, s.sampledate, s.weight, s.elev, s.comments, true, '{TAG}', now(), '{SRC}', s.bronze_sampleid
FROM geochem._stage_vic_samples s JOIN geochem.sample_types t ON t.sample_type_code = s.sample_type_code ORDER BY s.bronze_sampleid""")
c.execute(f"""
INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
SELECT 'SAMPLE', s.sample_id, 'BRONZE_CRITICIALMINERALSEXP', s._bronze_sampleid::text, '{TAG}', now()
FROM geochem.samples s WHERE s.source_system = '{SRC}'""")
c.execute(f"CREATE TABLE geochem._stage_vic_samplemap AS SELECT _bronze_sampleid AS bronze_sampleid, sample_id FROM geochem.samples WHERE source_system = '{SRC}'")
c.execute("CREATE UNIQUE INDEX ON geochem._stage_vic_samplemap (bronze_sampleid)")
c.execute("ALTER TABLE geochem.samples DROP COLUMN _bronze_sampleid")
c.execute(f"SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}'"); log("gold samples", c.fetchone()[0])

# results (lean layout)
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, NULL, NULL,
  r.value, r.ldl, r.udl, r.report_number, r.date_analysed, coalesce(r.reviewed, false), true, 'vic_gsv_20261013', now()
FROM geochem._stage_vic_results r
JOIN geochem._stage_vic_samplemap m ON m.bronze_sampleid = r.bronze_sampleid
JOIN geochem.analytes a ON a.analyte_code = r.analyte_code
JOIN geochem.units u ON u.unit_code = r.unit_code
JOIN geochem.analytical_packages p ON p.package_code = r.package_code
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qualifier_code
ORDER BY r.bronze_sampleid, r.bronze_result_id""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results WHERE source_system = '{SRC}'"); ngr = c.fetchone()[0]
log("gold results", ngr, "in", round(time.time() - t0), "s")
assert ngr == nr, (ngr, nr)

# classification: '<' (and other below-detection qualifiers) -> BELOW_DL_QUALIFIED, not used in statistics; everything else DETECTED
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code IN ('<','ND','L','N') THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code IN ('>','G') THEN 'ABOVE_UDL'
       WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code IN ('<','ND','L','N') THEN coalesce(r.lower_detection_limit, r.value) END,
  CASE WHEN r.qualifier_code IN ('<','ND','L','N') THEN CASE WHEN r.lower_detection_limit IS NOT NULL THEN 'QUALIFIER_LDL' ELSE 'QUALIFIER_VALUE' END END,
  (r.qualifier_code IS NULL OR r.qualifier_code NOT IN ('<','ND','L','N','>','G')) AND r.value IS NOT NULL
FROM geochem.analytical_results r WHERE r.source_system = '{SRC}'""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_v2_20261012', now(), now(), count(*), 'rule-based classification at load' FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute(f"SELECT result_status, use_in_statistics, dl_source, count(*) FROM geochem.result_classifications WHERE source_system = '{SRC}' GROUP BY 1,2,3 ORDER BY 4 DESC")
log("classification", c.fetchall())

# lithology
c.execute("CREATE TABLE geochem._stage_vic_litmap AS SELECT b.lithology_code, g.lithology_id FROM (SELECT DISTINCT lithology_code FROM geochem._stage_vic_litho) b JOIN geochem.lithology g ON g.lithology_code = b.lithology_code")
c.execute(f"""
INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sampling_line_id, sample_id, occurrence_id, depth_from_m, depth_to_m,
  logged_by, logged_date, strat_group, strat_formation, strat_member, strat_bed, alteration_id, alteration_local, comments, is_active, created_by, created_date)
SELECT lm.lithology_id, l.lithology_local, l.observation_context, NULL, m.sample_id, NULL, l.dfrom, l.dto, l.logged_by, l.logged_date,
  l.strat_group, l.strat_formation, l.strat_member, l.strat_bed, NULL, l.alteration_local, l.comments, true, '{TAG}', now()
FROM geochem._stage_vic_litho l JOIN geochem._stage_vic_samplemap m ON m.bronze_sampleid = l.bronze_sampleid
LEFT JOIN geochem._stage_vic_litmap lm ON lm.lithology_code = l.lithology_code""")
c.execute(f"SELECT count(*), count(lithology_id) FROM geochem.lithology_observations WHERE created_by = '{TAG}'"); log("lithology obs (total, with lithology_id)", c.fetchone())

# verification
c.execute(f"""SELECT p.package_code, count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p ON p.package_id = r.package_id
 WHERE r.source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC"""); log("per package", c.fetchall())
c.execute(f"SELECT count(DISTINCT sample_id), count(DISTINCT analyte_id) FROM geochem.analytical_results WHERE source_system = '{SRC}'"); log("samples with results, analytes", c.fetchone())
c.execute(f"SELECT count(*) FROM geochem.analytical_results r LEFT JOIN geochem.result_classifications c ON c.result_id = r.result_id AND c.source_system = r.source_system WHERE r.source_system = '{SRC}' AND c.result_id IS NULL")
log("results without classification", c.fetchone()[0])

for t in ("_stage_vic_samples", "_stage_vic_results", "_stage_vic_litho", "_stage_vic_samplemap", "_stage_vic_litmap"):
    c.execute(f"DROP TABLE geochem.{t}")
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
os.remove(csv_path)
