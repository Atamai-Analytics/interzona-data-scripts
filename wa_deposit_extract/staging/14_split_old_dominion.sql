-- WA deposit extract — Step 2h: split canonical 3231 "Old Dominion".
--
-- Spot-check found the accepted name-variant merge (staging 3242 "Old Dominion" /
-- 4465 "Old Dominion mine") joined a Ag-Pb-Zn mine with a dolomite quarry point
-- 830 m away — two different features. Split staging 4465 into its own deposit.
--
--   cluster 3231  keeps {3242 gold_silver, 5990 iaml}  -> "Old Dominion" (Ag-Pb-Zn)
--   cluster 5418  (new)  = {4465 nonmetallic}          -> "Old Dominion mine" (dolomite)
--
-- Canonical ids are the frozen load key (locations.external_id = 'WA:<id>'), so this
-- patches wa_cluster_assignment directly (NOT via 03_cluster.py, which renumbers) and
-- keeps every other id unchanged. 02_edges.sql has had the (3242,4465) merge removed.

\set ON_ERROR_STOP on

-- 1. reassign the dolomite member to a fresh cluster id
UPDATE wa_cluster_assignment SET cluster_id = 5418 WHERE staging_id = 4465 AND cluster_id = 3231;

-- refresh the on-disk assignment CSV (frozen source of truth post-load)
\copy (SELECT staging_id, cluster_id FROM wa_cluster_assignment ORDER BY staging_id) TO 'wa_deposit_extract/staging/cluster_assignment.csv' WITH (FORMAT csv, HEADER true)

-- 2. rebuild canonical + commodity tokens (both read cluster_id as-is; no renumber)
\i wa_deposit_extract/staging/04_canonical.sql
\i wa_deposit_extract/staging/07_commodities.sql

-- 3. rebuild the commodity crosswalk table from the (unchanged) CSV
BEGIN;
DROP TABLE IF EXISTS wa_commodity_xwalk_raw;
CREATE TABLE wa_commodity_xwalk_raw (token text, n_deposits int, n_primary int,
    commodity_id text, commodity_name text, method text);
\copy wa_commodity_xwalk_raw FROM 'C:/Users/dean/claude_lithosurfer/lithosurfer-work/wa_deposit_extract/staging/crosswalk_commodity_wa.csv' WITH (FORMAT csv, HEADER true)
DROP TABLE IF EXISTS wa_commodity_xwalk;
CREATE TABLE wa_commodity_xwalk AS
SELECT DISTINCT token, commodity_id::int AS commodity_id FROM wa_commodity_xwalk_raw
WHERE method <> 'DROP' AND btrim(coalesce(commodity_id,'')) <> '';
ALTER TABLE wa_commodity_xwalk ADD PRIMARY KEY (token, commodity_id);
COMMIT;

-- 4. patch the loaded rows for canonical 3231 (metal mine) and insert 5418 (dolomite)
BEGIN;

-- 4a. new location + deposit for canonical 5418
WITH ins_l AS (
  INSERT INTO locations
      (locationcode, locationname, locationtype, latitude, longitude,
       countryid, divisionid, datasource, datasource_url, external_id, comments, createdby)
  SELECT 'WA', left(coalesce(c.name,'Unnamed DGER site '||c.canonical_id),255),
         'DEPOSIT', c.latitude, c.longitude, 246, 48,
         'Washington State Geological Survey (DGER)', 'https://www.dnr.wa.gov/geologyportal',
         'WA:'||c.canonical_id,
         regexp_replace(concat_ws(' | ',
            'DGER sources: '||array_to_string(c.sources,', ')||' ('||array_to_string(c.member_keys,' ; ')||')',
            CASE WHEN c.mining_district IS NOT NULL THEN 'Mining district: '||c.mining_district END,
            CASE WHEN c.county IS NOT NULL THEN 'County: '||c.county END,
            CASE WHEN nullif(btrim(c.all_names),'') IS NOT NULL AND lower(c.all_names)<>lower(coalesce(c.name,''))
                 THEN 'Names / aliases: '||c.all_names END,
            CASE WHEN nullif(btrim(c.loc_desc_all),'') IS NOT NULL THEN 'Location notes: '||c.loc_desc_all END,
            CASE WHEN c.member_spread_m > 100 THEN 'Merged from DGER records up to '||c.member_spread_m||' m apart' END
         ), E'[ \t]*[\r\n\t·]+[ \t·]*', ' | ', 'g'),
         'claude_wa_20260910'
  FROM wa_dedup_canonical c WHERE c.canonical_id = 5418
  RETURNING locationid, external_id
), ins_d AS (
  INSERT INTO deposits (locationid, deposit_type_id, geological_district,
       production_data, "references", comments, createdby)
  SELECT il.locationid, NULL, c.mining_district,
         CASE WHEN c.any_production_flag THEN 'Production recorded (DGER occurrence-inventory flag; source carries no grade or tonnage).' END,
         nullif(btrim(c.references_all),''),
         regexp_replace(concat_ws(' | ',
            nullif(btrim(c.comments_all),''),
            CASE WHEN nullif(btrim(c.value_all),'') IS NOT NULL THEN 'Value / significance: '||c.value_all END,
            CASE WHEN array_length(c.ore_mineral_tokens,1) IS NOT NULL THEN 'Ore minerals (DGER): '||array_to_string(c.ore_mineral_tokens,', ') END,
            CASE WHEN c.any_assay_flag THEN 'Assays recorded in DGER source.' END,
            'LithoSurfer sourceId: WA:'||c.canonical_id
         ), E'[ \t]*[\r\n\t·]+[ \t·]*', ' | ', 'g'),
         'claude_wa_20260910'
  FROM ins_l il JOIN wa_dedup_canonical c ON 'WA:'||c.canonical_id = il.external_id
  RETURNING depositid, locationid
)
-- NB: a plain data-modifying CTE can't see rows a sibling CTE just inserted via a
-- re-join to the base table — carry the key through, or (here) use the constant id.
INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, createdby)
SELECT d.depositid, x.commodity_id,
       CASE WHEN bool_or(t.role='PRIMARY') THEN 'PRIMARY' ELSE 'SECONDARY' END, 'claude_wa_20260910'
