-- Rollback for apply_mineral_translations.sql (criticialmineralsexp, 2026-09-10).

BEGIN;

-- 1. un-link the deposit_mineralogy rows this run touched
UPDATE deposit_mineralogy dm
SET mineral_id = NULL
FROM deposit_mineralogy_bak_mineraltrans_20260910 b
WHERE b.deposit_mineralogy_id = dm.deposit_mineralogy_id
  AND b.mineral_id IS NULL
  AND dm.mineral_id IS NOT NULL;

-- 2. remove the translation entries this run added
DELETE FROM mineral_name_translations WHERE created_by = 'claude_mineraltrans_20260910';

COMMIT;

-- DROP TABLE deposit_mineralogy_bak_mineraltrans_20260910;
