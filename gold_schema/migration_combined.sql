-- ============================================================================
-- Combined migration: Argentina backfill + full Greenland bronze -> gold
-- migration, all 7 phases in one file. Each phase is its own BEGIN/COMMIT,
-- so if a later phase fails, earlier phases stay committed -- do NOT just
-- re-run this whole file from the top in that case (Phase 0's constraint
-- drop and Phase 1/3's inserts aren't safely re-runnable as-is). Instead,
-- delete the phases that already committed successfully from a copy of this
-- file and re-run from the failed phase onward.
--
-- Run with: psql -f migration_combined.sql   (or \i migration_combined.sql
-- from inside an interactive psql session, connected as the AtamaiAdmin
-- role to interzona_cm -- NOT the app's read-only .env.local credentials).
--
-- \echo lines below print progress markers as it runs; the verification
-- SELECTs print their row counts right after each phase's work.
-- ============================================================================

\echo '=== PHASE 0: drop chk_sample_parent ==='
BEGIN;
ALTER TABLE geochem.samples DROP CONSTRAINT IF EXISTS chk_sample_parent;
SELECT conname FROM pg_constraint
WHERE conrelid = 'geochem.samples'::regclass AND contype = 'c';
COMMIT;


\echo '=== PHASE 1: Argentina backfill samples (~30,700 expected) ==='
BEGIN;

CREATE TABLE geochem._stage_ar_backfill_samples AS
SELECT
  s.sampleid, l.latitude, l.longitude, l.elevation,
  s.sample_type_id AS bronze_sample_type_id, s.sampletypelocal, s.sample_context,
  s.samplenumber, s.samplenumberalt, s.fieldid, s.sampledate, s.sample_weight_kg,
  s.depthfrom_m, s.depthto_m
FROM bronze.samples s
JOIN bronze.locations l ON s.locationid = l.locationid
JOIN bronze.countries c ON l.countryid = c.countryid
WHERE c.countryname ILIKE '%argentina%';

DELETE FROM geochem._stage_ar_backfill_samples t
WHERE EXISTS (
  SELECT 1 FROM core.external_ids e
  WHERE e.entity_type = 'SAMPLE' AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'
    AND e.source_id = t.sampleid::text
);

CREATE TABLE geochem._map_sample_type AS
SELECT b.sample_type_id AS bronze_id, g.sample_type_id AS gold_id
FROM bronze.sample_types b
JOIN geochem.sample_types g ON g.sample_type_code = b.sample_type_code;

ALTER TABLE geochem.samples ADD COLUMN _bronze_sampleid bigint;

INSERT INTO geochem.samples (
  occurrence_id, sampling_line_id, geom, field_id, sample_number,
  sample_number_alt, sample_type_id, sample_type_local, sample_context,
  depth_from_m, depth_to_m, sample_date, sample_weight_kg, elevation_m,
  is_active, created_by, created_date, source_system, _bronze_sampleid
)
SELECT
  NULL, NULL,
  ST_SetSRID(ST_MakePoint(t.longitude, t.latitude), 4326),
  t.fieldid, t.samplenumber, t.samplenumberalt,
  m.gold_id, t.sampletypelocal, t.sample_context,
  t.depthfrom_m, t.depthto_m, t.sampledate, t.sample_weight_kg, t.elevation,
  true, 'migration_argentina_backfill_20260930', now(), 'ARGENTINA_SEGEMAR',
  t.sampleid
FROM geochem._stage_ar_backfill_samples t
LEFT JOIN geochem._map_sample_type m ON m.bronze_id = t.bronze_sample_type_id;

INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
SELECT 'SAMPLE', s.sample_id, 'BRONZE_CRITICIALMINERALSEXP', s._bronze_sampleid::text,
       'migration_argentina_backfill_20260930', now()
FROM geochem.samples s
WHERE s._bronze_sampleid IS NOT NULL;

ALTER TABLE geochem.samples DROP COLUMN _bronze_sampleid;

DROP TABLE geochem._stage_ar_backfill_samples;
DROP TABLE geochem._map_sample_type;

SELECT count(*) AS n_backfilled_samples
FROM geochem.samples WHERE created_by = 'migration_argentina_backfill_20260930';

COMMIT;


\echo '=== PHASE 2: Argentina backfill analytical_results (likely 1M+ rows -- may take a while) ==='
BEGIN;

CREATE TABLE geochem._stage_ar_backfill_results AS
SELECT
  ar.sampleid AS bronze_sampleid, ar.package_id AS bronze_package_id,
  ar.analyte_id AS bronze_analyte_id, ar.unitid AS bronze_unit_id,
  ar.qualifier_id AS bronze_qualifier_id,
  ar.value, ar.report_number, ar.date_analysed,
  ar.lower_detection_limit, ar.upper_detection_limit
FROM bronze.analytical_results ar
WHERE ar.sampleid = ANY(ARRAY(
  SELECT e.source_id::bigint FROM core.external_ids e
  WHERE e.entity_type = 'SAMPLE' AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'
    AND e.created_by = 'migration_argentina_backfill_20260930'
));

ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels;

CREATE TABLE geochem._map_analyte AS
SELECT b.analyte_id AS bronze_id, g.analyte_id AS gold_id
FROM bronze.analytes b JOIN geochem.analytes g ON g.analyte_code = b.analyte_code;

CREATE TABLE geochem._map_unit AS
SELECT b.unitid AS bronze_id, g.unit_id AS gold_id
FROM bronze.units b JOIN geochem.units g ON g.unit_code = b.unitcode;

CREATE TABLE geochem._map_qualifier AS
SELECT b.qualifier_id AS bronze_id, g.qualifier_id AS gold_id
FROM bronze.qualifiers b JOIN geochem.qualifiers g ON g.qualifier_code = b.qualifier_code;

CREATE TABLE geochem._map_package AS
SELECT b.package_id AS bronze_id, g.package_id AS gold_id
FROM bronze.analytical_packages b JOIN geochem.analytical_packages g ON g.package_code = b.package_code;

INSERT INTO geochem.analytical_results (
  sample_id, occurrence_id, source_system, package_id,
  analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code,
  qualifier_id, qualifier_code,
  laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed,
  reviewed, is_active, created_by, created_date
)
SELECT
  e.entity_id, NULL, 'ARGENTINA_SEGEMAR', mp.gold_id,
  ga.analyte_id, ga.analyte_name, ga.element_symbol,
  gu.unit_id, gu.unit_code,
  gq.qualifier_id, gq.qualifier_code,
  lab.lab_name, meth.method_code, meth.method_name, meth.digest_name,
  r.value, r.lower_detection_limit, r.upper_detection_limit, r.report_number, r.date_analysed,
  false, true, 'migration_argentina_backfill_20260930', now()
FROM geochem._stage_ar_backfill_results r
JOIN core.external_ids e ON e.entity_type = 'SAMPLE' AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'
  AND e.source_id = r.bronze_sampleid::text
JOIN geochem._map_analyte ma ON ma.bronze_id = r.bronze_analyte_id
JOIN geochem.analytes ga ON ga.analyte_id = ma.gold_id
JOIN geochem._map_unit mu ON mu.bronze_id = r.bronze_unit_id
JOIN geochem.units gu ON gu.unit_id = mu.gold_id
LEFT JOIN geochem._map_qualifier mqm ON mqm.bronze_id = r.bronze_qualifier_id
LEFT JOIN geochem.qualifiers gq ON gq.qualifier_id = mqm.gold_id
LEFT JOIN geochem._map_package mp ON mp.bronze_id = r.bronze_package_id
LEFT JOIN geochem.analytical_packages gp ON gp.package_id = mp.gold_id
LEFT JOIN geochem.laboratories lab ON lab.lab_id = gp.lab_id
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = gp.method_id;

ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels;

DROP TABLE geochem._stage_ar_backfill_results;
DROP TABLE geochem._map_analyte;
DROP TABLE geochem._map_unit;
DROP TABLE geochem._map_qualifier;
DROP TABLE geochem._map_package;

SELECT count(*) AS n_backfilled_results
FROM geochem.analytical_results WHERE created_by = 'migration_argentina_backfill_20260930';

COMMIT;


\echo '=== PHASE 3: Greenland occurrences (28 expected) ==='
BEGIN;

CREATE TABLE geochem._map_occurrence_type AS
SELECT b.deposit_type_id AS bronze_id, g.occurrence_type_id AS gold_id
FROM bronze.deposit_types b
JOIN core.occurrence_types g ON g.type_name = b.deposit_type_name;

ALTER TABLE core.occurrences ADD COLUMN _bronze_depositid integer;

INSERT INTO core.occurrences (
  name, is_deposit, occurrence_type_id, jurisdiction_id, geom, elevation_m,
  geological_province, geological_subprovince, geological_district,
  tectonic_setting, regional_structure, metallogenic_association,
  deposit_form, mineralization_style, associated_igneous, alteration,
  status, size_category, workings_type, comments,
  is_active, created_by, created_date, _bronze_depositid
)
SELECT
  l.locationname,
  d.deposit_status IN ('PAST_PRODUCER','PRODUCER','FEASIBILITY','DEVELOPMENT','CLOSED'),
  mt.gold_id,
  841,
  ST_SetSRID(ST_MakePoint(l.longitude, l.latitude), 4326),
  l.elevation,
  d.geological_province, d.geological_subprovince, d.geological_district,
  d.tectonic_setting, d.regional_structure, d.metallogenic_association,
  d.deposit_form, d.mineralization_style, d.associated_igneous, d.alteration,
  d.deposit_status, d.size_category, d.workings_type, d.comments,
  true, 'migration_greenland_20260930', now(), d.depositid
FROM bronze.deposits d
JOIN bronze.locations l ON d.locationid = l.locationid
JOIN bronze.countries c ON l.countryid = c.countryid
LEFT JOIN geochem._map_occurrence_type mt ON mt.bronze_id = d.deposit_type_id
WHERE c.countryname ILIKE '%greenland%';

INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
SELECT 'OCCURRENCE', o.occurrence_id, 'BRONZE_CRITICIALMINERALSEXP', o._bronze_depositid::text,
       'migration_greenland_20260930', now()
FROM core.occurrences o
WHERE o._bronze_depositid IS NOT NULL;

CREATE TABLE geochem._map_commodity AS
SELECT b.commodity_id AS bronze_id, g.commodity_id AS gold_id
FROM bronze.commodities b JOIN core.commodities g ON g.commodity_name = b.commodity_name;

INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by, created_date)
SELECT o.occurrence_id, mc.gold_id, dc.commodity_role, true, 'migration_greenland_20260930', now()
FROM bronze.deposit_commodities dc
JOIN core.occurrences o ON o._bronze_depositid = dc.depositid
JOIN geochem._map_commodity mc ON mc.bronze_id = dc.commodity_id;

