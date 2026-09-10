-- WA deposit extract — Step 2a: emit dedup edge list, node list, and review pairs.
--
-- AUTO-MERGE edge (edges.csv)  <=>  same physical deposit, high precision:
--   E1  exact name_norm (non-empty)  AND  great-circle distance <= 500 m
--
-- Coordinate proximity ALONE never merges: ~240 distinct-name pairs sit within 30 m
-- because DGER digitised many sites to a section / township centroid.
-- Exact name at > 500 m is mostly generic names reused across districts
-- ("Last Chance" x205 pairs, "Eureka" x91) OR shared geographic names
-- (creek / lake / valley) on distinct occurrences — those go to review, not merge.
--
-- REVIEW pairs (review_pairs.csv) — surfaced, never auto-applied:
--   R_NAME_FAR  exact name_norm, same county, name not generic (< 3 statewide), 500–3000 m
--   R_TRGM      trigram similarity >= 0.72, same county, <= 1000 m, different name_norm
--   R_SAMEPT    different name_norm, <= 30 m apart, some name relation (sim > 0) OR hazard re-cut

\pset format unaligned
\pset tuples_only on
\pset fieldsep ','

\o wa_deposit_extract/staging/nodes.csv
SELECT 'staging_id,wa_source,src_id,site_name,name_norm,county,latitude,longitude';
SELECT staging_id || ',' || wa_source || ',' || src_id || ',' ||
       '"' || replace(coalesce(site_name,''), '"', '""') || '",' ||
       '"' || replace(name_norm, '"', '""') || '",' ||
       '"' || replace(coalesce(county,''), '"', '""') || '",' ||
       latitude || ',' || longitude
FROM wa_deposits_staging ORDER BY staging_id;
\o

\o wa_deposit_extract/staging/edges.csv
SELECT 'a,b,dist_m';
WITH g AS (
    SELECT staging_id, name_norm,
           geography(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) gg
    FROM wa_deposits_staging WHERE name_norm <> ''
)
SELECT a.staging_id || ',' || b.staging_id || ',' || round(ST_Distance(a.gg, b.gg)::numeric, 1)
FROM g a
JOIN g b ON a.name_norm = b.name_norm AND a.staging_id < b.staging_id
WHERE ST_Distance(a.gg, b.gg) <= 500;
\o

\o wa_deposit_extract/staging/review_pairs.csv
SELECT 'rule,a,b,name_a,name_b,src_a,src_b,county_a,county_b,dist_m,name_sim';
WITH g AS (
    SELECT staging_id, wa_source, site_name, name_norm, county,
           geography(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) gg
    FROM wa_deposits_staging WHERE name_norm <> ''
),
freq AS (
    SELECT name_norm, count(*) n FROM wa_deposits_staging WHERE name_norm <> '' GROUP BY 1
),
cand AS (
    SELECT a.staging_id a, b.staging_id b, a.site_name na, b.site_name nb,
           a.wa_source sa, b.wa_source sb, a.county ca, b.county cb,
           ST_Distance(a.gg, b.gg) d,
           similarity(a.name_norm, b.name_norm) sim,
           (a.name_norm = b.name_norm) exact_name,
           (a.county IS NOT DISTINCT FROM b.county) same_cty,
           f.n freq
    FROM g a
    JOIN g b ON a.staging_id < b.staging_id
    JOIN freq f ON f.name_norm = a.name_norm
    WHERE ST_DWithin(a.gg, b.gg, 3000)
      AND (
            (a.name_norm = b.name_norm)
         OR (similarity(a.name_norm, b.name_norm) >= 0.72)
          )
)
SELECT
    CASE
        WHEN exact_name AND d > 500 THEN 'R_NAME_FAR'
        WHEN NOT exact_name AND d <= 1000 THEN 'R_TRGM'
        WHEN NOT exact_name AND d <= 30 THEN 'R_SAMEPT'
    END || ',' ||
    a || ',' || b || ',' ||
    '"' || replace(na, '"', '""') || '","' || replace(nb, '"', '""') || '",' ||
    sa || ',' || sb || ',' ||
    '"' || replace(coalesce(ca,''), '"', '""') || '","' || replace(coalesce(cb,''), '"', '""') || '",' ||
    round(d::numeric, 1) || ',' || round(sim::numeric, 2)
FROM cand
WHERE (exact_name AND d > 500 AND same_cty AND freq < 3)
   OR (NOT exact_name AND d <= 1000 AND same_cty)
   OR (NOT exact_name AND d <= 30 AND (sim > 0 OR sa IN ('arsenic','mercury','radon') OR sb IN ('arsenic','mercury','radon')))
ORDER BY 1, d;
\o

\pset format aligned
\pset tuples_only off
\echo 'nodes.csv, edges.csv, review_pairs.csv written'
