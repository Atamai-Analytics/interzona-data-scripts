-- PHASE 3: Greenland occurrences, from the 28 real bronze deposits.
-- Requires Phase 0 committed first (not Phase 1/2 -- independent of those).

BEGIN;

CREATE TABLE geochem._map_occurrence_type AS
SELECT b.deposit_type_id AS bronze_id, g.occurrence_type_id AS gold_id
FROM bronze.deposit_types b
JOIN core.occurrence_types g ON g.type_name = b.deposit_type_name;

ALTER TABLE core.occurrences ADD COLUMN _bronze_depositid integer;

INSERT INTO core.occurrences (
  name, is_deposit, occurrence_type_id, jurisdiction_id, geom, elevation_m,
  geological_province, geological_subprovince, geological_district,
  tectonic_setting, regional_structure, metallogenic_association,
  deposit_form, mineralization_style, associated_igneous, alteration,
  status, size_category, workings_type, comments,
  is_active, created_by, created_date, _bronze_depositid
)
SELECT
  l.locationname,
  d.deposit_status IN ('PAST_PRODUCER','PRODUCER','FEASIBILITY','DEVELOPMENT','CLOSED'),
  mt.gold_id,
  841,  -- Greenland, core.jurisdictions (already seeded as a country row)
  ST_SetSRID(ST_MakePoint(l.longitude, l.latitude), 4326),
  l.elevation,
  d.geological_province, d.geological_subprovince, d.geological_district,
  d.tectonic_setting, d.regional_structure, d.metallogenic_association,
  d.deposit_form, d.mineralization_style, d.associated_igneous, d.alteration,
  d.deposit_status, d.size_category, d.workings_type, d.comments,
  true, 'migration_greenland_20260930', now(), d.depositid
FROM bronze.deposits d
JOIN bronze.locations l ON d.locationid = l.locationid
JOIN bronze.countries c ON l.countryid = c.countryid
LEFT JOIN geochem._map_occurrence_type mt ON mt.bronze_id = d.deposit_type_id
WHERE c.countryname ILIKE '%greenland%';

INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
SELECT 'OCCURRENCE', o.occurrence_id, 'BRONZE_CRITICIALMINERALSEXP', o._bronze_depositid::text,
       'migration_greenland_20260930', now()
FROM core.occurrences o
WHERE o._bronze_depositid IS NOT NULL;

-- Commodities for the 28 occurrences (feeds core.occurrences.commodities via
-- the existing core.refresh_occurrence_commodities trigger on insert here).
CREATE TABLE geochem._map_commodity AS
SELECT b.commodity_id AS bronze_id, g.commodity_id AS gold_id
FROM bronze.commodities b JOIN core.commodities g ON g.commodity_name = b.commodity_name;

INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by, created_date)
SELECT o.occurrence_id, mc.gold_id, dc.commodity_role, true, 'migration_greenland_20260930', now()
FROM bronze.deposit_commodities dc
JOIN core.occurrences o ON o._bronze_depositid = dc.depositid
JOIN geochem._map_commodity mc ON mc.bronze_id = dc.commodity_id;

ALTER TABLE core.occurrences DROP COLUMN _bronze_depositid;
DROP TABLE geochem._map_occurrence_type;
DROP TABLE geochem._map_commodity;

-- Verify: expect 28, each with a sensible name/commodities array.
SELECT occurrence_id, name, is_deposit, occurrence_type_name, commodities
FROM core.occurrences WHERE created_by = 'migration_greenland_20260930'
ORDER BY occurrence_id;

-- Review the output above, then type COMMIT; or ROLLBACK;
