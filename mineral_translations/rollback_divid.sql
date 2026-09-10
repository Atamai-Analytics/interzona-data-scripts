-- Rollback for apply_divid_backfill.sql + apply_divid_correction.sql (2026-09-10).
BEGIN;
UPDATE locations l SET divisionid = b.divisionid, modifiedby = NULL, modifieddate = NULL
FROM locations_divid_bak_20260910 b
WHERE b.locationid = l.locationid;
COMMIT;
-- DROP TABLE locations_divid_bak_20260910;
