-- WA deposit extract — Step 3b: flatten embedded newlines in the loaded comments.
-- The Step-3 load joined comment sections with '\n' / '\n\n'; those break CSV / flat
-- exports. Collapse every newline run (plus surrounding whitespace) to ' | '.
-- Source text has no newlines, so this only touches the separators 09_load.sql added.
-- Idempotent. 09_load.sql has been updated to emit the flat form directly.

BEGIN;

UPDATE locations
SET comments = btrim(regexp_replace(regexp_replace(comments, E'\\s*[\r\n]+\\s*', ' | ', 'g'),
                                    E'\\s*·\\s*', ' | ', 'g'))
WHERE createdby = 'claude_wa_20260910' AND comments ~ E'[\r\n·]';

UPDATE deposits d
SET comments = btrim(regexp_replace(regexp_replace(d.comments, E'\\s*[\r\n]+\\s*', ' | ', 'g'),
                                    E'\\s*·\\s*', ' | ', 'g'))
FROM locations l
WHERE d.locationid = l.locationid
  AND l.createdby = 'claude_wa_20260910'
  AND d.comments ~ E'[\r\n·]';

COMMIT;

\echo '--- remaining rows with newlines (should be 0 / 0) ---'
SELECT
  (SELECT count(*) FROM locations WHERE createdby='claude_wa_20260910' AND comments ~ '[\r\n]') AS loc,
  (SELECT count(*) FROM deposits d JOIN locations l USING(locationid)
     WHERE l.createdby='claude_wa_20260910' AND d.comments ~ '[\r\n]') AS dep;
