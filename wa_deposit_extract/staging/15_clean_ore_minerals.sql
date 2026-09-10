-- WA deposit extract — Step 2i: clean prose out of ore_minerals / deposit_mineralogy.
--
-- Spot-check found ~87 deposit_mineralogy rows that are phrases, not mineral names:
-- "some chalcopyrite", "minor amounts of sphalerite", "reportedly stibnite",
-- "cinnabar was found in nw 1/4 sec. 25", "ore on dump similar to gould & curry".
-- DGER's ore_minerals field is free text with quantifiers/commentary; the naive
-- comma-split carried them through. 04_canonical.sql now runs each token through
-- pg_temp.wa_min() (strip leading quantifier, drop residual prose).
--
-- This re-runs 04, then rebuilds the loaded deposit_mineralogy + deposits.comments
-- ("Ore minerals (DGER):" line) for the WA load. Run from repo root.

\set ON_ERROR_STOP on

\i wa_deposit_extract/staging/04_canonical.sql

BEGIN;

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

\echo '--- mineralogy after clean ---'
SELECT count(*) total, count(mineral_id) resolved,
       count(*) FILTER (WHERE mineral_name_local ~ '^(some|minor|trace|reportedly|possibly|probably|much|abundant|free|small|lesser) ') AS still_prose
FROM deposit_mineralogy WHERE createdby='claude_wa_20260910';
