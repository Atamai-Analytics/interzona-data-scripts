-- Link age_measured.mineral_id for the SIGAM rows (dated mineral from the fact-sheet
-- "concentrado" field), + fix one bad id from apply_deposit_gaps.sql. 2026-09-10.
-- Tag: created_by / modifiedby = 'claude_age_min_20260910'.

BEGIN;

CREATE TABLE age_measured_bak_agemin_20260910 AS
SELECT age_measured_id, mineral_id FROM age_measured
WHERE createdby = 'claude_sigam_20260910' AND coalesce(mineral,'') <> '' AND mineral_id IS NULL;

-- 0. fix: apply_deposit_gaps.sql set sericita -> 2815 (Kesebolite-(Ce)); it's Muscovite (3775)
UPDATE mineral_name_translations
SET mineral_id = 3775, modified_by = 'claude_age_min_20260910', modified_date = now()
WHERE lower(source_text) = 'sericita' AND mineral_id = 2815;
UPDATE deposit_mineralogy SET mineral_id = 3775
WHERE mineral_id = 2815 AND lower(btrim(mineral_name_local)) = 'sericita';

-- 1. translations surfaced by the age_measured "concentrado" field
INSERT INTO mineral_name_translations (source_text, english_text, mineral_id, category, notes, created_by)
VALUES
  ('moscovita', 'Muscovite', 3775, 'species', 'alt spelling of muscovita; surfaced by age_measured', 'claude_age_min_20260910'),
  ('circon', 'Zircon', 6155, 'species', 'alt spelling of zircon; surfaced by age_measured', 'claude_age_min_20260910'),
  ('feldespato potasico', 'Orthoclase', 4098, 'species', 'K-feldspar; surfaced by age_measured', 'claude_age_min_20260910'),
  ('galena', 'Galena', 1961, 'species', 'surfaced by age_measured', 'claude_age_min_20260910'),
  ('alunita', 'Alunite', 152, 'species', 'surfaced by age_measured', 'claude_age_min_20260910'),
  ('sanidina', 'Sanidine', 4891, 'species', 'surfaced by age_measured', 'claude_age_min_20260910'),
  ('pechblenda', 'Uraninite', 5694, 'variety', 'pitchblende = massive uraninite; surfaced by age_measured', 'claude_age_min_20260910'),
  ('circón', 'Zircon', 6155, 'species', 'accented variant; surfaced by age_measured', 'claude_age_min_20260910'),
  ('feldespato potásico', 'Orthoclase', 4098, 'species', 'K-feldspar, accented; surfaced by age_measured', 'claude_age_min_20260910')
ON CONFLICT (source_text) DO NOTHING;

-- adularia is present with mineral_id NULL -> it's the low-T K-feldspar variety
UPDATE mineral_name_translations
SET mineral_id = 4098, category = 'variety', modified_by = 'claude_age_min_20260910', modified_date = now()
WHERE lower(source_text) = 'adularia' AND mineral_id IS NULL;

-- 2. relink age_measured from the translation table (exact match on the mineral text)
WITH upd AS (
  UPDATE age_measured am SET mineral_id = t.mineral_id, modifiedby = 'claude_age_min_20260910', modifieddate = now()
  FROM mineral_name_translations t
  WHERE am.createdby = 'claude_sigam_20260910'
    AND am.mineral_id IS NULL
    AND coalesce(am.mineral,'') <> ''
    AND t.mineral_id IS NOT NULL
    AND lower(btrim(am.mineral)) = lower(t.source_text)
  RETURNING am.age_measured_id
)
SELECT count(*) AS age_rows_linked FROM upd;

SELECT count(*) FILTER (WHERE mineral_id IS NOT NULL) AS linked,
       count(*) FILTER (WHERE mineral_id IS NULL) AS still_null
FROM age_measured WHERE createdby = 'claude_sigam_20260910' AND coalesce(mineral,'') <> '';

COMMIT;
