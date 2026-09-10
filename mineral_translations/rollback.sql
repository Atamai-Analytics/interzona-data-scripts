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

-- 3. undo the buckets 1 & 3 edits (6 rows) and bucket 2 edits (4 rows)
UPDATE mineral_name_translations t
SET category = b.category, mineral_id = b.mineral_id, english_text = b.english_text,
    notes = b.notes, modified_by = b.modified_by, modified_date = b.modified_date
FROM mineral_name_translations_bak_20260910b b
WHERE b.source_text = t.source_text;

UPDATE mineral_name_translations t
SET mineral_id = b.mineral_id, english_text = b.english_text,
    modified_by = b.modified_by, modified_date = b.modified_date
FROM mineral_name_translations_bak_20260910c b
WHERE b.source_text = t.source_text;

-- 4. remove the Glauconite row added to `minerals` (only if nothing references it)
DELETE FROM minerals WHERE createdby = 'claude_mineraltrans_20260910'
  AND NOT EXISTS (SELECT 1 FROM deposit_mineralogy dm WHERE dm.mineral_id = minerals.mineral_id)
  AND NOT EXISTS (SELECT 1 FROM age_measured a WHERE a.mineral_id = minerals.mineral_id)
  AND NOT EXISTS (SELECT 1 FROM mineral_name_translations t WHERE t.mineral_id = minerals.mineral_id);

COMMIT;

-- DROP TABLE deposit_mineralogy_bak_mineraltrans_20260910;
-- DROP TABLE mineral_name_translations_bak_20260910b;
-- DROP TABLE mineral_name_translations_bak_20260910c;
