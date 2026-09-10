-- WA deposit extract — Step 2c: build wa_dedup_canonical, one row per cluster.
-- Reads cluster_assignment.csv (from 03_cluster.py). Non-destructive: only creates
-- wa_dedup_* tables. Nothing here touches locations / deposits / *_commodities / *_mineralogy.

BEGIN;

DROP TABLE IF EXISTS wa_cluster_assignment;
CREATE TABLE wa_cluster_assignment (staging_id int PRIMARY KEY, cluster_id int NOT NULL);
\copy wa_cluster_assignment FROM 'wa_deposit_extract/staging/cluster_assignment.csv' WITH (FORMAT csv, HEADER true)
CREATE INDEX ix_wa_ca_cluster ON wa_cluster_assignment (cluster_id);

-- source priority: which member's scalar fields win (1 = best)
CREATE OR REPLACE FUNCTION pg_temp.src_rank(s text) RETURNS int LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE s
    WHEN 'iaml' THEN 1 WHEN 'metallic' THEN 2 WHEN 'gold_silver' THEN 3
    WHEN 'nonmetallic' THEN 4 WHEN 'asbestos' THEN 5 WHEN 'coal_mine' THEN 6
    WHEN 'arsenic' THEN 7 WHEN 'mercury' THEN 8 WHEN 'radon' THEN 9 ELSE 99 END $$;
-- coordinate priority: full-precision sources first, rounded hazard re-cuts last
CREATE OR REPLACE FUNCTION pg_temp.coord_rank(s text) RETURNS int LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE s
    WHEN 'metallic' THEN 1 WHEN 'gold_silver' THEN 2 WHEN 'nonmetallic' THEN 3
    WHEN 'asbestos' THEN 4 WHEN 'coal_mine' THEN 5 WHEN 'iaml' THEN 6
    WHEN 'arsenic' THEN 7 WHEN 'mercury' THEN 8 WHEN 'radon' THEN 9 ELSE 99 END $$;

