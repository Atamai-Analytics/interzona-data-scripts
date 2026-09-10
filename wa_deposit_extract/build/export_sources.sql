-- WA deposit extract — Step 5a: export the loaded WA deposits for the LithoSurfer build.
-- Reads the curated tables (locations/deposits/deposit_commodities/deposit_mineralogy)
-- filtered to createdby='claude_wa_20260910', plus wa_dedup_canonical for the raw context.
-- Outputs build/wa_*.csv. Run with cwd = repo root, or edit the \o paths.

\pset format csv
\pset tuples_only off

-- 1. base: one row per WA deposit
\o wa_deposit_extract/build/wa_base.csv
WITH acc AS (   -- coarse location precision (metres) from the members' free-text accuracy
    SELECT c.canonical_id,
           min(CASE
                 WHEN a ~ 'gps'                              THEN 30
                 WHEN a ~ 'orthophoto|quarter section|qtr'   THEN 400
                 WHEN a ~ '7\.5-minute|topographic'          THEN 250
                 WHEN a ~ '(^|[^e]) section|^section'        THEN 800
                 WHEN a ~ 'multiple sections|^township'      THEN 2500
                 WHEN a ~ 'multiple townships|district centroid' THEN 10000
                 WHEN a ~ 'estimated from'                   THEN 2000
                 ELSE 2000
               END)::int AS prec_m
    FROM wa_dedup_canonical c
    JOIN wa_cluster_assignment ca ON ca.cluster_id = c.canonical_id
    JOIN wa_deposits_staging s ON s.staging_id = ca.staging_id AND NOT s.excluded
    CROSS JOIN LATERAL (SELECT lower(coalesce(s.raw->>'location_accuracy',
                                              s.raw->>'location_confidence', '')) AS a) x
    GROUP BY c.canonical_id
)
SELECT c.canonical_id,
       l.locationname                              AS name,
       l.latitude, l.longitude,
       coalesce(acc.prec_m, 2000)                  AS lat_lon_precision_m,
       c.mining_district, c.county,
       array_to_string(c.sources, '+')             AS sources,
       array_to_string(c.member_keys, ' ; ')       AS member_keys,
       c.all_names,
       c.n_members, c.member_spread_m,
       c.has_iaml, c.any_production_flag, c.any_assay_flag,
       d.comments                                  AS deposit_comments,
       d."references"                              AS deposit_references,
       l.comments                                  AS location_comments,
       c.value_all
FROM wa_dedup_canonical c
JOIN locations l ON l.external_id = 'WA:' || c.canonical_id AND l.createdby = 'claude_wa_20260910'
JOIN deposits  d ON d.locationid = l.locationid
LEFT JOIN acc USING (canonical_id)
ORDER BY c.canonical_id;
\o

-- 2. commodities: deposit -> commodity_id -> LCommodity name (join done in build script)
\o wa_deposit_extract/build/wa_commodities.csv
SELECT c.canonical_id, dc.commodity_id, cm.commodity_name, dc.commodity_role
FROM wa_dedup_canonical c
JOIN locations l ON l.external_id = 'WA:' || c.canonical_id AND l.createdby = 'claude_wa_20260910'
JOIN deposits  d ON d.locationid = l.locationid
JOIN deposit_commodities dc ON dc.depositid = d.depositid AND dc.createdby = 'claude_wa_20260910'
JOIN commodities cm ON cm.commodity_id = dc.commodity_id
ORDER BY c.canonical_id, (dc.commodity_role = 'PRIMARY') DESC, cm.commodity_name;
\o

-- 3. mineralogy: for the description sidecar (no LithoSurfer deposit entity)
\o wa_deposit_extract/build/wa_mineralogy.csv
SELECT c.canonical_id, string_agg(dm.mineral_name_local, ', ' ORDER BY dm.mineral_name_local) AS minerals
FROM wa_dedup_canonical c
JOIN locations l ON l.external_id = 'WA:' || c.canonical_id AND l.createdby = 'claude_wa_20260910'
JOIN deposits  d ON d.locationid = l.locationid
JOIN deposit_mineralogy dm ON dm.depositid = d.depositid AND dm.createdby = 'claude_wa_20260910'
GROUP BY c.canonical_id;
\o

\pset format aligned
\echo 'wa_base.csv / wa_commodities.csv / wa_mineralogy.csv written'
