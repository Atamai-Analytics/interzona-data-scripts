-- Reverse 01_load.sql.  Children first.
DELETE FROM age_measured  WHERE createdby = 'claude_wa_age_20260910';
DELETE FROM locations     WHERE createdby = 'claude_wa_age_20260910'
  AND external_id LIKE 'WA-AGE:%'
  AND NOT EXISTS (SELECT 1 FROM age_measured am WHERE am.locationid = locations.locationid);
DELETE FROM age_reference WHERE createdby = 'claude_wa_age_20260910';
-- Note: the 8 dating_method_reference rows (ids 20-27, S3) are left in place;
-- they are schema, not load data.  Remove manually if truly unwinding S3.
