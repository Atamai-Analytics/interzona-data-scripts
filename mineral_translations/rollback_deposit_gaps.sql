-- Rollback for apply_deposit_gaps.sql + apply_task1_commodities.sql (2026-09-10).
BEGIN;
DELETE FROM deposit_commodities         WHERE createdby  = 'claude_deposit_gap_20260910';
DELETE FROM deposit_mineralogy          WHERE createdby  = 'claude_sigam_min_20260910';
DELETE FROM mineral_name_translations   WHERE created_by = 'claude_deposit_gap_20260910';
COMMIT;
-- DROP TABLE IF EXISTS deposit_mineralogy_bak_sigammin_20260910;
