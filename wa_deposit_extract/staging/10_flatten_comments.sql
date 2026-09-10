-- WA deposit extract — Step 3b: flatten embedded newlines in the loaded comments.
-- The Step-3 load joined comment sections with '\n' / '\n\n'; those break CSV / flat
-- exports. Collapse every newline run (plus surrounding whitespace) to ' | '.
-- Source text has no newlines, so this only touches the separators 09_load.sql added.
-- Idempotent. 09_load.sql has been updated to emit the flat form directly.

-- one flat, tidy comment string:
--   * newline / tab runs        -> ' | '
--   * legacy ' · ' separators   -> ' | '
--   * collapsed ' | | '         -> ' | '
--   * leading / trailing ' | '  -> trimmed
CREATE OR REPLACE FUNCTION pg_temp.wa_flat(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT btrim(
           regexp_replace(
             regexp_replace(
               regexp_replace(coalesce(t, ''), E'[ \t]*[\r\n\t·]+[ \t·]*', ' | ', 'g'),
               '( *\| *){2,}', ' | ', 'g'),
             '^ *\| *| *\| *$', '', 'g')
         )
$$;

BEGIN;

UPDATE locations
SET comments = pg_temp.wa_flat(comments)
WHERE createdby = 'claude_wa_20260910' AND comments <> pg_temp.wa_flat(comments);

UPDATE deposits d
SET comments = pg_temp.wa_flat(d.comments)
FROM locations l
WHERE d.locationid = l.locationid
  AND l.createdby = 'claude_wa_20260910'
  AND d.comments <> pg_temp.wa_flat(d.comments);

COMMIT;

\echo '--- remaining control chars (should be 0 / 0) ---'
SELECT
  (SELECT count(*) FROM locations WHERE createdby='claude_wa_20260910' AND comments ~ '[\x00-\x1F]') AS loc,
  (SELECT count(*) FROM deposits d JOIN locations l USING(locationid)
     WHERE l.createdby='claude_wa_20260910' AND d.comments ~ '[\x00-\x1F]') AS dep;