ALTER TABLE core.occurrences DROP COLUMN _bronze_depositid;
DROP TABLE geochem._map_occurrence_type;
DROP TABLE geochem._map_commodity;

SELECT occurrence_id, name, is_deposit, occurrence_type_name, commodities
FROM core.occurrences WHERE created_by = 'migration_greenland_20260930'
ORDER BY occurrence_id;

COMMIT;


\echo '=== PHASE 4: Greenland samples (~49,400 total expected, ~604 linked to an occurrence) ==='
BEGIN;

CREATE TABLE geochem._stage_gl_samples AS
SELECT
  s.sampleid, l.latitude, l.longitude, l.elevation,
  s.sample_type_id AS bronze_sample_type_id, s.sampletypelocal, s.sample_context,
  s.samplenumber, s.samplenumberalt, s.fieldid, s.sampledate, s.sample_weight_kg,
  s.depthfrom_m, s.depthto_m
FROM bronze.samples s
JOIN bronze.locations l ON s.locationid = l.locationid
JOIN bronze.countries c ON l.countryid = c.countryid
WHERE c.countryname ILIKE '%greenland%';

CREATE TABLE geochem._map_sample_type AS
SELECT b.sample_type_id AS bronze_id, g.sample_type_id AS gold_id
FROM bronze.sample_types b
JOIN geochem.sample_types g ON g.sample_type_code = b.sample_type_code;

