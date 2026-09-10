-- WA deposit extract — Step 2g: fix the iaml `material` mis-mapping.
--
-- 01_staging.sql routed iaml `material` into wa_deposits_staging.ore_minerals, but that
-- field is abandoned-mine-land site debris ("ore car", "scrap steel", "6\" pipe", "none",
-- "see feature 1003-14"), NOT mineralogy. Move the meaningful values into `comments`,
-- clear `ore_minerals` for iaml, rebuild the canonical + loaded mineralogy / comments.
--
-- 01_staging.sql has been corrected so a fresh run does the right thing.

\set ON_ERROR_STOP on
BEGIN;

-- 1. staging: material -> comments (skip null / none / no / n/a), then clear ore_minerals
UPDATE wa_deposits_staging s
SET comments = btrim(concat_ws(' | ',
                 nullif(s.comments, ''),
                 'Site remains (IAML): ' || s.ore_minerals))
WHERE s.wa_source = 'iaml'
  AND s.ore_minerals IS NOT NULL
  AND lower(s.ore_minerals) !~ '^(none|no|n/?a|none observed|not applicable)\.?$';

UPDATE wa_deposits_staging
SET ore_minerals = NULL
WHERE wa_source = 'iaml' AND ore_minerals IS NOT NULL;

COMMIT;

-- 2. rebuild canonical (04) + commodity tok (07) — run those files after this one:
--    psql -f wa_deposit_extract/staging/04_canonical.sql
--    psql -f wa_deposit_extract/staging/07_commodities.sql
-- then refresh the loaded mineralogy + comments:

\i wa_deposit_extract/staging/04_canonical.sql
\i wa_deposit_extract/staging/07_commodities.sql

BEGIN;

-- 3. rebuild deposit_mineralogy for the WA load from the corrected canonical
DELETE FROM deposit_mineralogy WHERE createdby = 'claude_wa_20260910';

INSERT INTO deposit_mineralogy (depositid, mineral_id, mineral_name_local, role_raw, createdby)
SELECT d.depositid, mn.mineral_id, tok.name_l, 'DGER ore_minerals', 'claude_wa_20260910'
FROM (
    SELECT c.canonical_id, lower(btrim(t)) AS name_l
    FROM wa_dedup_canonical c, unnest(c.ore_mineral_tokens) t
    WHERE btrim(t) <> ''
    GROUP BY c.canonical_id, lower(btrim(t))
) tok
JOIN locations l ON l.external_id = 'WA:' || tok.canonical_id AND l.createdby = 'claude_wa_20260910'
JOIN deposits  d ON d.locationid = l.locationid
LEFT JOIN LATERAL (
    SELECT mineral_id FROM minerals WHERE lower(mineral_name) = tok.name_l LIMIT 1
) mn ON true;

-- 4. rebuild deposits.comments for the WA load from the corrected canonical
UPDATE deposits d
SET comments = regexp_replace(concat_ws(' | ',
        nullif(btrim(c.comments_all), ''),
        CASE WHEN nullif(btrim(c.value_all), '') IS NOT NULL
             THEN 'Value / significance: ' || c.value_all END,
        CASE WHEN array_length(c.ore_mineral_tokens, 1) IS NOT NULL
             THEN 'Ore minerals (DGER): ' || array_to_string(c.ore_mineral_tokens, ', ') END,
        CASE WHEN c.any_assay_flag THEN 'Assays recorded in DGER source.' END,
        'LithoSurfer sourceId: WA:' || c.canonical_id
     ), E'[ \t]*[\r\n\t·]+[ \t·]*', ' | ', 'g')
FROM wa_dedup_canonical c
JOIN locations l ON l.external_id = 'WA:' || c.canonical_id AND l.createdby = 'claude_wa_20260910'
WHERE d.locationid = l.locationid;

COMMIT;

\echo '--- iaml-material tokens remaining in loaded mineralogy (should be 0) ---'
SELECT count(*) FROM deposit_mineralogy
WHERE createdby='claude_wa_20260910'
  AND mineral_name_local ~ '(scrap steel|ore car|piping|pipe|tank|kiln|nuts and bolts|see feature|hazmat comment)';

\echo '--- mineralogy totals after fix ---'
SELECT count(*) total, count(mineral_id) resolved FROM deposit_mineralogy WHERE createdby='claude_wa_20260910';
