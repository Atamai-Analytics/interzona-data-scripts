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
FROM wa_deposits_staging WHERE NOT excluded ORDER BY staging_id;
\o

-- accepted name-variant merges from the 2026-09-10 review (X <-> "X Mine" / OCR typo)
DROP TABLE IF EXISTS pg_temp.accepted_merges;
CREATE TEMP TABLE accepted_merges (a int, b int);
INSERT INTO accepted_merges (a, b) VALUES
    (1456, 4480),                       -- Deer Trail Monitor / ... mine
    (1496, 4239), (1496, 5642),         -- McMyrl-Wilson / McMyri-Wilson (OCR)
    (1721, 5965),                       -- Metaline Mining & Leasing Co. / ... and Leasing
    (1815, 5019),                       -- Flagstaff Mountain / ... Mine
    (2924, 2925),                       -- Sultan River Placer / Placers
    (3221, 4474),                       -- Frisco Standard / ... mine
    (3242, 4465),                       -- Old Dominion / ... mine
    (3655, 3682),                       -- Northwest Haydite Co, Inc / Northwest Haydite
    (3683, 5711), (3753, 5711),         -- Cedar Mountain / Cedar Mountain Mine
    (3671, 5871);                       -- Johnson Coal Co. / ... Mine

\o wa_deposit_extract/staging/edges.csv
SELECT 'a,b,dist_m';
WITH g AS (
    SELECT staging_id, name_norm,
           geography(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) gg
    FROM wa_deposits_staging WHERE name_norm <> '' AND NOT excluded
),
e1 AS (
    SELECT a.staging_id a, b.staging_id b, ST_Distance(a.gg, b.gg) d
    FROM g a
    JOIN g b ON a.name_norm = b.name_norm AND a.staging_id < b.staging_id
    WHERE ST_Distance(a.gg, b.gg) <= 500
),
acc AS (
    SELECT least(m.a, m.b) a, greatest(m.a, m.b) b,
           ST_Distance(ga.gg, gb.gg) d
    FROM accepted_merges m
    JOIN g ga ON ga.staging_id = m.a
    JOIN g gb ON gb.staging_id = m.b
)
SELECT a || ',' || b || ',' || round(d::numeric, 1)
FROM (SELECT * FROM e1 UNION SELECT * FROM acc) u;
\o

\o wa_deposit_extract/staging/review_pairs.csv
SELECT 'rule,a,b,name_a,name_b,src_a,src_b,county_a,county_b,dist_m,name_sim';
WITH g AS (
    SELECT staging_id, wa_source, site_name, name_norm, county,
           geography(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) gg
    FROM wa_deposits_staging WHERE name_norm <> '' AND NOT excluded
),
freq AS (
    SELECT name_norm, count(*) n FROM wa_deposits_staging WHERE name_norm <> '' AND NOT excluded GROUP BY 1
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