CREATE TABLE geochem._gl_sample_occurrence_match AS
SELECT DISTINCT ON (t.sampleid)
  t.sampleid, o.occurrence_id,
  ST_Distance(ST_SetSRID(ST_MakePoint(t.longitude, t.latitude), 4326)::geography, o.geog) AS dist_m
FROM geochem._stage_gl_samples t
JOIN core.occurrences o
  ON o.jurisdiction_id = 841
  AND o.created_by = 'migration_greenland_20260930'
  AND ST_DWithin(ST_SetSRID(ST_MakePoint(t.longitude, t.latitude), 4326)::geography, o.geog, 5000)
ORDER BY t.sampleid, dist_m;

ALTER TABLE geochem.samples ADD COLUMN _bronze_sampleid bigint;

INSERT INTO geochem.samples (
  occurrence_id, sampling_line_id, geom, field_id, sample_number,
  sample_number_alt, sample_type_id, sample_type_local, sample_context,
  depth_from_m, depth_to_m, sample_date, sample_weight_kg, elevation_m,
  is_active, created_by, created_date, source_system, _bronze_sampleid
)
SELECT
  mo.occurrence_id, NULL,
  ST_SetSRID(ST_MakePoint(t.longitude, t.latitude), 4326),
  t.fieldid, t.samplenumber, t.samplenumberalt,
  mst.gold_id, t.sampletypelocal, t.sample_context,
  t.depthfrom_m, t.depthto_m, t.sampledate, t.sample_weight_kg, t.elevation,
  true, 'migration_greenland_20260930', now(), 'GREENLAND_GEUS', t.sampleid
