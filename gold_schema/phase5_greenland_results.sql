-- PHASE 5: analytical_results for the Phase 4 samples. New LIST partitions
-- are needed first (same pattern as ARGENTINA_SEGEMAR's own partition --
-- without this, GREENLAND_GEUS rows would silently land in the DEFAULT
-- partition rather than getting a dedicated one). Requires Phase 4
-- committed first (reuses its _stage_gl_samples table).

BEGIN;

CREATE TABLE geochem.analytical_results_greenland_geus
  PARTITION OF geochem.analytical_results FOR VALUES IN ('GREENLAND_GEUS');
CREATE TABLE geochem.result_classifications_greenland_geus
  PARTITION OF geochem.result_classifications FOR VALUES IN ('GREENLAND_GEUS');

ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels;

CREATE TABLE geochem._stage_gl_results AS
SELECT
  ar.sampleid AS bronze_sampleid,
  ar.package_id AS bronze_package_id,
  ar.analyte_id AS bronze_analyte_id,
  ar.unitid AS bronze_unit_id,
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

-- Verify: total result count, plus the oxide-specific count -- THIS is the
-- number that actually unlocks alteration_box_plot.py. The 300-sample spot
-- check earlier implied roughly 9.7% of samples carry a full major-oxide
-- suite, so expect this to land in the low thousands.
SELECT
  count(*) AS n_total_results,
  count(*) FILTER (WHERE a.is_oxide) AS n_oxide_results
FROM geochem.analytical_results ar
JOIN geochem.analytes a ON a.analyte_id = ar.analyte_id
WHERE ar.source_system = 'GREENLAND_GEUS';

-- Review the output above, then type COMMIT; or ROLLBACK;
-- IMPORTANT: if you ROLLBACK here, re-run this whole file from scratch --
-- _stage_gl_samples (from Phase 4) is untouched either way, so no need to
-- redo Phase 4.
