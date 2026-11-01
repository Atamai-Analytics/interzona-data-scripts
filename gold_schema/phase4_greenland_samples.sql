-- PHASE 4: Greenland samples -- the full ~49,400 bronze samples for the
-- country, not just the handful near a known deposit. Each is matched to its
-- nearest Greenland occurrence within 5km; anything beyond 5km gets
-- occurrence_id = NULL, which is correct, not a gap -- most of this dataset
-- is regional survey data with no nearby catalogued deposit.
-- Requires Phase 3 committed first.

BEGIN;

CREATE TABLE geochem._stage_gl_samples AS
SELECT
  s.sampleid,
  l.latitude, l.longitude, l.elevation,
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

-- Nearest-occurrence match (local-to-local join: both the staged samples and
-- the 28 Greenland occurrences from Phase 3 are local tables, so this is
-- cheap even unindexed at this scale).
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

-- Keep _stage_gl_samples and _gl_sample_occurrence_match alive -- Phase 5
-- and Phase 6 both reuse them. Only drop the sample_type mapping now.
DROP TABLE geochem._map_sample_type;

-- Verify: expect ~49,400 total, ~604 with occurrence_id set.
SELECT
  count(*) AS n_total,
  count(occurrence_id) AS n_linked_to_occurrence
FROM geochem.samples WHERE source_system = 'GREENLAND_GEUS';

-- Review the output above, then type COMMIT; or ROLLBACK;
-- IMPORTANT: if you ROLLBACK here, _stage_gl_samples and
-- _gl_sample_occurrence_match roll back too -- re-run this whole file from
-- scratch, don't try to resume mid-way.
