-- WA deposit extract — Step 4a: tokenize commodities per canonical deposit.
-- Builds wa_canonical_commodity_tok (canonical_id, token, role, n_members_with).
-- Role = PRIMARY if any member carried the token as its primary_commodity / single
-- commodity / industrial-mineral name; else SECONDARY.

BEGIN;

-- normalize one raw commodity phrase to a lowercase token (or '' to drop)
CREATE OR REPLACE FUNCTION pg_temp.wa_tok(raw text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN t = '' THEN ''
    -- drop commodities the source itself flags as uncertain
    WHEN lower(coalesce(raw,'')) ~ '\?|^\s*reportedly|doubtful' THEN ''
    WHEN length(t) > 45 THEN ''
    WHEN t ~ '(report|doubtful|occurrence|erroneous|authenticated|unlikely|apparently|constitute|although| are | is |spectrographic|principal value|present\.?$|also reported|has been|have been|failed to|radioactive)' THEN ''
    ELSE t
  END
  FROM (
    SELECT btrim(regexp_replace(
             regexp_replace(
               regexp_replace(lower(coalesce(raw,'')), E'[\r\n]+', ' ', 'g'),
               '\s*\([a-z0-9]{1,4}\)\s*$', '', 'g'),         -- strip "(Cu)" symbol suffix
             '^(and|reportedly|native)\s+|[?.\s]+$', '', 'g') -- strip leading noise / trailing ? .
           ) t
  ) s
$$;

-- explode a raw field (comma / semicolon list) into tokens
CREATE OR REPLACE FUNCTION pg_temp.wa_toks(raw text) RETURNS SETOF text LANGUAGE sql IMMUTABLE AS $$
  SELECT DISTINCT x FROM (
    SELECT pg_temp.wa_tok(unnest(string_to_array(regexp_replace(coalesce(raw,''), ';', ',', 'g'), ','))) x
  ) q WHERE x <> ''
$$;

DROP TABLE IF EXISTS wa_canonical_commodity_tok;
CREATE TABLE wa_canonical_commodity_tok AS
WITH m AS (
    SELECT c.cluster_id AS canonical_id, s.*
    FROM wa_deposits_staging s
    JOIN wa_cluster_assignment c USING (staging_id)
    WHERE NOT s.excluded
),
tok AS (
    -- primary sources: primary_commodity / single hazard commodity / mineral name  -> PRIMARY
    SELECT canonical_id, t AS token, 'PRIMARY'::text AS role
    FROM m, LATERAL pg_temp.wa_toks(m.primary_commodity) t
    UNION ALL
    SELECT canonical_id, t, 'PRIMARY'
    FROM m, LATERAL pg_temp.wa_toks(m.mineral) t
    UNION ALL
    -- commodities list -> SECONDARY (promoted to PRIMARY below if it also appears as primary)
    SELECT canonical_id, t, 'SECONDARY'
    FROM m, LATERAL pg_temp.wa_toks(m.commodities) t
)
SELECT canonical_id, token,
       CASE WHEN bool_or(role = 'PRIMARY') THEN 'PRIMARY' ELSE 'SECONDARY' END AS role,
       count(*) AS mentions
FROM tok
GROUP BY canonical_id, token;

ALTER TABLE wa_canonical_commodity_tok ADD PRIMARY KEY (canonical_id, token);

COMMIT;

\echo '--- distinct tokens (for crosswalk) ---'
\pset format csv
\o wa_deposit_extract/staging/_commodity_tokens.csv
SELECT token,
       count(*) AS n_deposits,
       count(*) FILTER (WHERE role = 'PRIMARY') AS n_primary
FROM wa_canonical_commodity_tok
GROUP BY token ORDER BY n_deposits DESC;
\o
\pset format aligned
SELECT count(DISTINCT token) AS distinct_tokens,
       count(*) AS canonical_commodity_rows,
       count(DISTINCT canonical_id) AS canonical_with_commodity
FROM wa_canonical_commodity_tok;
