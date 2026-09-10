-- WA deposit extract — Step 3: load wa_dedup_canonical into the curated tables.
-- One transaction. Everything tagged createdby='claude_wa_20260910'. Reversible — see
-- the rollback block at the bottom. Snapshots deposits / deposit_commodities /
-- deposit_mineralogy first (locations rolls back by the createdby tag, as SIGAM did).
--
-- Run from anywhere:  psql -v ON_ERROR_STOP=1 -f wa_deposit_extract/staging/09_load.sql
-- (\copy path below is absolute so cwd does not matter.)

\set ON_ERROR_STOP on
BEGIN;

-- ============================================================ 1. snapshots
DROP TABLE IF EXISTS deposits_bak_wa_20260910;
DROP TABLE IF EXISTS deposit_commodities_bak_wa_20260910;
DROP TABLE IF EXISTS deposit_mineralogy_bak_wa_20260910;
CREATE TABLE deposits_bak_wa_20260910            AS TABLE deposits;
CREATE TABLE deposit_commodities_bak_wa_20260910 AS TABLE deposit_commodities;
CREATE TABLE deposit_mineralogy_bak_wa_20260910  AS TABLE deposit_mineralogy;

-- guard: refuse to double-load
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM locations WHERE createdby = 'claude_wa_20260910') THEN
     RAISE EXCEPTION 'WA rows already present (createdby=claude_wa_20260910) — roll back first';
  END IF;
END $$;

-- ============================================================ 2. commodity crosswalk
DROP TABLE IF EXISTS wa_commodity_xwalk_raw;
CREATE TABLE wa_commodity_xwalk_raw (
    token text, n_deposits int, n_primary int,
    commodity_id text, commodity_name text, method text);
\copy wa_commodity_xwalk_raw FROM 'C:/Users/dean/claude_lithosurfer/lithosurfer-work/wa_deposit_extract/staging/crosswalk_commodity_wa.csv' WITH (FORMAT csv, HEADER true)

DROP TABLE IF EXISTS wa_commodity_xwalk;
CREATE TABLE wa_commodity_xwalk AS
SELECT DISTINCT token, commodity_id::int AS commodity_id
FROM wa_commodity_xwalk_raw
WHERE method <> 'DROP' AND btrim(coalesce(commodity_id, '')) <> '';
ALTER TABLE wa_commodity_xwalk ADD PRIMARY KEY (token, commodity_id);

-- ============================================================ 3. id map
DROP TABLE IF EXISTS wa_load_map;
CREATE TABLE wa_load_map (canonical_id int PRIMARY KEY, locationid int, depositid int);

-- ============================================================ 4. locations
WITH ins AS (
  INSERT INTO locations
      (locationcode, locationname, locationtype, latitude, longitude,
       countryid, divisionid, datasource, datasource_url, external_id, comments, createdby)
  SELECT 'WA',
         left(coalesce(c.name,
              'Unnamed DGER ' || c.sources[1] || ' site ' || c.canonical_id), 255),
         'DEPOSIT', c.latitude, c.longitude,
         246, 48,
         'Washington State Geological Survey (DGER)',
         'https://www.dnr.wa.gov/geologyportal',
         'WA:' || c.canonical_id,
         regexp_replace(concat_ws(' | ',
            'DGER sources: ' || array_to_string(c.sources, ', ')
                || ' (' || array_to_string(c.member_keys, ' ; ') || ')',
            CASE WHEN c.mining_district IS NOT NULL THEN 'Mining district: ' || c.mining_district END,
            CASE WHEN c.county IS NOT NULL THEN 'County: ' || c.county END,
            CASE WHEN nullif(btrim(c.all_names), '') IS NOT NULL
                  AND lower(c.all_names) <> lower(coalesce(c.name, ''))
                 THEN 'Names / aliases: ' || c.all_names END,
            CASE WHEN nullif(btrim(c.loc_desc_all), '') IS NOT NULL
                 THEN 'Location notes: ' || c.loc_desc_all END,
            CASE WHEN c.member_spread_m > 100
                 THEN 'Merged from DGER records up to ' || c.member_spread_m || ' m apart' END
         ), E'\\s*[\r\n]+\\s*', ' | ', 'g'),
         'claude_wa_20260910'
  FROM wa_dedup_canonical c
  RETURNING locationid, external_id
)
INSERT INTO wa_load_map (canonical_id, locationid)
SELECT replace(external_id, 'WA:', '')::int, locationid FROM ins;

