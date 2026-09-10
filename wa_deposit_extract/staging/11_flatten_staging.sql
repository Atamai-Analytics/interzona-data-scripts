-- WA deposit extract — Step 2f: strip stray control chars from the staging table.
-- A handful of DGER source values carry a trailing \r (e.g. "Manganese\r",
-- alternate_names "Cast Steel | Casteel\r"). Collapse [\r\n\t] runs to a space in
-- every free-text column so re-runs of 04_canonical.sql / 07_commodities.sql /
-- 09_load.sql stay clean. The loaded curated rows were already fixed
-- (10_flatten_comments.sql); this only tidies the internal staging layer.
-- Idempotent. 01_staging.sql's pg_temp.tn() now does this at ingest.

BEGIN;

UPDATE wa_deposits_staging SET
    site_name           = btrim(regexp_replace(site_name,           E'[\r\n\t]+', ' ', 'g')),
    alternate_names     = btrim(regexp_replace(alternate_names,     E'[\r\n\t]+', ' ', 'g')),
    primary_commodity   = btrim(regexp_replace(primary_commodity,   E'[\r\n\t]+', ' ', 'g')),
    commodities         = btrim(regexp_replace(commodities,         E'[\r\n\t]+', ' ', 'g')),
    ore_minerals        = btrim(regexp_replace(ore_minerals,        E'[\r\n\t]+', ' ', 'g')),
    gangue              = btrim(regexp_replace(gangue,              E'[\r\n\t]+', ' ', 'g')),
    mineral             = btrim(regexp_replace(mineral,             E'[\r\n\t]+', ' ', 'g')),
    category            = btrim(regexp_replace(category,            E'[\r\n\t]+', ' ', 'g')),
    location_description = btrim(regexp_replace(location_description, E'[\r\n\t]+', ' ', 'g')),
    county              = btrim(regexp_replace(county,              E'[\r\n\t]+', ' ', 'g')),
    mining_district     = btrim(regexp_replace(mining_district,     E'[\r\n\t]+', ' ', 'g')),
    assays              = btrim(regexp_replace(assays,              E'[\r\n\t]+', ' ', 'g')),
    production          = btrim(regexp_replace(production,          E'[\r\n\t]+', ' ', 'g')),
    value_text          = btrim(regexp_replace(value_text,          E'[\r\n\t]+', ' ', 'g')),
    comments            = btrim(regexp_replace(comments,            E'[\r\n\t]+', ' ', 'g')),
    references_text     = btrim(regexp_replace(references_text,     E'[\r\n\t]+', ' ', 'g'))
WHERE concat_ws('|', site_name, alternate_names, primary_commodity, commodities, ore_minerals,
                gangue, mineral, category, location_description, county, mining_district,
                assays, production, value_text, comments, references_text) ~ '[\r\n\t]';

COMMIT;

\echo '--- staging rows with control chars, all text cols (should be 0) ---'
SELECT count(*) FROM wa_deposits_staging
WHERE concat_ws('|', site_name, alternate_names, primary_commodity, commodities, ore_minerals,
                gangue, mineral, category, location_description, county, mining_district,
                assays, production, value_text, comments, references_text) ~ '[\x00-\x08\x0A-\x1F]';
