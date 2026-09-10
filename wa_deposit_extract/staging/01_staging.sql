-- WA (Washington State Geological Survey / DGER) deposit extract — Step 1
-- Build wa_deposits_staging: a pure, non-destructive UNION of the 9 deposit-relevant
-- WA_* source tables. No dedup decisions here — every source row survives, keyed by
-- (wa_source, src_id). Full source row preserved in raw jsonb.
--
-- Sibling of the SIGAM/Argentina work; kept fully separate (own table, own tag).
-- Nothing here touches locations / deposits / deposit_commodities / deposit_mineralogy.

BEGIN;

DROP TABLE IF EXISTS wa_deposits_staging;

CREATE TABLE wa_deposits_staging (
    staging_id           serial PRIMARY KEY,
    wa_source            text NOT NULL,   -- metallic|gold_silver|nonmetallic|arsenic|mercury|radon|asbestos|coal_mine|iaml
    src_id               text NOT NULL,   -- site_id / mine_id / iaml_id as text
    site_name            text,
    alternate_names      text,
    primary_commodity    text,            -- source's own primary-commodity string ("Copper (Cu)", "antimony", "Coal", ...)
    commodities          text,            -- comma-list of commodities
    ore_minerals         text,
    gangue               text,
    mineral              text,            -- nonmetallic/asbestos single industrial-mineral name
    category             text,            -- nonmetallic category / asbestos n/a / iaml hazard label
    location_description  text,
    county               text,
    mining_district      text,
    latitude             double precision NOT NULL,
    longitude            double precision NOT NULL,
    assays               text,            -- metallic/gold_silver: yes/no flag only
    production           text,            -- metallic/gold_silver: yes/no flag only; iaml: narrative
    value_text           text,            -- nonmetallic/asbestos "value" narrative
    comments             text,
    references_text      text,
    raw                  jsonb NOT NULL,  -- complete source row
    createdby            text NOT NULL DEFAULT 'claude_wa_20260910',
    createddate          timestamp NOT NULL DEFAULT now(),
    UNIQUE (wa_source, src_id)
);

-- helper: trim to NULL
CREATE OR REPLACE FUNCTION pg_temp.tn(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT nullif(btrim($1), '') $$;

-- 1. metallic ---------------------------------------------------------------
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, alternate_names, primary_commodity, commodities,
     ore_minerals, gangue, location_description, county, mining_district,
     latitude, longitude, assays, production, comments, raw)
SELECT 'metallic', site_id::text, pg_temp.tn(site_name), pg_temp.tn(alternate_names),
       pg_temp.tn(primary_commodity), pg_temp.tn(commodities), pg_temp.tn(ore_minerals),
       pg_temp.tn(gangue), pg_temp.tn(location_description), pg_temp.tn(county),
       pg_temp.tn(mining_district), latitude, longitude, pg_temp.tn(assays),
       pg_temp.tn(production), pg_temp.tn(comments), to_jsonb(m)
FROM "WA_metallic_mineral_locations" m;

-- 2. gold_silver ----------------------------------------------------------------
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, alternate_names, primary_commodity, commodities,
     ore_minerals, gangue, location_description, county, mining_district,
     latitude, longitude, assays, production, comments, raw)
SELECT 'gold_silver', site_id::text, pg_temp.tn(site_name), pg_temp.tn(alternate_names),
       pg_temp.tn(primary_commodity), pg_temp.tn(commodities), pg_temp.tn(ore_minerals),
       pg_temp.tn(gangue), pg_temp.tn(location_description), pg_temp.tn(county),
       pg_temp.tn(mining_district), latitude, longitude, pg_temp.tn(assays),
       pg_temp.tn(production), pg_temp.tn(comments), to_jsonb(g)
FROM "WA_gold_silver_locations" g;

-- 3. nonmetallic --------------------------------------------------------------
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, primary_commodity, mineral, category,
     location_description, county, latitude, longitude, value_text, comments,
     references_text, raw)
SELECT 'nonmetallic', site_id::text, pg_temp.tn(site_name), pg_temp.tn(mineral),
       pg_temp.tn(mineral), pg_temp.tn(category), pg_temp.tn(location_description),
       pg_temp.tn(county), latitude, longitude, pg_temp.tn(value),
       pg_temp.tn(site_description), pg_temp.tn(n."references"), to_jsonb(n)
FROM "WA_nonmetallic_mineral_locations" n;

-- 4. arsenic / 5. mercury / 6. radon (re-cuts of metallic by hazardous commodity)
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, primary_commodity, commodities,
     location_description, county, latitude, longitude, assays, production, comments, raw)
SELECT 'arsenic', site_id::text, pg_temp.tn(site_name), pg_temp.tn(commodity),
       pg_temp.tn(commodity), pg_temp.tn(location), pg_temp.tn(county),
       latitude, longitude, pg_temp.tn(assays), pg_temp.tn(production),
       pg_temp.tn(comment), to_jsonb(a)
FROM "WA_arsenic_locations" a;

INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, primary_commodity, commodities,
     location_description, county, latitude, longitude, assays, production, comments, raw)
SELECT 'mercury', site_id::text, pg_temp.tn(site_name), pg_temp.tn(commodity),
       pg_temp.tn(commodity), pg_temp.tn(location), pg_temp.tn(county),
       latitude, longitude, pg_temp.tn(assays), pg_temp.tn(production),
       pg_temp.tn(comment), to_jsonb(mm)
