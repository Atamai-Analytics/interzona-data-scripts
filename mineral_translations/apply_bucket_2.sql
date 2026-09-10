-- Bucket 2: the 4 "missing" minerals for SEGEMAR deposit_mineralogy.
-- Finding: 3 of the 4 already exist in `minerals` under their mindat diacritic spelling
-- (Romanèchite 4776, Thénardite 5505, Kësterite 3014) - the translation rows just had
-- plain-ASCII english_text so they never linked. Only Glauconite is genuinely absent.
-- criticialmineralsexp, 2026-09-10. Run with PGCLIENTENCODING=UTF8.

BEGIN;

CREATE TABLE mineral_name_translations_bak_20260910c AS
SELECT * FROM mineral_name_translations
WHERE lower(source_text) IN ('romanechita','thenardita','glauconita','kesterita');

-- 1. add the one genuinely-missing species (mindat min-1710)
INSERT INTO minerals
  (mindat_id, mineral_name, ima_formula, ima_abbreviation, ima_status,
   strunz_code, strunz_class, strunz_subclass, strunz_family,
   dana_class, dana_type, crystal_system, description, createdby)
VALUES
  (1710, 'Glauconite', '(K,Na)(Fe,Al,Mg)2(Si,Al)4O10(OH)2', 'Glt', 'APPROVED',
   '9.E.C', '9', 'E', 'C', '71', '2', 'Monoclinic',
   'Iron-potassium phyllosilicate of the mica group; authigenic marine mineral (greensand). Added 2026-09-10 for SEGEMAR deposit_mineralogy linkage.',
   'claude_mineraltrans_20260910')
ON CONFLICT (mineral_name) DO NOTHING;

-- 2. point the 4 translation rows at the right mineral_id + fix english_text to the
--    canonical (accented) spelling
UPDATE mineral_name_translations SET mineral_id = 4776, english_text = 'Romanèchite',
       modified_by = 'claude_mineraltrans_20260910', modified_date = now()
WHERE lower(source_text) = 'romanechita';

UPDATE mineral_name_translations SET mineral_id = 5505, english_text = 'Thénardite',
       modified_by = 'claude_mineraltrans_20260910', modified_date = now()
WHERE lower(source_text) = 'thenardita';

UPDATE mineral_name_translations SET mineral_id = 3014, english_text = 'Kësterite',
       modified_by = 'claude_mineraltrans_20260910', modified_date = now()
WHERE lower(source_text) = 'kesterita';

UPDATE mineral_name_translations t SET mineral_id = m.mineral_id,
       modified_by = 'claude_mineraltrans_20260910', modified_date = now()
FROM minerals m
WHERE m.mineral_name = 'Glauconite' AND lower(t.source_text) = 'glauconita';

-- 3. relink deposit_mineralogy
WITH upd AS (
  UPDATE deposit_mineralogy dm SET mineral_id = t.mineral_id
  FROM mineral_name_translations t
  WHERE dm.mineral_id IS NULL AND t.mineral_id IS NOT NULL
    AND lower(btrim(dm.mineral_name_local)) = lower(t.source_text)
  RETURNING dm.deposit_mineralogy_id, dm.depositid
)
SELECT count(*) AS rows_linked, count(DISTINCT depositid) AS deposits FROM upd;

SELECT t.source_text, t.english_text, t.mineral_id, m.mineral_name
FROM mineral_name_translations t JOIN minerals m ON m.mineral_id = t.mineral_id
WHERE lower(t.source_text) IN ('romanechita','thenardita','glauconita','kesterita')
ORDER BY t.source_text;

COMMIT;
