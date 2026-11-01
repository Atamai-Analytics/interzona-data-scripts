-- PHASE 1: Argentina backfill -- samples excluded from the original
-- 2026-09-25 migration (anything not already recorded in core.external_ids
-- as a BRONZE_CRITICIALMINERALSEXP SAMPLE). This is overwhelmingly stream-
-- sediment regional survey data (~36,240 of ~38,900 total Argentina bronze
-- samples) that was never deposit-proximal to begin with -- it migrates as
-- standalone points (occurrence_id NULL). Requires Phase 0 committed first.

BEGIN;

-- Stage ALL Argentina bronze samples with a single foreign-only scan (no
-- join against the local external_ids table in this step -- that combination
-- is what caused the original migration's analytical_results join to time
-- out; stage first, filter locally after).
CREATE TABLE geochem._stage_ar_backfill_samples AS
SELECT
  s.sampleid,
  l.latitude,
  l.longitude,
  l.elevation,
  s.sample_type_id AS bronze_sample_type_id,
  s.sampletypelocal,
  s.sample_context,
  s.samplenumber,
  s.samplenumberalt,
  s.fieldid,
  s.sampledate,
  s.sample_weight_kg,
  s.depthfrom_m,
  s.depthto_m
FROM bronze.samples s
JOIN bronze.locations l ON s.locationid = l.locationid
JOIN bronze.countries c ON l.countryid = c.countryid
WHERE c.countryname ILIKE '%argentina%';

-- Exclude samples already migrated in the original Argentina slice (local
-- join now -- fast).
DELETE FROM geochem._stage_ar_backfill_samples t
WHERE EXISTS (
  SELECT 1 FROM core.external_ids e
  WHERE e.entity_type = 'SAMPLE'
    AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'
    AND e.source_id = t.sampleid::text
);

-- sample_type mapping (bronze -> gold), tiny table, cheap foreign-to-local join.
CREATE TABLE geochem._map_sample_type AS
SELECT b.sample_type_id AS bronze_id, g.sample_type_id AS gold_id
FROM bronze.sample_types b
JOIN geochem.sample_types g ON g.sample_type_code = b.sample_type_code;

-- Insert as standalone samples (occurrence_id and sampling_line_id both
-- NULL -- valid as of Phase 0). _bronze_sampleid is a temporary column used
-- only to build the external_ids lineage immediately below, then dropped.
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

-- Verify: expect ~30,700
SELECT count(*) AS n_backfilled_samples
FROM geochem.samples WHERE created_by = 'migration_argentina_backfill_20260930';

-- Review the output above, then type COMMIT; or ROLLBACK;
