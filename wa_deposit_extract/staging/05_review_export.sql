-- WA deposit extract — Step 2d: export review CSVs.
\pset format csv
\pset tuples_only off

\o wa_deposit_extract/staging/canonical_all.csv
SELECT canonical_id, name, name_src, latitude, longitude, coord_src, member_spread_m,
       mining_district, county, n_members,
       array_to_string(sources,'+')            AS sources,
       array_to_string(member_keys,' ; ')      AS member_keys,
       all_names,
       array_to_string(commodity_tokens,', ')  AS commodities,
       array_to_string(ore_mineral_tokens,', ') AS ore_minerals,
       array_to_string(industrial_mineral_tokens,', ') AS industrial_minerals,
       has_iaml, any_production_flag, any_assay_flag
FROM wa_dedup_canonical ORDER BY canonical_id;
\o

\o wa_deposit_extract/staging/canonical_merged_only.csv
SELECT canonical_id, name, latitude, longitude, coord_src, member_spread_m, county,
       n_members, array_to_string(sources,'+') AS sources,
       array_to_string(member_keys,' ; ') AS member_keys, all_names,
       array_to_string(commodity_tokens,', ') AS commodities
FROM wa_dedup_canonical WHERE n_members > 1 ORDER BY member_spread_m DESC, canonical_id;
\o

\pset format aligned
\echo '=== merged clusters: 25 widest (verify these are one deposit) ==='
SELECT canonical_id, member_spread_m sp, array_to_string(sources,'+') src, left(all_names,70) names
FROM wa_dedup_canonical WHERE n_members>1 ORDER BY member_spread_m DESC LIMIT 25;

\echo
\echo '=== merged clusters: 20 random typical (2 members) ==='
SELECT canonical_id, array_to_string(sources,'+') src, left(all_names,60) names,
       left(array_to_string(commodity_tokens,', '),45) comm
FROM wa_dedup_canonical WHERE n_members=2 ORDER BY md5(canonical_id::text) LIMIT 20;

\echo
\echo '=== 3-4 member clusters ==='
SELECT canonical_id, n_members, array_to_string(sources,'+') src, left(all_names,55) names
FROM wa_dedup_canonical WHERE n_members>=3 ORDER BY n_members DESC, canonical_id LIMIT 40;

\echo
\echo '=== distinct commodity tokens across all canonical (for step-4 crosswalk) ==='
SELECT t AS commodity_token, count(*) n
FROM wa_dedup_canonical, unnest(commodity_tokens) t
GROUP BY 1 ORDER BY 2 DESC;

\echo
\echo '=== canonical with NO commodity token ==='
SELECT canonical_id, name, array_to_string(sources,'+') src, county FROM wa_dedup_canonical
WHERE array_length(commodity_tokens,1) IS NULL ORDER BY src;