FROM geochem._stage_gl_samples t
LEFT JOIN geochem._map_sample_type mst ON mst.bronze_id = t.bronze_sample_type_id
LEFT JOIN geochem._gl_sample_occurrence_match mo ON mo.sampleid = t.sampleid;

INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
SELECT 'SAMPLE', s.sample_id, 'BRONZE_CRITICIALMINERALSEXP', s._bronze_sampleid::text,
       'migration_greenland_20260930', now()
FROM geochem.samples s
WHERE s._bronze_sampleid IS NOT NULL AND s.source_system = 'GREENLAND_GEUS';

ALTER TABLE geochem.samples DROP COLUMN _bronze_sampleid;

-- _stage_gl_samples and _gl_sample_occurrence_match stay alive -- Phase 5 and
-- Phase 6 both reuse them. map_sample_type is done with.
DROP TABLE geochem._map_sample_type;

SELECT
  count(*) AS n_total,
  count(occurrence_id) AS n_linked_to_occurrence
FROM geochem.samples WHERE source_system = 'GREENLAND_GEUS';

COMMIT;


\echo '=== PHASE 5: Greenland analytical_results (check the oxide count -- this is what unlocks alteration_box_plot.py) ==='
BEGIN;

CREATE TABLE geochem.analytical_results_greenland_geus
  PARTITION OF geochem.analytical_results FOR VALUES IN ('GREENLAND_GEUS');
CREATE TABLE geochem.result_classifications_greenland_geus
  PARTITION OF geochem.result_classifications FOR VALUES IN ('GREENLAND_GEUS');

ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels;

CREATE TABLE geochem._stage_gl_results AS
SELECT
  ar.sampleid AS bronze_sampleid, ar.package_id AS bronze_package_id,
  ar.analyte_id AS bronze_analyte_id, ar.unitid AS bronze_unit_id,
  ar.qualifier_id AS bronze_qualifier_id,
  ar.value, ar.report_number, ar.date_analysed,
  ar.lower_detection_limit, ar.upper_detection_limit
FROM bronze.analytical_results ar
WHERE ar.sampleid = ANY(ARRAY(SELECT sampleid FROM geochem._stage_gl_samples));

CREATE TABLE geochem._map_analyte AS
SELECT b.analyte_id AS bronze_id, g.analyte_id AS gold_id
FROM bronze.analytes b JOIN geochem.analytes g ON g.analyte_code = b.analyte_code;

CREATE TABLE geochem._map_unit AS
SELECT b.unitid AS bronze_id, g.unit_id AS gold_id
FROM bronze.units b JOIN geochem.units g ON g.unit_code = b.unitcode;

CREATE TABLE geochem._map_qualifier AS
SELECT b.qualifier_id AS bronze_id, g.qualifier_id AS gold_id
FROM bronze.qualifiers b JOIN geochem.qualifiers g ON g.qualifier_code = b.qualifier_code;

CREATE TABLE geochem._map_package AS
SELECT b.package_id AS bronze_id, g.package_id AS gold_id
FROM bronze.analytical_packages b JOIN geochem.analytical_packages g ON g.package_code = b.package_code;

INSERT INTO geochem.analytical_results (
  sample_id, occurrence_id, source_system, package_id,
  analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code,
  qualifier_id, qualifier_code,
  laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed,
  reviewed, is_active, created_by, created_date
)
SELECT
  e.entity_id, s.occurrence_id, 'GREENLAND_GEUS', mp.gold_id,
  ga.analyte_id, ga.analyte_name, ga.element_symbol,
  gu.unit_id, gu.unit_code,
  gq.qualifier_id, gq.qualifier_code,
  lab.lab_name, meth.method_code, meth.method_name, meth.digest_name,
  r.value, r.lower_detection_limit, r.upper_detection_limit, r.report_number, r.date_analysed,
  false, true, 'migration_greenland_20260930', now()