-- clean one DGER ore_minerals phrase: strip leading quantifiers, drop residual prose
CREATE OR REPLACE FUNCTION pg_temp.wa_min(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN x = '' THEN ''
    WHEN length(x) > 24 THEN ''
    WHEN x ~ '(was found|similar to| worth | per flake| property|in one hole| bank of| order of| sec\.?( |$)| r[0-9]+[ew]|contain|fracture|decreasing|dump|float\.?$|at depth| of the )' THEN ''
    ELSE x
  END
  FROM (
    SELECT btrim(regexp_replace(
             regexp_replace(
               btrim(regexp_replace(lower(coalesce(t,'')), E'[\r\n\t]+', ' ', 'g')),
               '^(some|minor|trace|traces|traces of|minor amounts? of|small amounts? of|lesser amounts? of|a small amount of|much|abundant|reportedly|reported|possibly|probably|free|flake|and|or|an?|two)\s+',
               '', 'g'),
             '[?,;]*\s*(reported|noted|present|observed)?\.?$', '', 'g')) x
  ) s
$$;

DROP TABLE IF EXISTS wa_dedup_canonical;
CREATE TABLE wa_dedup_canonical AS
WITH m AS (
    SELECT c.cluster_id, s.*,
           pg_temp.src_rank(s.wa_source)   sr,
           pg_temp.coord_rank(s.wa_source) cr
    FROM wa_deposits_staging s
    JOIN wa_cluster_assignment c USING (staging_id)
    WHERE NOT s.excluded
),
name_pick AS (
    SELECT DISTINCT ON (cluster_id) cluster_id, site_name, wa_source name_src
    FROM m ORDER BY cluster_id, sr, length(site_name) DESC NULLS LAST
),
coord_pick AS (
    SELECT DISTINCT ON (cluster_id) cluster_id, latitude, longitude, wa_source coord_src
    FROM m ORDER BY cluster_id, cr
),
dist_pick AS (
    SELECT DISTINCT ON (cluster_id) cluster_id, mining_district
    FROM m WHERE mining_district IS NOT NULL ORDER BY cluster_id, sr
),
county_pick AS (
    SELECT DISTINCT ON (cluster_id) cluster_id, county
    FROM m WHERE county IS NOT NULL ORDER BY cluster_id, sr
),
agg AS (
    SELECT cluster_id,
           count(*) n_members,
           array_agg(DISTINCT wa_source ORDER BY wa_source) sources,
           array_agg(wa_source || ':' || src_id ORDER BY sr) member_keys,
           -- all distinct names seen (for alternate_names / review)
           array_to_string(ARRAY(SELECT DISTINCT x FROM (
                SELECT unnest(array_agg(site_name)) x
                UNION SELECT unnest(string_to_array(string_agg(alternate_names, ', '), ', '))
           ) q WHERE x IS NOT NULL AND btrim(x) <> ''), ' | ') all_names,
           -- commodity tokens: primary_commodity + commodities, comma-split, deduped
           ARRAY(SELECT DISTINCT btrim(t) FROM (
                SELECT unnest(string_to_array(
                    string_agg(concat_ws(',', primary_commodity, commodities), ','), ',')) t
           ) q WHERE btrim(t) <> '') commodity_tokens,
           ARRAY(SELECT DISTINCT pg_temp.wa_min(t) FROM (
                SELECT unnest(string_to_array(string_agg(ore_minerals, ','), ',')) t
           ) q WHERE pg_temp.wa_min(t) <> '') ore_mineral_tokens,
           ARRAY(SELECT DISTINCT btrim(t) FROM (
                SELECT unnest(string_to_array(string_agg(mineral, ','), ',')) t
           ) q WHERE btrim(t) <> '') industrial_mineral_tokens,
           bool_or(wa_source = 'iaml') has_iaml,
           bool_or(production ILIKE 'yes' OR (wa_source='iaml' AND production IS NOT NULL)) any_production_flag,
           bool_or(assays ILIKE 'yes') any_assay_flag,
           string_agg(DISTINCT nullif(concat_ws(' ', '[' || wa_source || ']', location_description), '[' || wa_source || ']'), ' ') loc_desc_all,
           string_agg(DISTINCT nullif(concat_ws(' ', '[' || wa_source || ']', comments), '[' || wa_source || ']'), '  ') comments_all,
           string_agg(DISTINCT nullif(concat_ws(' ', '[' || wa_source || ']', value_text), '[' || wa_source || ']'), '  ') value_all,
           string_agg(DISTINCT references_text, ' ; ') references_all,
           min(latitude) lat_min, max(latitude) lat_max, min(longitude) lon_min, max(longitude) lon_max
    FROM m GROUP BY cluster_id
)
SELECT a.cluster_id AS canonical_id,
       np.site_name        AS name,
       np.name_src,
       cp.latitude, cp.longitude, cp.coord_src,
       round((ST_Distance(
           geography(ST_MakePoint(a.lon_min, a.lat_min)),
           geography(ST_MakePoint(a.lon_max, a.lat_max)))::numeric), 0) AS member_spread_m,
       dp.mining_district,
       ccp.county,
       a.n_members, a.sources, a.member_keys,
       a.all_names,
       a.commodity_tokens,
       a.ore_mineral_tokens,
       a.industrial_mineral_tokens,
       a.has_iaml, a.any_production_flag, a.any_assay_flag,
       a.loc_desc_all, a.comments_all, a.value_all, a.references_all
FROM agg a
JOIN name_pick   np  USING (cluster_id)
JOIN coord_pick  cp  USING (cluster_id)
LEFT JOIN dist_pick   dp  USING (cluster_id)
LEFT JOIN county_pick ccp USING (cluster_id);

ALTER TABLE wa_dedup_canonical ADD PRIMARY KEY (canonical_id);

COMMIT;

\echo '--- canonical totals ---'
SELECT count(*) AS canonical_deposits,
       count(*) FILTER (WHERE n_members > 1) AS merged_clusters,
       count(*) FILTER (WHERE array_length(commodity_tokens,1) IS NULL) AS no_commodity,
       count(*) FILTER (WHERE has_iaml) AS with_iaml_detail
FROM wa_dedup_canonical;

\echo '--- by dominant source ---'
SELECT sources, count(*) FROM wa_dedup_canonical GROUP BY 1 ORDER BY 2 DESC LIMIT 25;