FROM ins_d d
JOIN wa_canonical_commodity_tok t ON t.canonical_id = 5418
JOIN wa_commodity_xwalk x USING (token)
GROUP BY d.depositid, x.commodity_id;

-- 4b. refresh canonical 3231 (loses the dolomite member)
UPDATE locations l
SET comments = regexp_replace(concat_ws(' | ',
        'DGER sources: '||array_to_string(c.sources,', ')||' ('||array_to_string(c.member_keys,' ; ')||')',
        CASE WHEN c.mining_district IS NOT NULL THEN 'Mining district: '||c.mining_district END,
        CASE WHEN c.county IS NOT NULL THEN 'County: '||c.county END,
        CASE WHEN nullif(btrim(c.all_names),'') IS NOT NULL AND lower(c.all_names)<>lower(coalesce(c.name,''))
             THEN 'Names / aliases: '||c.all_names END,
        CASE WHEN nullif(btrim(c.loc_desc_all),'') IS NOT NULL THEN 'Location notes: '||c.loc_desc_all END,
        CASE WHEN c.member_spread_m > 100 THEN 'Merged from DGER records up to '||c.member_spread_m||' m apart' END
     ), E'[ \t]*[\r\n\t·]+[ \t·]*', ' | ', 'g')
FROM wa_dedup_canonical c
WHERE l.external_id = 'WA:3231' AND l.createdby='claude_wa_20260910' AND c.canonical_id = 3231;

UPDATE deposits d
SET comments = regexp_replace(concat_ws(' | ',
        nullif(btrim(c.comments_all),''),
        CASE WHEN nullif(btrim(c.value_all),'') IS NOT NULL THEN 'Value / significance: '||c.value_all END,
        CASE WHEN array_length(c.ore_mineral_tokens,1) IS NOT NULL THEN 'Ore minerals (DGER): '||array_to_string(c.ore_mineral_tokens,', ') END,
        CASE WHEN c.any_assay_flag THEN 'Assays recorded in DGER source.' END,
        'LithoSurfer sourceId: WA:'||c.canonical_id
     ), E'[ \t]*[\r\n\t·]+[ \t·]*', ' | ', 'g')
FROM wa_dedup_canonical c
JOIN locations l ON l.external_id = 'WA:3231' AND l.createdby='claude_wa_20260910'
WHERE d.locationid = l.locationid AND c.canonical_id = 3231;

-- re-sync commodities for 3231 (drops Limestone)
DELETE FROM deposit_commodities dc
USING deposits d JOIN locations l ON l.locationid=d.locationid
WHERE dc.depositid=d.depositid AND dc.createdby='claude_wa_20260910' AND l.external_id='WA:3231';

INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, createdby)
SELECT d.depositid, x.commodity_id,
       CASE WHEN bool_or(t.role='PRIMARY') THEN 'PRIMARY' ELSE 'SECONDARY' END, 'claude_wa_20260910'
FROM wa_canonical_commodity_tok t
JOIN wa_commodity_xwalk x USING (token)
JOIN locations l ON l.external_id = 'WA:'||t.canonical_id AND l.createdby='claude_wa_20260910' AND l.external_id='WA:3231'
JOIN deposits d ON d.locationid = l.locationid
GROUP BY d.depositid, x.commodity_id;

COMMIT;

\echo '--- Old Dominion after split ---'
SELECT l.external_id, l.locationname, l.latitude::numeric(9,5) lat, l.longitude::numeric(9,5) lon,
       string_agg(cm.commodity_name||':'||dc.commodity_role, ', ' ORDER BY dc.commodity_role, cm.commodity_name) commodities
FROM locations l JOIN deposits d USING(locationid)
LEFT JOIN deposit_commodities dc ON dc.depositid=d.depositid AND dc.createdby='claude_wa_20260910'
LEFT JOIN commodities cm USING(commodity_id)
WHERE l.external_id IN ('WA:3231','WA:5418') GROUP BY 1,2,3,4 ORDER BY 1;

\echo '--- totals ---'
SELECT (SELECT count(*) FROM locations WHERE createdby='claude_wa_20260910') locations,
       (SELECT count(*) FROM wa_dedup_canonical) canonical;
