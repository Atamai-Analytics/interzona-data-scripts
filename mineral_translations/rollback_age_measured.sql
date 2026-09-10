-- Rollback for apply_age_measured_links.sql (2026-09-10).
BEGIN;

-- un-link the age_measured rows
UPDATE age_measured am SET mineral_id = b.mineral_id, modifiedby = NULL, modifieddate = NULL
FROM age_measured_bak_agemin_20260910 b
WHERE b.age_measured_id = am.age_measured_id;

-- remove the translations this run added
DELETE FROM mineral_name_translations WHERE created_by = 'claude_age_min_20260910';

-- revert the adularia + sericita edits (both were mineral_id NULL / 2815 before)
UPDATE mineral_name_translations SET mineral_id = NULL, category = 'variety', modified_by = NULL, modified_date = NULL
WHERE lower(source_text) = 'adularia';
UPDATE mineral_name_translations SET mineral_id = 2815, modified_by = 'claude_deposit_gap_20260910'
WHERE lower(source_text) = 'sericita';
UPDATE deposit_mineralogy SET mineral_id = 2815
WHERE mineral_id = 3775 AND lower(btrim(mineral_name_local)) = 'sericita';

COMMIT;
-- DROP TABLE age_measured_bak_agemin_20260910;
