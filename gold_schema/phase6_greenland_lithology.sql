-- PHASE 6: lithology_observations for Greenland (14,242 real rows, tied to
-- locationid in bronze -- feeds core.geology_summary automatically via the
-- existing refresh triggers once inserted, no new trigger needed). Requires
-- Phase 4 committed first (reuses its _stage_gl_samples table). This is the
-- LAST phase -- it also drops the two scratch tables Phase 4 left alive.
--
-- NOTE: alteration_id mapping is deliberately NOT attempted here -- bronze's
-- alteration-reference table name/column was not verified when this script
-- was written, and guessing wrong risks a hard SQL error rather than a
-- harmless gap. alteration_local (free text) is carried over; alteration_id
-- is left NULL. If you want it, send me the bronze table/column name and
-- I'll give you a small follow-up UPDATE script.

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

-- Verify: expect close to 14,242, and at least some geology_summary rows
-- for the 28 Greenland occurrences (only occurrence-linked samples' lithology
-- feeds geology_summary, so this second count will be much smaller than the
-- first -- that's expected, not a bug).
SELECT count(*) AS n_lithology_observations
FROM geochem.lithology_observations WHERE created_by = 'migration_greenland_20260930';

SELECT count(*) AS n_geology_summary_rows
FROM core.geology_summary
WHERE occurrence_id IN (SELECT occurrence_id FROM core.occurrences WHERE created_by = 'migration_greenland_20260930');

-- Review the output above, then type COMMIT; or ROLLBACK;
-- This is the last phase -- once committed, the migration is complete.