FROM geochem._stage_gl_results r
JOIN core.external_ids e ON e.entity_type = 'SAMPLE' AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'
  AND e.source_id = r.bronze_sampleid::text
JOIN geochem.samples s ON s.sample_id = e.entity_id AND s.source_system = 'GREENLAND_GEUS'
JOIN geochem._map_analyte ma ON ma.bronze_id = r.bronze_analyte_id
JOIN geochem.analytes ga ON ga.analyte_id = ma.gold_id
JOIN geochem._map_unit mu ON mu.bronze_id = r.bronze_unit_id
JOIN geochem.units gu ON gu.unit_id = mu.gold_id
LEFT JOIN geochem._map_qualifier mqm ON mqm.bronze_id = r.bronze_qualifier_id
LEFT JOIN geochem.qualifiers gq ON gq.qualifier_id = mqm.gold_id
LEFT JOIN geochem._map_package mp ON mp.bronze_id = r.bronze_package_id
LEFT JOIN geochem.analytical_packages gp ON gp.package_id = mp.gold_id
LEFT JOIN geochem.laboratories lab ON lab.lab_id = gp.lab_id
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = gp.method_id;

ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels;

DROP TABLE geochem._stage_gl_results;
DROP TABLE geochem._map_analyte;
DROP TABLE geochem._map_unit;
DROP TABLE geochem._map_qualifier;
DROP TABLE geochem._map_package;

SELECT
  count(*) AS n_total_results,
  count(*) FILTER (WHERE a.is_oxide) AS n_oxide_results
FROM geochem.analytical_results ar
JOIN geochem.analytes a ON a.analyte_id = ar.analyte_id
WHERE ar.source_system = 'GREENLAND_GEUS';

COMMIT;


\echo '=== PHASE 6: Greenland lithology_observations (~14,242 expected) -- LAST PHASE ==='
BEGIN;

CREATE TABLE geochem._map_lithology AS
SELECT b.lithology_id AS bronze_id, g.lithology_id AS gold_id
FROM bronze.lithology b JOIN geochem.lithology g ON g.lithology_code = b.lithology_code;

INSERT INTO geochem.lithology_observations (
  lithology_id, lithology_local, observation_context,
  sampling_line_id, sample_id, occurrence_id,
  depth_from_m, depth_to_m, logged_by, logged_date,
  strat_group, strat_formation, strat_member, strat_bed,
  alteration_id, alteration_local, comments,
  is_active, created_by, created_date
)
SELECT
  ml.gold_id, lo.lithologylocal, lo.observation_context,
  NULL,
  e_sample.entity_id,
  s_for_occ.occurrence_id,
  lo.depthfrom_m, lo.depthto_m, lo.logged_by, lo.logged_date,
  lo.stratgroup, lo.stratformation, lo.stratmember, lo.stratbed,
  NULL, lo.alterationlocal, lo.comments,
  true, 'migration_greenland_20260930', now()
FROM bronze.lithology_observations lo
JOIN bronze.locations l ON lo.locationid = l.locationid
LEFT JOIN geochem._map_lithology ml ON ml.bronze_id = lo.lithology_id
LEFT JOIN core.external_ids e_sample
  ON e_sample.entity_type = 'SAMPLE' AND e_sample.source_system = 'BRONZE_CRITICIALMINERALSEXP'
  AND e_sample.source_id = lo.sampleid::text
LEFT JOIN geochem.samples s_for_occ ON s_for_occ.sample_id = e_sample.entity_id
WHERE l.datasource = 'GEUS - Geological Survey of Denmark and Greenland'
  AND e_sample.entity_id IS NOT NULL;

DROP TABLE geochem._map_lithology;
DROP TABLE geochem._stage_gl_samples;
DROP TABLE geochem._gl_sample_occurrence_match;

SELECT count(*) AS n_lithology_observations
FROM geochem.lithology_observations WHERE created_by = 'migration_greenland_20260930';

SELECT count(*) AS n_geology_summary_rows
FROM core.geology_summary
WHERE occurrence_id IN (SELECT occurrence_id FROM core.occurrences WHERE created_by = 'migration_greenland_20260930');

COMMIT;

\echo '=== MIGRATION COMPLETE ==='
