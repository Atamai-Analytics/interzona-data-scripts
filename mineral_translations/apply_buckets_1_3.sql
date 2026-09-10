-- Follow-up to apply_mineral_translations.sql: the 10 species-category / mineral_id NULL rows.
-- Bucket 1: tetraedrita / tennantita / tenantita are GROUP names -> recategorise, stay NULL.
-- Bucket 3: andorita -> Senandorite (5022); thorogummita/torogummita -> Thorite (5497).
-- Bucket 2 (romanechita/thenardita/glauconita/kesterita) left alone - not in `minerals`.
-- criticialmineralsexp, 2026-09-10. Tag: modified_by = 'claude_mineraltrans_20260910'.

BEGIN;

CREATE TABLE mineral_name_translations_bak_20260910b AS
SELECT * FROM mineral_name_translations
WHERE lower(source_text) IN ('tetraedrita','tennantita','tenantita','andorita','thorogummita','torogummita');

-- Bucket 1
UPDATE mineral_name_translations
SET category = 'group', modified_by = 'claude_mineraltrans_20260910', modified_date = now()
WHERE lower(source_text) IN ('tetraedrita','tennantita','tenantita');

-- Bucket 3
UPDATE mineral_name_translations
SET mineral_id = 5022, notes = 'approx: historical andorite = andorite-VI = senandorite',
    modified_by = 'claude_mineraltrans_20260910', modified_date = now()
WHERE lower(source_text) = 'andorita';

UPDATE mineral_name_translations
SET mineral_id = 5497, notes = 'approx: thorogummite discredited = hydrous/metamict thorite',
    modified_by = 'claude_mineraltrans_20260910', modified_date = now()
WHERE lower(source_text) IN ('thorogummita','torogummita');

-- relink deposit_mineralogy for the bucket-3 names now that they carry a mineral_id
WITH upd AS (
  UPDATE deposit_mineralogy dm
  SET mineral_id = t.mineral_id
  FROM mineral_name_translations t
  WHERE dm.mineral_id IS NULL
    AND t.mineral_id IS NOT NULL
    AND lower(btrim(dm.mineral_name_local)) = lower(t.source_text)
  RETURNING dm.deposit_mineralogy_id, dm.depositid
)
SELECT count(*) AS rows_linked, count(DISTINCT depositid) AS deposits FROM upd;

SELECT source_text, english_text, mineral_id, category, notes
FROM mineral_name_translations
WHERE lower(source_text) IN ('tetraedrita','tennantita','tenantita','andorita','thorogummita','torogummita')
ORDER BY source_text;

COMMIT;
