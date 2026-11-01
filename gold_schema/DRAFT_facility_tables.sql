-- DRAFT - NOT APPLIED. For review before the USGS "Mines, smelters, refineries, and recycling facilities in the
-- United States" (2026) load.  Source sheet: 849 facilities / 1,289 rows (one row per facility x commodity),
-- 731 rows with an annual capacity, up to nine equity owners per row.
--
-- Fit with the existing gold layer:
--   * A facility is a core.occurrences row (is_deposit = false, workings_type 'Processing plant' or the mine type).
--     No change to core.occurrences needed for that.
--   * Its USGS facility id (USA0001 ...) goes in core.external_ids (entity_type 'OCCURRENCE', source_system
--     'USGS_US_FACILITIES') - existing table.
--   * Commodities served: core.occurrence_commodities (existing).
--   * Two new tables below: annual capacity (a flow, so NOT core.resource_estimates, which is in-ground stock) and ownership.
--   * Default privileges already give cm_app_readonly SELECT on new core tables - no GRANT needed.

BEGIN;

-- 1. Annual production capacity: one row per published sheet row (facility x commodity x stage/form).
CREATE TABLE core.facility_capacity (
    facility_capacity_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id          integer NOT NULL REFERENCES core.occurrences(occurrence_id),
    commodity_id           integer REFERENCES core.commodities(commodity_id),   -- NULL where the commodity is not in core.commodities (e.g. lime, gypsum)
    commodity_name         text NOT NULL,                  -- as published ('Level 2 (Commodity)')
    commodity_group        text,                           -- 'Level 1 (Commodity group)': Platinum-group metals, Rare earths, ...
    feature_type           varchar(40),                    -- 'Mines and Quarries' | 'Mineral Processing Plant'
    facility_stage         varchar(40),                    -- 'Level 3 (Type)': Mine, Concentrator, Smelter, Refinery, 'Smelter, Refinery'
    phase                  varchar(40),                    -- 'Level 4': Primary, Secondary, Byproduct, Intermediate, Tailings
    product_form           text,                           -- 'Level 5': Concentrates, Ore, Metal, Cathodes, Oxide, Solvent extraction ...
    product_descriptor     text,                           -- GMAS descriptor, e.g. 'Cu content', 'High-calcium quicklime'
    annual_capacity        numeric,                        -- NULL where published as -999 (unknown); never 0 for unknown
    capacity_unit          varchar(20),                    -- 'mt' = metric tons for every populated row in the 2026 sheet
    capacity_basis         varchar(30),                    -- ELEMENTAL_CONTENT | GROSS_WEIGHT | COMPOUND_WEIGHT (sheet: 'Commodity Unit classification')
    capacity_notes         text,
    shared_with_rows       text[],                         -- source_row_ids that SHARE this capacity figure ('Shared Capacity'); do not add shared rows together
    facility_status        varchar(30),                    -- as published: Assumed active | In development | Care and maintenance | Inactive
    multiple_commodities   boolean,
    multiple_products      boolean,
    data_year              smallint,                       -- 2026
    source_system          varchar(100) NOT NULL DEFAULT 'USGS_US_FACILITIES',
    source_row_id          varchar(30) NOT NULL,           -- the sheet's 'Global entry' (U1, U2 ...)
    footnote               text,                           -- Commodity Footnote
    source_urls            text[],                         -- Data Source 1-4
    is_active              boolean NOT NULL DEFAULT true,
    created_by             varchar(100) NOT NULL DEFAULT current_user,
    created_date           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT facility_capacity_basis_chk CHECK (capacity_basis IS NULL OR capacity_basis IN ('ELEMENTAL_CONTENT','GROSS_WEIGHT','COMPOUND_WEIGHT')),
    CONSTRAINT facility_capacity_nonneg_chk CHECK (annual_capacity IS NULL OR annual_capacity >= 0),
    UNIQUE (source_system, source_row_id)
);
CREATE INDEX idx_facility_capacity_occurrence ON core.facility_capacity(occurrence_id);
CREATE INDEX idx_facility_capacity_commodity  ON core.facility_capacity(commodity_id) WHERE commodity_id IS NOT NULL;

-- 2. Ownership / operator: one row per owner per facility (the sheet repeats owners on each commodity row; the loader de-duplicates).
CREATE TABLE core.occurrence_ownership (
    ownership_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id     integer NOT NULL REFERENCES core.occurrences(occurrence_id),
    owner_name        text NOT NULL,                       -- as published
    company_id        integer REFERENCES core.companies(company_id),   -- set only where the owner matches one of the (currently 30) core.companies rows
    ownership_role    varchar(20) NOT NULL,                -- OPERATOR | EQUITY_OWNER
    share_pct         numeric,                             -- NULL if not published
    as_of_year        smallint,
    source_system     varchar(100) NOT NULL DEFAULT 'USGS_US_FACILITIES',
    footnote          text,                                -- Company Footnote
    is_active         boolean NOT NULL DEFAULT true,
    created_by        varchar(100) NOT NULL DEFAULT current_user,
    created_date      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT occurrence_ownership_role_chk  CHECK (ownership_role IN ('OPERATOR','EQUITY_OWNER')),
    CONSTRAINT occurrence_ownership_share_chk CHECK (share_pct IS NULL OR (share_pct >= 0 AND share_pct <= 100)),
    UNIQUE (occurrence_id, source_system, ownership_role, owner_name)
);
CREATE INDEX idx_occurrence_ownership_occurrence ON core.occurrence_ownership(occurrence_id);
CREATE INDEX idx_occurrence_ownership_company    ON core.occurrence_ownership(company_id) WHERE company_id IS NOT NULL;

-- 3. OPTIONAL (changes an existing table, so your call): the sheet has no coordinates, only 'Town, ST'.
--    Facilities are placed by (a) snapping to a matching MRDS / Washington record or (b) the town centre. Recording
--    how each position was obtained keeps town-centre points out of the sample-to-deposit links and lets the app say so.
-- ALTER TABLE core.occurrences ADD COLUMN position_accuracy varchar(20);   -- NULL = as published; else SNAPPED | TOWN_CENTROID
-- (nullable, no default: instant, no table rewrite. link_samples_to_occurrences.py would skip TOWN_CENTROID rows.)

-- Status mapping for occurrences.status (no constraint exists, so no DDL): Assumed active -> PRODUCER, In development -> DEVELOPMENT,
-- Inactive -> CLOSED, Care and maintenance -> CARE_AND_MAINTENANCE (new value) or CLOSED - decide before the load.

COMMIT;