-- ============================================================ 5. deposits
WITH ins AS (
  INSERT INTO deposits
      (locationid, deposit_type_id, geological_district,
       production_data, "references", comments, createdby)
  SELECT m.locationid, NULL, c.mining_district,
         CASE WHEN c.any_production_flag
              THEN 'Production recorded (DGER occurrence-inventory flag; source carries no grade or tonnage).' END,
         nullif(btrim(c.references_all), ''),
         regexp_replace(concat_ws(' | ',
            nullif(btrim(c.comments_all), ''),
            CASE WHEN nullif(btrim(c.value_all), '') IS NOT NULL
                 THEN 'Value / significance: ' || c.value_all END,
            CASE WHEN array_length(c.ore_mineral_tokens, 1) IS NOT NULL
                 THEN 'Ore minerals (DGER): ' || array_to_string(c.ore_mineral_tokens, ', ') END,
            CASE WHEN c.any_assay_flag
                 THEN 'Assays recorded in DGER source.' END,
            'LithoSurfer sourceId: WA:' || c.canonical_id
         ), E'\\s*[\r\n]+\\s*', ' | ', 'g'),
         'claude_wa_20260910'
  FROM wa_dedup_canonical c JOIN wa_load_map m USING (canonical_id)
  RETURNING depositid, locationid
)
UPDATE wa_load_map m SET depositid = ins.depositid
FROM ins WHERE ins.locationid = m.locationid;

-- ============================================================ 6. deposit_commodities
INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, createdby)
SELECT m.depositid, x.commodity_id,
       CASE WHEN bool_or(t.role = 'PRIMARY') THEN 'PRIMARY' ELSE 'SECONDARY' END,
       'claude_wa_20260910'
FROM wa_canonical_commodity_tok t
JOIN wa_commodity_xwalk x USING (token)
JOIN wa_load_map m USING (canonical_id)
GROUP BY m.depositid, x.commodity_id;

-- ============================================================ 7. deposit_mineralogy
INSERT INTO deposit_mineralogy (depositid, mineral_id, mineral_name_local, role_raw, createdby)
SELECT m.depositid, mn.mineral_id, tok.name_l, 'DGER ore_minerals', 'claude_wa_20260910'
FROM (
    SELECT c.canonical_id, lower(btrim(t)) AS name_l
    FROM wa_dedup_canonical c, unnest(c.ore_mineral_tokens) t
    WHERE btrim(t) <> ''
    GROUP BY c.canonical_id, lower(btrim(t))
) tok
JOIN wa_load_map m USING (canonical_id)
LEFT JOIN LATERAL (
    SELECT mineral_id FROM minerals WHERE lower(mineral_name) = tok.name_l LIMIT 1
) mn ON true;

-- ============================================================ 8. verify
\echo '--- row counts (this load) ---'
SELECT
  (SELECT count(*) FROM locations          WHERE createdby='claude_wa_20260910') AS locations,
  (SELECT count(*) FROM deposits d JOIN locations l USING(locationid) WHERE l.createdby='claude_wa_20260910') AS deposits,
  (SELECT count(*) FROM deposit_commodities WHERE createdby='claude_wa_20260910') AS deposit_commodities,
  (SELECT count(*) FROM deposit_mineralogy  WHERE createdby='claude_wa_20260910') AS deposit_mineralogy;

\echo '--- integrity ---'
SELECT
  (SELECT count(*) FROM wa_load_map WHERE locationid IS NULL OR depositid IS NULL) AS unmapped_rows,
  (SELECT count(*) FROM locations WHERE createdby='claude_wa_20260910' AND geom IS NULL) AS null_geom,
  (SELECT count(*) FROM deposit_commodities WHERE createdby='claude_wa_20260910'
        AND depositid NOT IN (SELECT depositid FROM wa_load_map)) AS orphan_commodities;

\echo '--- commodity role split ---'
SELECT commodity_role, count(*) FROM deposit_commodities
WHERE createdby='claude_wa_20260910' GROUP BY 1;

\echo '--- deposits with zero commodity ---'
SELECT count(*) FROM wa_load_map m
WHERE NOT EXISTS (SELECT 1 FROM deposit_commodities dc WHERE dc.depositid = m.depositid);

\echo '--- mineralogy mineral_id resolution ---'
SELECT count(*) total, count(mineral_id) resolved
FROM deposit_mineralogy WHERE createdby='claude_wa_20260910';

COMMIT;

-- ================================================================= ROLLBACK
-- BEGIN;
-- DELETE FROM deposit_mineralogy  WHERE createdby='claude_wa_20260910';
-- DELETE FROM deposit_commodities WHERE createdby='claude_wa_20260910';
-- DELETE FROM deposits  WHERE createdby='claude_wa_20260910';
-- DELETE FROM locations WHERE createdby='claude_wa_20260910';
-- DROP TABLE IF EXISTS wa_load_map, wa_commodity_xwalk, wa_commodity_xwalk_raw;
-- DROP TABLE IF EXISTS deposits_bak_wa_20260910, deposit_commodities_bak_wa_20260910,
--                      deposit_mineralogy_bak_wa_20260910;
-- COMMIT;