FROM "WA_mercury_locations" mm;

INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, primary_commodity, commodities,
     location_description, county, latitude, longitude, assays, production, comments, raw)
SELECT 'radon', site_id::text, pg_temp.tn(site_name), pg_temp.tn(commodity),
       pg_temp.tn(commodity), pg_temp.tn(location), pg_temp.tn(county),
       latitude, longitude, pg_temp.tn(assays), pg_temp.tn(production),
       pg_temp.tn(comment), to_jsonb(r)
FROM "WA_radon_locations" r;

-- 7. asbestos --------------------------------------------------------------------
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, primary_commodity, mineral,
     location_description, county, latitude, longitude, value_text, comments,
     references_text, raw)
SELECT 'asbestos', site_id::text, pg_temp.tn(site_name), pg_temp.tn(mineral),
       pg_temp.tn(mineral), pg_temp.tn(location), pg_temp.tn(county),
       latitude, longitude, pg_temp.tn(value), pg_temp.tn(description),
       pg_temp.tn(x."references"), to_jsonb(x)
FROM "WA_asbestos_locations" x;

-- 8. coal_mine (names/operators from WA_coal_mine_map_inventory, join on mine_id) --
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, primary_commodity, county,
     latitude, longitude, comments, raw)
SELECT 'coal_mine', l.mine_id,
       pg_temp.tn(inv.mine_name),
       'Coal',
       pg_temp.tn(inv.county),
       l.latitude84, l.longitude84,
       pg_temp.tn(concat_ws(' | ',
           pg_temp.tn(l.comments),
           CASE WHEN pg_temp.tn(inv.mine_operator) IS NOT NULL
                THEN 'Operator: ' || inv.mine_operator END,
           CASE WHEN pg_temp.tn(l.location_accuracy) IS NOT NULL
                THEN 'Location accuracy: ' || l.location_accuracy END)),
       to_jsonb(l) || jsonb_build_object(
           'inv_mine_name', inv.mine_name, 'inv_mine_name_2', inv.mine_name_2,
           'inv_mine_name_3', inv.mine_name_3, 'inv_mine_operator', inv.mine_operator,
           'inv_county', inv.county)
FROM "WA_coal_mine_locations" l
LEFT JOIN LATERAL (
    SELECT mine_name, mine_name_2, mine_name_3, mine_operator, county
    FROM "WA_coal_mine_map_inventory" i
    WHERE i.mine_id = l.mine_id
    ORDER BY (i.mine_name IS NULL), i.map_year NULLS LAST
    LIMIT 1
) inv ON true;

-- 9. iaml (Inventory of Abandoned Mine Lands — richest) --------------------------
INSERT INTO wa_deposits_staging
    (wa_source, src_id, site_name, category, ore_minerals, mining_district, county,
     latitude, longitude, production, comments, raw)
SELECT 'iaml', iaml_id, pg_temp.tn(site_name),
       pg_temp.tn(hazard),                       -- iaml "hazard" flag (yes/no/unknown)
       pg_temp.tn(material),                     -- physical material on site (debris/ore)
       pg_temp.tn(mining_district), pg_temp.tn(county),
       site_dd_lat, site_dd_long,
       pg_temp.tn(production),
       pg_temp.tn(concat_ws(' | ',
           CASE WHEN pg_temp.tn(years_of_operation) IS NOT NULL
                THEN 'Years of operation: ' || years_of_operation END,
           CASE WHEN pg_temp.tn(ownership) IS NOT NULL
                THEN 'Ownership: ' || ownership END,
           CASE WHEN pg_temp.tn(surface_mine) IS NOT NULL
                THEN 'Surface mine: ' || surface_mine END,
           CASE WHEN pg_temp.tn(underground_mine) IS NOT NULL
                THEN 'Underground mine: ' || underground_mine END,
           CASE WHEN pg_temp.tn(mill) IS NOT NULL
                THEN 'Mill: ' || mill END,
           CASE WHEN pg_temp.tn(site_comments) IS NOT NULL
                THEN site_comments END)),
       to_jsonb(s)
FROM "WA_iaml_sites" s;

-- normalized name for dedup (English names; no unaccent needed) -----------------
ALTER TABLE wa_deposits_staging
    ADD COLUMN name_norm text
    GENERATED ALWAYS AS (
        btrim(regexp_replace(lower(coalesce(site_name, '')), '[^a-z0-9]+', ' ', 'g'))
    ) STORED;

CREATE INDEX ix_wa_stg_name_norm  ON wa_deposits_staging (name_norm);
CREATE INDEX ix_wa_stg_name_trgm  ON wa_deposits_staging USING gin (name_norm gin_trgm_ops);
CREATE INDEX ix_wa_stg_geom       ON wa_deposits_staging
    USING gist (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326));
CREATE INDEX ix_wa_stg_source     ON wa_deposits_staging (wa_source);

COMMIT;

-- summary
\echo '--- rows per source ---'
SELECT wa_source, count(*) AS rows,
       count(*) FILTER (WHERE site_name IS NULL)         AS no_name,
       count(*) FILTER (WHERE primary_commodity IS NULL) AS no_commodity
FROM wa_deposits_staging GROUP BY wa_source ORDER BY wa_source;
\echo '--- total ---'
SELECT count(*) AS total_staged FROM wa_deposits_staging;
