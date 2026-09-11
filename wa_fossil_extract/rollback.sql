-- Reverse staging/01_load.sql. Children first.
DELETE FROM age_stratigraphic WHERE created_by = 'claude_wa_fossil_20260911';
DELETE FROM locations WHERE createdby = 'claude_wa_fossil_20260911'
  AND external_id LIKE 'WA-AGE:fossil:%'
  AND NOT EXISTS (SELECT 1 FROM age_stratigraphic a WHERE a.locationid = locations.locationid);
DROP TABLE IF EXISTS wa_fossil_age_crosswalk;
