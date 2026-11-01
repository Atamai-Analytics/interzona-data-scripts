-- ============================================================================
-- GOLD SCHEMA DDL — Critical Minerals AI Web App
-- Target DB: interzona_cm ("gold"), same RDS instance as criticialmineralsexp ("bronze")
-- Reflects the design finalized in gold_schema_proposal.html after cardinality review, PLUS
-- a later revision (2026-09-17) that collapsed a separate synced `agent` schema into
-- core/geochem directly — see the COLLAPSED DESIGN note on geochem.analytical_results below,
-- and gold_schema/agent_layer_draft.sql for the fuller writeup of that revision.
-- This file matches what's actually LIVE on interzona_cm as of 2026-09-17.
-- Naming convention fixed vs. bronze: created_by/created_date/modified_by/modified_date/
-- is_active everywhere (bronze mixed createdby/created_by, isactive/is_active per table).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ----------------------------------------------------------------------------
-- 1. SCHEMAS
-- ----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS geochem;
CREATE SCHEMA IF NOT EXISTS docs;
CREATE SCHEMA IF NOT EXISTS financials;

-- ============================================================================
-- 2. CORE
-- ============================================================================

CREATE TABLE core.jurisdictions (
    jurisdiction_id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_jurisdiction_id  integer REFERENCES core.jurisdictions(jurisdiction_id),
    level                   varchar(20) NOT NULL,   -- COUNTRY, STATE_PROVINCE, DISTRICT
    name                    varchar(200) NOT NULL,
    official_name           varchar(200),
    iso_code                varchar(10),
    iso_code3               varchar(10),
    is_active               boolean NOT NULL DEFAULT true,
    created_by              varchar(100) NOT NULL DEFAULT current_user,
    created_date            timestamptz NOT NULL DEFAULT now(),
    modified_by             varchar(100),
    modified_date           timestamptz
);
CREATE INDEX idx_jurisdictions_parent ON core.jurisdictions(parent_jurisdiction_id);
CREATE INDEX idx_jurisdictions_level ON core.jurisdictions(level);

CREATE TABLE core.commodities (
    commodity_id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_commodity_id     integer REFERENCES core.commodities(commodity_id),
    commodity_name          varchar(150) NOT NULL,
    commodity_symbol        varchar(20),
    commodity_category      varchar(100) NOT NULL,
    is_critical_mineral     boolean NOT NULL DEFAULT false,
    description             text,
    is_active               boolean NOT NULL DEFAULT true,
    created_by              varchar(100) NOT NULL DEFAULT current_user,
    created_date            timestamptz NOT NULL DEFAULT now(),
    modified_by             varchar(100),
    modified_date           timestamptz,
    UNIQUE (commodity_name)
);
CREATE INDEX idx_commodities_parent ON core.commodities(parent_commodity_id);

CREATE TABLE core.occurrence_types (
    occurrence_type_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type_name                varchar(150) NOT NULL,
    type_group                varchar(150) NOT NULL,
    description              text,
    is_active                boolean NOT NULL DEFAULT true,
    created_by                varchar(100) NOT NULL DEFAULT current_user,
    created_date              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.companies (
    company_id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                      text NOT NULL,
    short_name                text,
    ticker                    text,
    exchange                  text,
    isin                      text,
    hq_jurisdiction_id        integer REFERENCES core.jurisdictions(jurisdiction_id),
    company_type              varchar(50),
    stage                     varchar(50),
    primary_commodity_id      integer REFERENCES core.commodities(commodity_id),
    market_cap_usd             numeric,
    employees                  integer,
    website                    text,
    is_active                  boolean NOT NULL DEFAULT true,
    created_by                 varchar(100) NOT NULL DEFAULT current_user,
    created_date                timestamptz NOT NULL DEFAULT now(),
    modified_by                 varchar(100),
    modified_date                timestamptz
);
CREATE INDEX idx_companies_ticker ON core.companies(ticker);
CREATE INDEX idx_companies_name_trgm ON core.companies USING gin (name gin_trgm_ops);

CREATE TABLE core.company_commodities (
    company_commodity_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                integer NOT NULL REFERENCES core.companies(company_id),
    commodity_id               integer NOT NULL REFERENCES core.commodities(commodity_id),
    is_active                   boolean NOT NULL DEFAULT true,
    created_by                  varchar(100) NOT NULL DEFAULT current_user,
    created_date                 timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, commodity_id)
);

-- projects: new concept, doesn't exist in bronze. Simple FK to company (v1 — no JV/ownership history).
CREATE TABLE core.projects (
    project_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                 integer REFERENCES core.companies(company_id),
    name                        text NOT NULL,
    jurisdiction_id              integer REFERENCES core.jurisdictions(jurisdiction_id),
    status                       varchar(50),
    primary_commodity_id          integer REFERENCES core.commodities(commodity_id),
    geom                          geometry(Point, 4326),
    description                   text,
    is_active                     boolean NOT NULL DEFAULT true,
    created_by                    varchar(100) NOT NULL DEFAULT current_user,
    created_date                   timestamptz NOT NULL DEFAULT now(),
    modified_by                    varchar(100),
    modified_date                   timestamptz
);
CREATE INDEX idx_projects_company ON core.projects(company_id);
CREATE INDEX idx_projects_geom ON core.projects USING gist(geom);

-- occurrences: generalizes bronze's deposits. is_deposit flags an economic deposit vs. a
-- prospect/occurrence. Carries a DIRECT nullable company_id (independent of project_id) —
-- an occurrence can belong to a company before it's grouped into a named project.
CREATE TABLE core.occurrences (
    occurrence_id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id                   integer REFERENCES core.projects(project_id),
    company_id                    integer REFERENCES core.companies(company_id),
    name                           text NOT NULL,
    is_deposit                      boolean NOT NULL DEFAULT false,
    occurrence_type_id               integer REFERENCES core.occurrence_types(occurrence_type_id),
    occurrence_type_name              text,     -- resolved from occurrence_type_id by trg_resolve_occurrence_own_fields
    jurisdiction_id                   integer REFERENCES core.jurisdictions(jurisdiction_id),
    jurisdiction_path                  text[],  -- root-to-leaf, e.g. {'United States','Washington'}; resolved by trg_resolve_occurrence_own_fields
    country_name                        text,   -- = jurisdiction_path[1], resolved by the same trigger
    commodities                          text[] NOT NULL DEFAULT '{}',  -- aggregated from occurrence_commodities by trg_refresh_occurrence_commodities
    geom                               geometry(Point, 4326) NOT NULL,
    lat                                  double precision GENERATED ALWAYS AS (ST_Y(geom)) STORED,
    lon                                  double precision GENERATED ALWAYS AS (ST_X(geom)) STORED,
    geog                                  geography(Point, 4326) GENERATED ALWAYS AS (geom::geography) STORED,
    elevation_m                         numeric,   -- not always populated
    geological_province                 varchar(150),
    geological_subprovince               varchar(150),
    geological_district                   varchar(150),
    tectonic_setting                       varchar(150),
    regional_structure                      text,  -- widened from varchar(150) during Argentina migration: bronze has values up to 224 chars
    metallogenic_association                 varchar(150),
    deposit_form                              text,  -- widened from varchar(150): bronze has values up to 303 chars
    mineralization_style                       text,  -- widened from varchar(150): bronze has values up to 884 chars
    associated_igneous                          text,  -- widened from varchar(150): bronze has values up to 432 chars
    alteration                                   text,
    status                                        varchar(50),
    size_category                                 varchar(50),
    workings_type                                  varchar(50),
    comments                                        text,
    is_active                                        boolean NOT NULL DEFAULT true,
    created_by                                        varchar(100) NOT NULL DEFAULT current_user,
    created_date                                       timestamptz NOT NULL DEFAULT now(),
    modified_by                                         varchar(100),
    modified_date                                        timestamptz
);
CREATE INDEX idx_occurrences_project ON core.occurrences(project_id);
CREATE INDEX idx_occurrences_company ON core.occurrences(company_id);
CREATE INDEX idx_occurrences_geom ON core.occurrences USING gist(geom);
CREATE INDEX idx_occurrences_geog ON core.occurrences USING gist(geog);
CREATE INDEX idx_occurrences_is_deposit ON core.occurrences(is_deposit) WHERE is_deposit;
CREATE INDEX idx_occurrences_name_trgm ON core.occurrences USING gin (name gin_trgm_ops);
CREATE INDEX idx_occurrences_commodities ON core.occurrences USING gin(commodities);
CREATE INDEX idx_occurrences_jurisdiction_path ON core.occurrences USING gin(jurisdiction_path);
CREATE INDEX idx_occurrences_country ON core.occurrences(country_name);

-- Resolves occurrence_type_name + jurisdiction_path + country_name whenever this row's own
-- occurrence_type_id / jurisdiction_id changes. Recursive CTE walks the jurisdiction hierarchy
-- to arbitrary depth (country -> state -> district), root-to-leaf. Same-row resolution, no
-- separate synced table needed — this is the collapsed design, not a first pass.
CREATE OR REPLACE FUNCTION core.resolve_occurrence_own_fields() RETURNS trigger AS $$
BEGIN
    IF NEW.occurrence_type_id IS NOT NULL THEN
        SELECT type_name INTO NEW.occurrence_type_name
        FROM core.occurrence_types WHERE occurrence_type_id = NEW.occurrence_type_id;
    END IF;

    IF NEW.jurisdiction_id IS NULL THEN
        NEW.jurisdiction_path := NULL;
        NEW.country_name := NULL;
    ELSE
        WITH RECURSIVE path AS (
            SELECT jurisdiction_id, parent_jurisdiction_id, name, 1 AS depth
            FROM core.jurisdictions WHERE jurisdiction_id = NEW.jurisdiction_id
            UNION ALL
            SELECT j.jurisdiction_id, j.parent_jurisdiction_id, j.name, p.depth + 1
            FROM core.jurisdictions j JOIN path p ON j.jurisdiction_id = p.parent_jurisdiction_id
        )
        SELECT array_agg(name ORDER BY depth DESC) INTO NEW.jurisdiction_path FROM path;
        NEW.country_name := NEW.jurisdiction_path[1];
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resolve_occurrence_own_fields
    BEFORE INSERT OR UPDATE OF occurrence_type_id, jurisdiction_id ON core.occurrences
    FOR EACH ROW EXECUTE FUNCTION core.resolve_occurrence_own_fields();

CREATE TABLE core.occurrence_commodities (
    occurrence_commodity_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id               integer NOT NULL REFERENCES core.occurrences(occurrence_id),
    commodity_id                  integer NOT NULL REFERENCES core.commodities(commodity_id),
    commodity_role                 varchar(30),   -- PRIMARY / SECONDARY
    is_active                       boolean NOT NULL DEFAULT true,
    created_by                       varchar(100) NOT NULL DEFAULT current_user,
    created_date                      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (occurrence_id, commodity_id)
);

-- commodities on core.occurrences is aggregated from THIS child table, so it needs its own
-- trigger here rather than on occurrences itself — it can change without the occurrence row
-- being touched at all.
CREATE OR REPLACE FUNCTION core.refresh_occurrence_commodities() RETURNS trigger AS $$
DECLARE
    target_id integer := COALESCE(NEW.occurrence_id, OLD.occurrence_id);
BEGIN
    UPDATE core.occurrences o
    SET commodities = COALESCE((
        SELECT array_agg(DISTINCT c.commodity_name ORDER BY c.commodity_name)
        FROM core.occurrence_commodities oc
        JOIN core.commodities c ON c.commodity_id = oc.commodity_id
        WHERE oc.occurrence_id = target_id AND oc.is_active
    ), '{}')
    WHERE o.occurrence_id = target_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_refresh_occurrence_commodities
    AFTER INSERT OR UPDATE OR DELETE ON core.occurrence_commodities
    FOR EACH ROW EXECUTE FUNCTION core.refresh_occurrence_commodities();

-- resource_estimates: new. Keyed on occurrence_id (JORC/NI 43-101 classifies a specific
-- mineralized body — one project can bundle occurrences with different classifications).
-- source_document_id FK added in section 8 (docs.documents doesn't exist yet at this point).
CREATE TABLE core.resource_estimates (
    resource_estimate_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id                 integer NOT NULL REFERENCES core.occurrences(occurrence_id),
    commodity_id                    integer REFERENCES core.commodities(commodity_id),
    classification                   varchar(30) NOT NULL,  -- MEASURED/INDICATED/INFERRED/PROVEN/PROBABLE
    reporting_standard                varchar(30),            -- JORC / NI43-101 / SAMREC
    effective_date                     date,
    tonnage                              numeric,
    tonnage_unit                          varchar(20),
    grade                                   numeric,
    grade_unit                               varchar(20),
    contained_metal                           numeric,
    contained_metal_unit                       varchar(20),
    cutoff_grade                                 numeric,
    cutoff_grade_unit                              varchar(20),
    competent_person                                text,
    source_document_id                                bigint,  -- FK added in section 8
    is_active                                           boolean NOT NULL DEFAULT true,
    created_by                                           varchar(100) NOT NULL DEFAULT current_user,
    created_date                                          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_resource_estimates_occurrence ON core.resource_estimates(occurrence_id);
CREATE INDEX idx_resource_estimates_commodity ON core.resource_estimates(commodity_id);

-- generic lineage crosswalk — replaces bronze's habit of burying source ids in free-text
-- comments (e.g. deposits.comments containing "LithoSurfer sourceId: WA:5173")
CREATE TABLE core.external_ids (
    external_id_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type           varchar(30) NOT NULL,     -- OCCURRENCE, PROJECT, COMPANY, SAMPLE, SAMPLING_LINE, ...
    entity_id               bigint NOT NULL,
    source_system             varchar(100) NOT NULL,  -- e.g. 'bronze.criticialmineralsexp', 'SIGAM', 'WA_DGER'
    source_id                   varchar(200) NOT NULL,
    match_confidence              varchar(20),          -- EXACT / HIGH / MEDIUM / LOW
    created_by                     varchar(100) NOT NULL DEFAULT current_user,
    created_date                    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, source_system, source_id)
);
CREATE INDEX idx_external_ids_entity ON core.external_ids(entity_type, entity_id);

-- geology_summary: the one thing that's genuinely a many-rows-to-one aggregate (lithology +
-- age + mineralogy observations rolled up per occurrence), so unlike occurrence_type_name/
-- commodities/jurisdiction_path it can't collapse into a same-row resolution — it stays its
-- own table. Refresh trigger(s) from lithology_observations/age_measured/occurrence_mineralogy
-- not yet built (TODO — low risk, this table is occurrence-scoped, thousands of rows not millions).
CREATE TABLE core.geology_summary (
    occurrence_id         integer PRIMARY KEY REFERENCES core.occurrences(occurrence_id),
    dominant_lithology        text,
    dominant_alteration          text,
    dominant_mineral               text,
    dominant_formation                text,   -- mode of lithology_observations.strat_formation
    dominant_stratigraphic_age          text,  -- mode of age_stratigraphic -> stratigraphic_age_reference.age_name
    primary_age_ma                        numeric,  -- best-precision age_measured.age_ma (lowest error %, then most analyses, then most recent) — NOT a mineralization/crystallization-tagged pick, see refresh_geology_summary
    primary_age_method                      text,   -- dating method name for the row primary_age_ma was picked from
    observations                          jsonb NOT NULL DEFAULT '[]',
    -- observations is the catch-all for everything not promoted to its own column:
    -- [{"type":"lithology","name":"...","depth_from":10,"depth_to":45,
    --   "strat_group":"...","strat_formation":"...","strat_member":"...","strat_bed":"..."},
    --  {"type":"age","age_ma":65.2,"method":"U-Pb","error_pct":0.8,"n_analyses":12},
    --  {"type":"stratigraphic_age","name":"Cretaceous","age_start_ma":145,"age_end_ma":66,"confidence":"HIGH"},
    --  {"type":"mineral","name":"chalcopyrite","role":"ore","zone":"supergene"},
    --  {"type":"alteration","name":"phyllic","depth_from":50,"depth_to":120}]
    updated_at                        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_geology_summary_observations     ON core.geology_summary USING gin(observations);
CREATE INDEX idx_geology_summary_dominant_mineral ON core.geology_summary(dominant_mineral);
CREATE INDEX idx_geology_summary_formation         ON core.geology_summary(dominant_formation);
CREATE INDEX idx_geology_summary_strat_age          ON core.geology_summary(dominant_stratigraphic_age);
CREATE INDEX idx_geology_summary_primary_age         ON core.geology_summary(primary_age_ma);

-- ============================================================================
-- 3. GEOCHEM — reference / lookup tables (migrate largely as-is from bronze)
-- ============================================================================

CREATE TABLE geochem.laboratories (
    lab_id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lab_code            varchar(30) NOT NULL UNIQUE,
    lab_name              varchar(200) NOT NULL,
    accreditation           varchar(200),
    contact_info              text,
    is_active                  boolean NOT NULL DEFAULT true,
    created_by                  varchar(100) NOT NULL DEFAULT current_user,
    created_date                 timestamptz NOT NULL DEFAULT now(),
    modified_by                   varchar(100),
    modified_date                  timestamptz
);

CREATE TABLE geochem.units (
    unit_id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_code            varchar(20) NOT NULL UNIQUE,
    unit_name              varchar(100) NOT NULL,
    unit_type                varchar(50),
    unit_category              varchar(50),
    base_unit                    varchar(20),
    unit_description                text,
    common_usage                      text,
    is_active                          boolean NOT NULL DEFAULT true,
    created_by                          varchar(100) NOT NULL DEFAULT current_user,
    created_date                         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.unit_conversions (
    conversion_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_unit_id              integer NOT NULL REFERENCES geochem.units(unit_id),
    to_unit_id                  integer NOT NULL REFERENCES geochem.units(unit_id),
    conversion_factor             numeric NOT NULL,
    conversion_offset               numeric,
    conversion_formula                varchar(200),
    applicable_conditions               varchar(200),
    notes                                  varchar(200),
    is_active                              boolean NOT NULL DEFAULT true,
    created_by                              varchar(100) NOT NULL DEFAULT current_user,
    created_date                             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (from_unit_id, to_unit_id)
);

CREATE TABLE geochem.qualifiers (
    qualifier_id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    qualifier_code              varchar(10) NOT NULL UNIQUE,
    qualifier_name                varchar(100) NOT NULL,
    qualifier_description           varchar(300) NOT NULL,
    analytical_meaning                 varchar(300),
    is_active                            boolean NOT NULL DEFAULT true,
    created_by                            varchar(100) NOT NULL DEFAULT current_user,
    created_date                           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.analytes (
    analyte_id                     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    analyte_code                      varchar(20) NOT NULL UNIQUE,
    analyte_name                        varchar(100) NOT NULL,
    element_symbol                        varchar(10),
    atomic_number                           integer,
    atomic_weight                             numeric,
    element_group                               varchar(50),
    is_element                                    boolean,
    is_oxide                                        boolean,
    typical_reporting_unit                            varchar(20),
    is_volatile                                         boolean,
    hosted_in_resistant_minerals                          boolean,
    is_critical_mineral                                      boolean,
    critical_mineral_category                                  varchar(100),
    critical_mineral_jurisdiction                                varchar(100),
    geochemical_behavior                                           varchar(150),  -- widened from 100 during reference-table seeding: bronze has values up to 109 chars
    geochemical_group                                                varchar(100),
    pathfinder_for                                                     varchar(200),
    pathfinder_association                                               varchar(200),
    typical_crustal_abundance                                              numeric,
    typical_crustal_abundance_unit                                           varchar(20),
    common_mineral_hosts                                                       varchar(300),
    typical_mineral_hosts                                                        varchar(300),
    preferred_technique                                                            varchar(200),
    common_interferences                                                             varchar(300),
    requires_special_handling                                                          boolean,
    handling_notes                                                                       varchar(300),
    environmental_concern                                                                  boolean,
    regulatory_threshold                                                                     numeric,
    regulatory_threshold_unit                                                                  varchar(20),
    mineralogical_significance                                                                   varchar(300),
    exploration_importance                                                                         varchar(300),
    health_hazards                                                                                   varchar(300),
    plausible_max_value                                                                                numeric,
    plausible_max_unit                                                                                   varchar(20),
    plausible_max_notes                                                                                    varchar(300),
    pct_ore_grade_only                                                                                       boolean,
    pct_ore_grade_threshold                                                                                    numeric,
    pct_ore_grade_notes                                                                                          varchar(300),
    pct_reporting_valid                                                                                            boolean,
    pct_reporting_valid_notes                                                                                        varchar(300),
    analysis_group                                                                                                     varchar(100),
    notes                                                                                                                text,
    is_active                                                                                                             boolean NOT NULL DEFAULT true,
    created_by                                                                                                             varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                                                                             timestamptz NOT NULL DEFAULT now(),
    modified_by                                                                                                              varchar(100),
    modified_date                                                                                                             timestamptz
);
CREATE INDEX idx_analytes_element_symbol ON geochem.analytes(element_symbol);
CREATE INDEX idx_analytes_critical ON geochem.analytes(is_critical_mineral) WHERE is_critical_mineral;

CREATE TABLE geochem.analytical_methods (
    method_id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    method_code                     varchar(20) NOT NULL UNIQUE,
    method_name                       varchar(150) NOT NULL,
    digest_code                         varchar(20) NOT NULL,
    digest_name                           varchar(150) NOT NULL,
    digest_chemical_formula                 varchar(100),
    digest_temp_celsius                       integer,
    digest_completeness                         varchar(50),
    digest_volatilisation                         text,
    digest_resistant_to                             text,
    digest_description                                text,
    instrument_code                                     varchar(20) NOT NULL,
    instrument_name                                       varchar(150) NOT NULL,
    instrument_description                                  text,
    application                                               varchar(200),
    notes                                                       text,
    is_active                                                     boolean NOT NULL DEFAULT true,
    created_by                                                     varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.preparation_methods (
    prep_method_id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prep_code                       varchar(20) NOT NULL UNIQUE,
    prep_name                         varchar(150) NOT NULL,
    description                         text,
    target_particle_size_microns          integer,
    notes                                    text,
    is_active                                 boolean NOT NULL DEFAULT true,
    created_by                                 varchar(100) NOT NULL DEFAULT current_user,
    created_date                                timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.analytical_packages (
    package_id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    package_code                    varchar(50) NOT NULL UNIQUE,  -- widened from 20 during reference-table seeding: bronze has codes up to 29 chars
    package_name                      varchar(150) NOT NULL,
    lab_id                              integer NOT NULL REFERENCES geochem.laboratories(lab_id),
    prep_method_id                        integer REFERENCES geochem.preparation_methods(prep_method_id),
    method_id                               integer REFERENCES geochem.analytical_methods(method_id),
    package_type                              varchar(50),
    element_suite                               varchar(200),
    minimum_sample_weight                         numeric,
    minimum_sample_weight_unit                      varchar(20),
    recommended_sample_weight                         numeric,
    recommended_sample_weight_unit                      varchar(20),
    suitable_sample_types                                 varchar(200),
    unsuitable_sample_types                                 varchar(200),
    source_method                                             varchar(100),
    description                                                 text,
    notes                                                         text,
    is_active                                                       boolean NOT NULL DEFAULT true,
    created_by                                                       varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.fraction_types (
    fraction_type_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fraction_type_code        varchar(20) NOT NULL UNIQUE,
    fraction_type_name          varchar(100) NOT NULL,
    description                    text,
    is_active                        boolean NOT NULL DEFAULT true,
    created_by                        varchar(100) NOT NULL DEFAULT current_user,
    created_date                       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.size_fractions (
    size_fraction_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    size_fraction_code         varchar(30) NOT NULL UNIQUE,
    size_min                     numeric,
    size_max                       numeric,
    size_unit                        varchar(20),
    description                        varchar(200),
    is_active                            boolean NOT NULL DEFAULT true,
    created_by                            varchar(100) NOT NULL DEFAULT current_user,
    created_date                            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.sample_type_categories (
    category_code           varchar(30) PRIMARY KEY,
    category_name              varchar(100) NOT NULL,
    description                   text,
    sort_order                      integer
);

CREATE TABLE geochem.sample_types (
    sample_type_id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sample_type_code             varchar(30) NOT NULL UNIQUE,
    sample_type_name               varchar(150) NOT NULL,
    category_code                     varchar(30) REFERENCES geochem.sample_type_categories(category_code),
    parent_type_id                       integer REFERENCES geochem.sample_types(sample_type_id),
    specificity_level                       integer,
    sample_context                            varchar(50),
    requires_interval                           boolean,
    typical_weight_kg                             numeric,
    typical_size_fraction                           varchar(50),
    primary_use                                       varchar(150),
    suitable_for                                        text,
    description                                           text,
    collection_method                                       text,
    is_generic                                                boolean,
    is_active                                                   boolean NOT NULL DEFAULT true,
    created_by                                                    varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.drill_types (
    drill_type_id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drill_type_code               varchar(20) NOT NULL UNIQUE,
    drill_type_name                 varchar(100) NOT NULL,
    drill_type_category               varchar(50),
    description                         text,
    typical_depth_min                     numeric,
    typical_depth_max                       numeric,
    sample_quality                            varchar(50),
    relative_cost                               varchar(50),
    display_order                                 integer,
    is_active                                       boolean NOT NULL DEFAULT true,
    created_by                                       varchar(100) NOT NULL DEFAULT current_user,
    created_date                                       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.drill_diameters (
    diameter_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    diameter_code                  varchar(20) NOT NULL UNIQUE,
    diameter_size                    numeric NOT NULL,
    size_unit_id                       integer NOT NULL REFERENCES geochem.units(unit_id),
    diameter_mm                          numeric,
    diameter_inches                        numeric,
    typical_drill_type                       varchar(100),
    description                                varchar(200),
    display_order                                integer,
    is_active                                      boolean NOT NULL DEFAULT true,
    created_by                                      varchar(100) NOT NULL DEFAULT current_user,
    created_date                                      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.core_sizes (
    core_size_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    core_size_code                  varchar(20) NOT NULL UNIQUE,
    core_size_name                    varchar(100) NOT NULL,
    core_diameter                       numeric NOT NULL,
    hole_diameter                         numeric NOT NULL,
    core_diameter_inches                    numeric,
    hole_diameter_inches                      numeric,
    wireline_compatible                         boolean,
    typical_use                                   varchar(200),
    description                                     text,
    display_order                                     integer,
    unit_id                                             integer REFERENCES geochem.units(unit_id),
    is_active                                             boolean NOT NULL DEFAULT true,
    created_by                                             varchar(100) NOT NULL DEFAULT current_user,
    created_date                                             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.lithology_categories (
    category_code             varchar(30) PRIMARY KEY,
    category_name                varchar(100) NOT NULL,
    description                     text,
    sort_order                        integer
);

CREATE TABLE geochem.lithology (
    lithology_id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lithology_code                 varchar(30) NOT NULL UNIQUE,
    lithology_name                    varchar(150) NOT NULL,
    category_code                        varchar(30) REFERENCES geochem.lithology_categories(category_code),
    parent_lithology_id                     integer REFERENCES geochem.lithology(lithology_id),
    iugs_classification                       varchar(150),
    grain_size                                  varchar(50),
    texture                                       varchar(100),
    typical_color                                   varchar(100),
    typical_minerals                                  text,
    forming_environment                                 text,
    description                                           text,
    synonyms                                                text,
    abbreviation                                              varchar(20),
    is_primary                                                  boolean,
    mindat_id                                                     integer,
    mindat_name                                                     varchar(150),
    mindat_match_score                                                numeric,
    mindat_match_method                                                 varchar(50),
    is_used                                                               boolean,
    is_active                                                               boolean NOT NULL DEFAULT true,
    created_by                                                               varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.alteration_reference (
    alteration_id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alteration_type                 varchar(150) NOT NULL,
    alteration_category               varchar(100),
    description                         text,
    key_minerals                          text,
    temperature_min_c                       numeric,
    temperature_max_c                         numeric,
    ph_conditions                               varchar(50),
    fluid_type                                    varchar(100),
    typical_deposit_types                           text,
    spatial_position                                  varchar(100),
    intensity_indicator                                 varchar(100),
    common_metals                                         text,
    notes                                                   text,
    is_active                                                 boolean NOT NULL DEFAULT true,
    created_by                                                 varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                 timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.dating_instruments (
    instrument_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_code                  varchar(20) NOT NULL UNIQUE,
    instrument_name                     varchar(150) NOT NULL,
    description                            text,
    is_active                                boolean NOT NULL DEFAULT true,
    created_by                                varchar(100) NOT NULL DEFAULT current_user,
    created_date                                timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.dating_method_reference (
    dating_method_id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    method_name                       varchar(150) NOT NULL,
    method_type                          varchar(50) NOT NULL,
    description                             text,  -- widened from varchar(300) during reference-table seeding: bronze has descriptions up to 310 chars
    typical_precision                          varchar(100),
    applicable_age_range                          varchar(100),
    is_active                                        boolean NOT NULL DEFAULT true,
    created_by                                        varchar(100) NOT NULL DEFAULT current_user,
    created_date                                        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.age_reference (
    age_reference_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name                         varchar(200) NOT NULL,
    source_record_id                       varchar(100),
    citation                                  text,
    authors                                     text,
    publication_year                              integer,
    doi                                              varchar(200),
    url                                                text,
    comments                                             text,
    is_active                                              boolean NOT NULL DEFAULT true,
    created_by                                              varchar(100) NOT NULL DEFAULT current_user,
    created_date                                              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.age_type_reference (
    age_type_id                       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    age_type_name                          varchar(150) NOT NULL,
    description                                text,
    is_active                                     boolean NOT NULL DEFAULT true,
    created_by                                     varchar(100) NOT NULL DEFAULT current_user,
    created_date                                     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geochem.stratigraphic_age_reference (
    stratigraphic_age_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    age_name                                 varchar(150) NOT NULL,
    age_type                                    varchar(50) NOT NULL,
    parent_age_id                                  integer REFERENCES geochem.stratigraphic_age_reference(stratigraphic_age_id),
    age_start_ma                                      numeric,
    age_end_ma                                          numeric,
    age_rank                                              integer,
    region                                                  varchar(100),
    is_official                                               boolean NOT NULL DEFAULT true,
    description                                                 text,
    reference                                                     varchar(300),
    is_active                                                       boolean NOT NULL DEFAULT true,
    created_by                                                       varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                       timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- 4. GEOCHEM — entity tables
-- ============================================================================

-- sampling_lines: unifies drillholes, trenches and channels. feature_type discriminator;
-- geom is a Point for a drillhole collar, a LineString for a trench/channel — enforced below.
CREATE TABLE geochem.sampling_lines (
    sampling_line_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id                integer REFERENCES core.occurrences(occurrence_id),
    feature_type                    varchar(20) NOT NULL CHECK (feature_type IN ('DRILLHOLE','TRENCH','CHANNEL')),
    hole_id                            varchar(100),
    name                                  text,
    geom                                    geometry(Geometry, 4326) NOT NULL,
    elevation_m                              numeric,   -- collar elevation, not always populated
    drill_type_id                            integer REFERENCES geochem.drill_types(drill_type_id),
    diameter_id                                integer REFERENCES geochem.drill_diameters(diameter_id),
    core_size_id                                 integer REFERENCES geochem.core_sizes(core_size_id),
    total_depth                                    numeric,
    azimuth                                          numeric,
    dip                                                numeric,
    length_m                                             numeric,
    start_date                                             date,
    end_date                                                 date,
    comments                                                   text,
    is_active                                                    boolean NOT NULL DEFAULT true,
    created_by                                                    varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                    timestamptz NOT NULL DEFAULT now(),
    modified_by                                                      varchar(100),
    modified_date                                                     timestamptz,
    CONSTRAINT chk_sampling_line_geom_type CHECK (
        (feature_type = 'DRILLHOLE' AND GeometryType(geom) = 'POINT')
        OR (feature_type IN ('TRENCH','CHANNEL') AND GeometryType(geom) IN ('LINESTRING','MULTILINESTRING'))
    )
);
CREATE INDEX idx_sampling_lines_geom ON geochem.sampling_lines USING gist(geom);
CREATE INDEX idx_sampling_lines_occurrence ON geochem.sampling_lines(occurrence_id);
CREATE INDEX idx_sampling_lines_feature_type ON geochem.sampling_lines(feature_type);

-- samples: always its own explicit point geometry, resolved once at load time (from
-- collar+depth, or line+distance-along) — never computed on the fly. Links directly to an
-- occurrence (surface/grab sample) OR to a sampling_line (with depth/distance-along), or both.
CREATE TABLE geochem.samples (
    sample_id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id                 integer REFERENCES core.occurrences(occurrence_id),
    sampling_line_id                 bigint REFERENCES geochem.sampling_lines(sampling_line_id),
    geom                                geometry(Point, 4326) NOT NULL,
    lat                                  double precision GENERATED ALWAYS AS (ST_Y(geom)) STORED,
    lon                                  double precision GENERATED ALWAYS AS (ST_X(geom)) STORED,
    geog                                  geography(Point, 4326) GENERATED ALWAYS AS (geom::geography) STORED,
    elevation_m                          numeric,   -- the sample's own elevation, not always populated
    source_system                          varchar(50),  -- e.g. 'ARGENTINA_SEGEMAR' — set by the loader; denormalizes onto analytical_results as its partition key
    field_id                              varchar(100),
    sample_number                           varchar(100),
    sample_number_alt                         varchar(100),
    sample_type_id                              integer REFERENCES geochem.sample_types(sample_type_id),
    sample_type_local                             varchar(100),
    sample_context                                  varchar(100),
    depth_from_m                                      numeric,
    depth_to_m                                          numeric,
    distance_along_m                                      numeric,
    sample_date                                             date,
    sample_weight_kg                                          numeric,
    comments                                                    text,
    is_active                                                     boolean NOT NULL DEFAULT true,
    created_by                                                      varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                      timestamptz NOT NULL DEFAULT now(),
    modified_by                                                        varchar(100),
    modified_date                                                       timestamptz,
    CONSTRAINT chk_sample_parent CHECK (occurrence_id IS NOT NULL OR sampling_line_id IS NOT NULL)
);
CREATE INDEX idx_samples_geom ON geochem.samples USING gist(geom);
CREATE INDEX idx_samples_geog ON geochem.samples USING gist(geog);
CREATE INDEX idx_samples_occurrence ON geochem.samples(occurrence_id);
CREATE INDEX idx_samples_sampling_line ON geochem.samples(sampling_line_id);
CREATE INDEX idx_samples_source_system ON geochem.samples(source_system);

-- Shared resolution helper: given an observation's own (occurrence_id, sample_id,
-- sampling_line_id) — any subset may be null — find the occurrence it actually belongs to.
-- A sample attached only via sampling_line_id (no occurrence_id of its own) still resolves
-- correctly, via the sample -> sampling_line -> occurrence chain. Used by
-- resolve_analytical_result_labels below and by the geology_summary refresh triggers.
CREATE OR REPLACE FUNCTION geochem.effective_occurrence_id(
    p_occurrence_id integer,
    p_sample_id bigint,
    p_sampling_line_id bigint
) RETURNS integer AS $$
    SELECT COALESCE(
        p_occurrence_id,
        (SELECT COALESCE(s.occurrence_id, sl.occurrence_id)
         FROM geochem.samples s
         LEFT JOIN geochem.sampling_lines sl ON sl.sampling_line_id = s.sampling_line_id
         WHERE s.sample_id = p_sample_id),
        (SELECT occurrence_id FROM geochem.sampling_lines WHERE sampling_line_id = p_sampling_line_id)
    );
$$ LANGUAGE sql STABLE;

-- analytical_results: 38M rows in bronze today, append-mostly — LIST partitioned by
-- source_system, NOT date_analysed. date-based RANGE partitioning was tried first but abandoned
-- after checking real bronze coverage: only 14.9% of all 38M results have a date, and it's
-- sharply bimodal — USGS (14.7M) and NSW (11.9M), 70% of all bronze analytical data combined,
-- are at 0% date coverage. Whichever region got migrated, the bulk of the data would pile into
-- one default partition regardless — no real pruning value. source_system is always known (set
-- by the loader) and aligns with how data actually gets migrated — region by region — so a
-- partition boundary doubles as an operational unit: reload/reprocess/drop one source
-- independently. date_analysed is kept as a plain column + index for the minority of sources
-- (Finland, Sweden, Denmark) that do have good date coverage.
--
-- COLLAPSED DESIGN: this table carries both the normalized FKs (analyte_id, unit_id,
-- qualifier_id, package_id) AND their resolved text values (analyte_name, unit_code, etc.) on
-- the SAME row, populated together by trg_resolve_analytical_result_labels below. There is no
-- separate agent-facing copy of this table and no sync mechanism — an earlier draft built one
-- (an outbox + async worker keeping a duplicate `agent.sample_results` in sync) and it was
-- deliberately abandoned: resolving against these lookup tables (145 rows, 41 rows, 138 rows)
-- in a BEFORE trigger at write time is nearly free, so there's nothing to keep in sync.
-- source_system is the ONE exception — a BEFORE trigger cannot change a partitioned table's
-- partition-key value (Postgres has already committed to a partition before the trigger runs),
-- so the caller must supply source_system directly on INSERT. NOT NULL enforces this loudly
-- instead of silently routing unset rows into the default partition.
CREATE TABLE geochem.analytical_results (
    result_id             bigint GENERATED ALWAYS AS IDENTITY,
    sample_id                bigint NOT NULL REFERENCES geochem.samples(sample_id),
    occurrence_id                integer REFERENCES core.occurrences(occurrence_id),  -- denormalized down from sample_id's occurrence at write time — saves a join hop on every "results for occurrence X" query
    source_system                   varchar(50) NOT NULL,  -- denormalized from samples.source_system — supplied by the caller, see note above; THE partition key
    package_id                        integer REFERENCES geochem.analytical_packages(package_id),
    analyte_id                          integer NOT NULL REFERENCES geochem.analytes(analyte_id),
    analyte_name                          text,   -- resolved from analyte_id
    analyte_symbol                          text,   -- resolved from analyte_id
    unit_id                                   integer NOT NULL REFERENCES geochem.units(unit_id),
    unit_code                                   text,   -- resolved from unit_id
    qualifier_id                                  integer REFERENCES geochem.qualifiers(qualifier_id),
    qualifier_code                                  text,   -- resolved from qualifier_id
    laboratory                                        text,   -- resolved from package_id -> analytical_packages.lab_id -> laboratories.lab_name
    method_code                                         text,   -- resolved from package_id -> analytical_packages.method_id -> analytical_methods.method_code
    method_name                                           text,   -- resolved from the same path -> analytical_methods.method_name
    digest_name                                             text,   -- resolved from the same path -> analytical_methods.digest_name
    value                                                     numeric,
    lower_detection_limit                                      numeric,
    upper_detection_limit                                        numeric,
    report_number                                                  varchar(100),
    date_analysed                                                    date,   -- plain column + index now, NOT the partition key; nullable (85% of bronze has no date)
    reviewed                                                           boolean NOT NULL DEFAULT false,
    is_active                                                            boolean NOT NULL DEFAULT true,
    created_by                                                             varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (result_id, source_system)
) PARTITION BY LIST (source_system);

CREATE TABLE geochem.analytical_results_argentina_segemar PARTITION OF geochem.analytical_results FOR VALUES IN ('ARGENTINA_SEGEMAR');
CREATE TABLE geochem.analytical_results_other             PARTITION OF geochem.analytical_results DEFAULT;  -- future migrated regions get carved out one at a time as they're loaded

CREATE INDEX idx_ar_sample        ON geochem.analytical_results(sample_id);
CREATE INDEX idx_ar_occurrence    ON geochem.analytical_results(occurrence_id);
CREATE INDEX idx_ar_analyte       ON geochem.analytical_results(analyte_id);
CREATE INDEX idx_ar_analyte_name  ON geochem.analytical_results(analyte_name);
CREATE INDEX idx_ar_laboratory    ON geochem.analytical_results(laboratory);
CREATE INDEX idx_ar_method_code   ON geochem.analytical_results(method_code);
CREATE INDEX idx_ar_date_analysed ON geochem.analytical_results(date_analysed);

-- Populates every resolved column above from the FKs on THIS row, at write time (EXCEPT
-- source_system, see note above — that must be supplied directly on INSERT). Scalar lookups
-- against tiny reference tables — cheap even at high insert volume, unlike joining the full 38M+
-- row fact table against these lookups at read time.
CREATE OR REPLACE FUNCTION geochem.resolve_analytical_result_labels() RETURNS trigger AS $$
BEGIN
    SELECT analyte_name, element_symbol INTO NEW.analyte_name, NEW.analyte_symbol
    FROM geochem.analytes WHERE analyte_id = NEW.analyte_id;

    SELECT unit_code INTO NEW.unit_code
    FROM geochem.units WHERE unit_id = NEW.unit_id;

    IF NEW.qualifier_id IS NOT NULL THEN
        SELECT qualifier_code INTO NEW.qualifier_code
        FROM geochem.qualifiers WHERE qualifier_id = NEW.qualifier_id;
    END IF;

    IF NEW.package_id IS NOT NULL THEN
        SELECT l.lab_name, m.method_code, m.method_name, m.digest_name
        INTO NEW.laboratory, NEW.method_code, NEW.method_name, NEW.digest_name
        FROM geochem.analytical_packages p
        JOIN geochem.laboratories l ON l.lab_id = p.lab_id
        LEFT JOIN geochem.analytical_methods m ON m.method_id = p.method_id
        WHERE p.package_id = NEW.package_id;
    END IF;

    -- occurrence_id IS a plain (non-partition-key) column, so trigger resolution still works fine here
    NEW.occurrence_id := geochem.effective_occurrence_id(NULL, NEW.sample_id, NULL);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resolve_analytical_result_labels
    BEFORE INSERT OR UPDATE ON geochem.analytical_results
    FOR EACH ROW EXECUTE FUNCTION geochem.resolve_analytical_result_labels();

-- result_classifications: partitioned identically to analytical_results (by source_system) so
-- Postgres can do a partition-wise join between the two instead of scanning the whole fact table.
CREATE TABLE geochem.result_classifications (
    result_id              bigint NOT NULL,
    source_system              varchar(50),
    result_status                 varchar(30) NOT NULL,
    dl_value                        numeric,
    dl_source                         varchar(100),
    use_in_statistics                   boolean NOT NULL DEFAULT true,
    -- (classified_at / classified_by were dropped 2026-10-12; history lives in geochem.classification_batches)
    UNIQUE (result_id, source_system),
    FOREIGN KEY (result_id, source_system) REFERENCES geochem.analytical_results(result_id, source_system)
) PARTITION BY LIST (source_system);

CREATE TABLE geochem.result_classifications_argentina_segemar PARTITION OF geochem.result_classifications FOR VALUES IN ('ARGENTINA_SEGEMAR');
CREATE TABLE geochem.result_classifications_other             PARTITION OF geochem.result_classifications DEFAULT;

-- occurrence_mineralogy / occurrence_endowment: was deposit_mineralogy / deposit_endowment,
-- re-keyed to occurrence_id.
CREATE TABLE geochem.occurrence_mineralogy (
    occurrence_mineralogy_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id                   integer NOT NULL REFERENCES core.occurrences(occurrence_id),
    mineral_id                         integer,   -- REFERENCES geochem.minerals(mineral_id), see note below
    mineral_name_local                    varchar(150) NOT NULL,
    mineral_role                             varchar(150),  -- widened from varchar(50) during Argentina migration: bronze has values up to 116 chars
    mineral_zone                               varchar(100),
    role_raw                                     varchar(250),  -- widened from varchar(100): bronze has values up to 232 chars
    is_active                                      boolean NOT NULL DEFAULT true,
    created_by                                      varchar(100) NOT NULL DEFAULT current_user,
    created_date                                     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_occ_mineralogy_occurrence ON geochem.occurrence_mineralogy(occurrence_id);

CREATE TABLE geochem.minerals (
    mineral_id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mindat_id                 integer,
    mineral_name                 varchar(150) NOT NULL,
    ima_formula                     varchar(200),
    ima_abbreviation                   varchar(20),
    ima_status                            varchar(50),
    strunz_code                              varchar(30),
    strunz_class                                varchar(150),
    strunz_subclass                                varchar(150),
    strunz_family                                     varchar(150),
    strunz_group                                         varchar(150),
    dana_class                                              varchar(150),
    dana_type                                                  varchar(150),
    crystal_system                                                varchar(50),
    description                                                      text,
    mindat_updated                                                      date,
    is_active                                                             boolean NOT NULL DEFAULT true,
    created_by                                                             varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                             timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE geochem.occurrence_mineralogy
    ADD CONSTRAINT fk_occ_mineralogy_mineral FOREIGN KEY (mineral_id) REFERENCES geochem.minerals(mineral_id);

CREATE TABLE geochem.occurrence_endowment (
    occurrence_endowment_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id                   integer NOT NULL REFERENCES core.occurrences(occurrence_id),
    commodity_id                       integer REFERENCES core.commodities(commodity_id),
    commodity_raw                         varchar(100) NOT NULL,
    data_type                                varchar(30) NOT NULL,   -- PRODUCTION / RESOURCE
    measure                                    varchar(50) NOT NULL,
    value_num                                    numeric,
    value_text                                     varchar(200),
    unit                                             varchar(50),
    seq                                                integer NOT NULL,
    source                                               varchar(200) NOT NULL,
    is_active                                              boolean NOT NULL DEFAULT true,
    created_by                                              varchar(100) NOT NULL DEFAULT current_user,
    created_date                                              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_occ_endowment_occurrence ON geochem.occurrence_endowment(occurrence_id);

-- lithology_observations / age_measured / age_stratigraphic: reference whichever parent
-- feature the observation was logged against (sampling_line, sample, or occurrence directly).
CREATE TABLE geochem.lithology_observations (
    lithology_observation_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lithology_id                     integer NOT NULL REFERENCES geochem.lithology(lithology_id),
    lithology_local                     varchar(250),  -- widened from varchar(150) during Argentina migration: bronze has values up to 177 chars
    observation_context                    varchar(50) NOT NULL,
    sampling_line_id                          bigint REFERENCES geochem.sampling_lines(sampling_line_id),
    sample_id                                    bigint REFERENCES geochem.samples(sample_id),
    occurrence_id                                   integer REFERENCES core.occurrences(occurrence_id),
    depth_from_m                                       numeric,
    depth_to_m                                            numeric,
    logged_by                                                varchar(100),
    logged_date                                                 date,
    strat_group                                                    varchar(150),
    strat_formation                                                   varchar(150),
    strat_member                                                         varchar(150),
    strat_bed                                                               varchar(150),
    alteration_id                                                             integer REFERENCES geochem.alteration_reference(alteration_id),
    alteration_local                                                             varchar(150),
    comments                                                                        text,
    is_active                                                                         boolean NOT NULL DEFAULT true,
    created_by                                                                          varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                                          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_lithology_observations_parent CHECK (occurrence_id IS NOT NULL OR sample_id IS NOT NULL OR sampling_line_id IS NOT NULL)
);
CREATE INDEX idx_lith_obs_sampling_line ON geochem.lithology_observations(sampling_line_id);
CREATE INDEX idx_lith_obs_sample ON geochem.lithology_observations(sample_id);
CREATE INDEX idx_lith_obs_occurrence ON geochem.lithology_observations(occurrence_id);

CREATE TABLE geochem.age_measured (
    age_measured_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dating_method_id                integer NOT NULL REFERENCES geochem.dating_method_reference(dating_method_id),
    observation_context                 varchar(50) NOT NULL,
    sampling_line_id                       bigint REFERENCES geochem.sampling_lines(sampling_line_id),
    sample_id                                 bigint REFERENCES geochem.samples(sample_id),
    occurrence_id                                integer REFERENCES core.occurrences(occurrence_id),
    depth_from_m                                    numeric,
    depth_to_m                                         numeric,
    age_ma                                                numeric NOT NULL,
    age_error_ma                                            numeric,
    age_error_percent                                          numeric,
    age_unit                                                     varchar(20) NOT NULL DEFAULT 'Ma',
    lab_sample_id                                                  varchar(100),
    laboratory                                                        varchar(200),
    instrument_id                                                        integer REFERENCES geochem.dating_instruments(instrument_id),
    analysis_date                                                           date,
    material_dated                                                             varchar(150),
    mineral_id                                                                    integer REFERENCES geochem.minerals(mineral_id),
    mswd                                                                            numeric,
    probability                                                                        numeric,
    n_analyses                                                                            integer,
    n_grains                                                                                 integer,
    age_type_id                                                                                integer REFERENCES geochem.age_type_reference(age_type_id),
    age_interpretation                                                                            text,
    age_quality                                                                                     varchar(50),
    age_reference_id                                                                                   integer REFERENCES geochem.age_reference(age_reference_id),
    dated_by                                                                                              varchar(100),
    interpreted_by                                                                                          varchar(100),
    comments                                                                                                   text,
    is_active                                                                                                    boolean NOT NULL DEFAULT true,
    created_by                                                                                                     varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                                                                    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_age_measured_parent CHECK (occurrence_id IS NOT NULL OR sample_id IS NOT NULL OR sampling_line_id IS NOT NULL)
);
CREATE INDEX idx_age_measured_occurrence ON geochem.age_measured(occurrence_id);
CREATE INDEX idx_age_measured_sample ON geochem.age_measured(sample_id);

CREATE TABLE geochem.age_stratigraphic (
    age_stratigraphic_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stratigraphic_age_id              integer NOT NULL REFERENCES geochem.stratigraphic_age_reference(stratigraphic_age_id),
    age_local                            varchar(150),  -- widened from varchar(100) during Argentina migration: bronze has values up to 115 chars
    observation_context                     varchar(50) NOT NULL,
    sampling_line_id                           bigint REFERENCES geochem.sampling_lines(sampling_line_id),
    sample_id                                     bigint REFERENCES geochem.samples(sample_id),
    occurrence_id                                    integer REFERENCES core.occurrences(occurrence_id),
    depth_from_m                                        numeric,
    depth_to_m                                             numeric,
    confidence_level                                          varchar(50),
    determination_method                                         varchar(100),
    fossil_taxa                                                     text,
    reported_age_raw                                                   text,
    age_reference_id                                                      integer REFERENCES geochem.age_reference(age_reference_id),
    logged_by                                                                varchar(100),
    logged_date                                                                 date,
    comments                                                                       text,
    is_active                                                                        boolean NOT NULL DEFAULT true,
    created_by                                                                        varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                                        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_age_stratigraphic_parent CHECK (occurrence_id IS NOT NULL OR sample_id IS NOT NULL OR sampling_line_id IS NOT NULL)
);
CREATE INDEX idx_age_strat_occurrence ON geochem.age_stratigraphic(occurrence_id);
CREATE INDEX idx_age_strat_sample ON geochem.age_stratigraphic(sample_id);

CREATE TABLE geochem.lineament_types (
    lineament_type_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type_code             varchar(20) NOT NULL UNIQUE,
    type_name               varchar(150) NOT NULL,
    description               text,
    is_active                   boolean NOT NULL DEFAULT true,
    created_by                   varchar(100) NOT NULL DEFAULT current_user,
    created_date                   timestamptz NOT NULL DEFAULT now()
);

-- Purely spatial relationship to occurrences/samples/everything else — no occurrence_id FK.
-- Several occurrences can sit along the same regional structure, so it's a many-to-many-by-
-- proximity relationship, not ownership. geog (generated from geom, same pattern as
-- occurrences/samples) is what makes cross-schema spatial joins ("occurrences within 2km of
-- this fault") cheap and index-backed. bronze's `estructuras` (Argentina-only, Spanish columns)
-- is the untransformed source this migrates from — same row count (2,864) as bronze's
-- `lineaments` strongly suggests it already IS the source, not a separate entity; folded into
-- the migration mapping rather than given its own gold table.
CREATE TABLE geochem.lineaments (
    lineament_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lineament_code           varchar(50),
    name                        text,
    lineament_type_id             integer REFERENCES geochem.lineament_types(lineament_type_id),
    jurisdiction_id                  integer REFERENCES core.jurisdictions(jurisdiction_id),
    geom                                geometry(LineString, 4326) NOT NULL,
    geog                                  geography(LineString, 4326) GENERATED ALWAYS AS (geom::geography) STORED,
    length_km                              numeric,
    strike_degrees                           numeric,
    dip_degrees                                numeric,
    dip_direction                                varchar(20),
    confidence_level                               varchar(50),
    interpretation_method                            varchar(100),
    source_system                                      varchar(50),
    datasource_url                                       text,
    external_id                                            varchar(200),
    comments                                                 text,
    is_active                                                  boolean NOT NULL DEFAULT true,
    created_by                                                   varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                   timestamptz NOT NULL DEFAULT now(),
    modified_by                                                      varchar(100),
    modified_date                                                      timestamptz
);
CREATE INDEX idx_lineaments_geom         ON geochem.lineaments USING gist(geom);
CREATE INDEX idx_lineaments_geog         ON geochem.lineaments USING gist(geog);
CREATE INDEX idx_lineaments_type         ON geochem.lineaments(lineament_type_id);
CREATE INDEX idx_lineaments_jurisdiction ON geochem.lineaments(jurisdiction_id);
CREATE INDEX idx_lineaments_source       ON geochem.lineaments(source_system);

CREATE TABLE geochem.lineament_ages (
    lineament_age_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lineament_id              bigint NOT NULL REFERENCES geochem.lineaments(lineament_id),
    stratigraphic_age_id         integer REFERENCES geochem.stratigraphic_age_reference(stratigraphic_age_id),
    age_local                       varchar(100),
    age_context                       varchar(100),
    comments                             text,
    is_active                              boolean NOT NULL DEFAULT true,
    created_by                              varchar(100) NOT NULL DEFAULT current_user,
    created_date                              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_lineament_ages_lineament ON geochem.lineament_ages(lineament_id);

-- ----------------------------------------------------------------------------
-- core.geology_summary refresh mechanism. Full recompute per affected occurrence on any
-- change to lithology_observations / age_measured / occurrence_mineralogy — not incrementally
-- maintained, since "dominant" values via running counts is fiddly to get right and this table
-- is occurrence-scoped (thousands of rows), so a full recompute per change is cheap.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.refresh_geology_summary(p_occurrence_id integer) RETURNS void AS $$
DECLARE
    v_dominant_lithology         text;
    v_dominant_alteration        text;
    v_dominant_mineral           text;
    v_dominant_formation         text;
    v_dominant_stratigraphic_age text;
    v_primary_age_ma             numeric;
    v_primary_age_method         text;
    v_observations               jsonb;
BEGIN
    IF p_occurrence_id IS NULL THEN
        RETURN;
    END IF;

    SELECT l.lithology_name INTO v_dominant_lithology
    FROM geochem.lithology_observations lo
    JOIN geochem.lithology l ON l.lithology_id = lo.lithology_id
    WHERE geochem.effective_occurrence_id(lo.occurrence_id, lo.sample_id, lo.sampling_line_id) = p_occurrence_id
      AND lo.is_active
    GROUP BY l.lithology_name
    ORDER BY count(*) DESC, l.lithology_name
    LIMIT 1;

    SELECT ar.alteration_type INTO v_dominant_alteration
    FROM geochem.lithology_observations lo
    JOIN geochem.alteration_reference ar ON ar.alteration_id = lo.alteration_id
    WHERE geochem.effective_occurrence_id(lo.occurrence_id, lo.sample_id, lo.sampling_line_id) = p_occurrence_id
      AND lo.is_active AND lo.alteration_id IS NOT NULL
    GROUP BY ar.alteration_type
    ORDER BY count(*) DESC, ar.alteration_type
    LIMIT 1;

    SELECT lo.strat_formation INTO v_dominant_formation
    FROM geochem.lithology_observations lo
    WHERE geochem.effective_occurrence_id(lo.occurrence_id, lo.sample_id, lo.sampling_line_id) = p_occurrence_id
      AND lo.is_active AND lo.strat_formation IS NOT NULL
    GROUP BY lo.strat_formation
    ORDER BY count(*) DESC, lo.strat_formation
    LIMIT 1;

    SELECT sar.age_name INTO v_dominant_stratigraphic_age
    FROM geochem.age_stratigraphic ast
    JOIN geochem.stratigraphic_age_reference sar ON sar.stratigraphic_age_id = ast.stratigraphic_age_id
    WHERE geochem.effective_occurrence_id(ast.occurrence_id, ast.sample_id, ast.sampling_line_id) = p_occurrence_id
      AND ast.is_active
    GROUP BY sar.age_name
    ORDER BY count(*) DESC, sar.age_name
    LIMIT 1;

    -- precision-based rule: lowest error % wins, then most analyses, then most recent.
    -- No "explicitly tagged as primary/mineralization" tier yet — age_type_reference has no
    -- loaded data to know what values it will actually contain. Add that tier once it does.
    SELECT am.age_ma, dmr.method_name
    INTO v_primary_age_ma, v_primary_age_method
    FROM geochem.age_measured am
    JOIN geochem.dating_method_reference dmr ON dmr.dating_method_id = am.dating_method_id
    WHERE geochem.effective_occurrence_id(am.occurrence_id, am.sample_id, am.sampling_line_id) = p_occurrence_id
      AND am.is_active
    ORDER BY
        COALESCE(am.age_error_percent,
                 CASE WHEN am.age_ma <> 0 THEN am.age_error_ma / am.age_ma * 100 END) ASC NULLS LAST,
        am.n_analyses DESC NULLS LAST,
        am.analysis_date DESC NULLS LAST
    LIMIT 1;

    -- prefer a mineral explicitly tagged primary/ore; fall back to the most-observed mineral overall
    SELECT COALESCE(m.mineral_name, om.mineral_name_local) INTO v_dominant_mineral
    FROM geochem.occurrence_mineralogy om
    LEFT JOIN geochem.minerals m ON m.mineral_id = om.mineral_id
    WHERE om.occurrence_id = p_occurrence_id AND om.is_active
      AND (om.mineral_role ILIKE 'primary%' OR om.mineral_role ILIKE 'ore%')
    GROUP BY COALESCE(m.mineral_name, om.mineral_name_local)
    ORDER BY count(*) DESC, COALESCE(m.mineral_name, om.mineral_name_local)
    LIMIT 1;

    IF v_dominant_mineral IS NULL THEN
        SELECT COALESCE(m.mineral_name, om.mineral_name_local) INTO v_dominant_mineral
        FROM geochem.occurrence_mineralogy om
        LEFT JOIN geochem.minerals m ON m.mineral_id = om.mineral_id
        WHERE om.occurrence_id = p_occurrence_id AND om.is_active
        GROUP BY COALESCE(m.mineral_name, om.mineral_name_local)
        ORDER BY count(*) DESC, COALESCE(m.mineral_name, om.mineral_name_local)
        LIMIT 1;
    END IF;

    SELECT COALESCE(jsonb_agg(entry), '[]'::jsonb) INTO v_observations
    FROM (
        SELECT jsonb_build_object('type','lithology','name',l.lithology_name,
                                   'depth_from',lo.depth_from_m,'depth_to',lo.depth_to_m,
                                   'strat_group',lo.strat_group,'strat_formation',lo.strat_formation,
                                   'strat_member',lo.strat_member,'strat_bed',lo.strat_bed) AS entry
        FROM geochem.lithology_observations lo
        JOIN geochem.lithology l ON l.lithology_id = lo.lithology_id
        WHERE geochem.effective_occurrence_id(lo.occurrence_id, lo.sample_id, lo.sampling_line_id) = p_occurrence_id
          AND lo.is_active
        UNION ALL
        SELECT jsonb_build_object('type','alteration','name',ar.alteration_type,
                                   'depth_from',lo.depth_from_m,'depth_to',lo.depth_to_m)
        FROM geochem.lithology_observations lo
        JOIN geochem.alteration_reference ar ON ar.alteration_id = lo.alteration_id
        WHERE geochem.effective_occurrence_id(lo.occurrence_id, lo.sample_id, lo.sampling_line_id) = p_occurrence_id
          AND lo.is_active AND lo.alteration_id IS NOT NULL
        UNION ALL
        SELECT jsonb_build_object('type','age','age_ma',am.age_ma,'method',dmr.method_name,
                                   'error_pct',am.age_error_percent,'n_analyses',am.n_analyses)
        FROM geochem.age_measured am
        JOIN geochem.dating_method_reference dmr ON dmr.dating_method_id = am.dating_method_id
        WHERE geochem.effective_occurrence_id(am.occurrence_id, am.sample_id, am.sampling_line_id) = p_occurrence_id
          AND am.is_active
        UNION ALL
        SELECT jsonb_build_object('type','stratigraphic_age','name',sar.age_name,
                                   'age_start_ma',sar.age_start_ma,'age_end_ma',sar.age_end_ma,
                                   'confidence',ast.confidence_level)
        FROM geochem.age_stratigraphic ast
        JOIN geochem.stratigraphic_age_reference sar ON sar.stratigraphic_age_id = ast.stratigraphic_age_id
        WHERE geochem.effective_occurrence_id(ast.occurrence_id, ast.sample_id, ast.sampling_line_id) = p_occurrence_id
          AND ast.is_active
        UNION ALL
        SELECT jsonb_build_object('type','mineral','name',COALESCE(m.mineral_name, om.mineral_name_local),
                                   'role',om.mineral_role,'zone',om.mineral_zone)
        FROM geochem.occurrence_mineralogy om
        LEFT JOIN geochem.minerals m ON m.mineral_id = om.mineral_id
        WHERE om.occurrence_id = p_occurrence_id AND om.is_active
    ) sub;

    IF v_observations = '[]'::jsonb AND v_dominant_lithology IS NULL AND v_dominant_alteration IS NULL
       AND v_dominant_mineral IS NULL AND v_dominant_formation IS NULL AND v_dominant_stratigraphic_age IS NULL
       AND v_primary_age_ma IS NULL THEN
        DELETE FROM core.geology_summary WHERE occurrence_id = p_occurrence_id;
        RETURN;
    END IF;

    INSERT INTO core.geology_summary (occurrence_id, dominant_lithology, dominant_alteration, dominant_mineral,
                                       dominant_formation, dominant_stratigraphic_age, primary_age_ma,
                                       primary_age_method, observations, updated_at)
    VALUES (p_occurrence_id, v_dominant_lithology, v_dominant_alteration, v_dominant_mineral,
            v_dominant_formation, v_dominant_stratigraphic_age, v_primary_age_ma, v_primary_age_method,
            v_observations, now())
    ON CONFLICT (occurrence_id) DO UPDATE SET
        dominant_lithology         = EXCLUDED.dominant_lithology,
        dominant_alteration        = EXCLUDED.dominant_alteration,
        dominant_mineral           = EXCLUDED.dominant_mineral,
        dominant_formation         = EXCLUDED.dominant_formation,
        dominant_stratigraphic_age = EXCLUDED.dominant_stratigraphic_age,
        primary_age_ma              = EXCLUDED.primary_age_ma,
        primary_age_method           = EXCLUDED.primary_age_method,
        observations                   = EXCLUDED.observations,
        updated_at                      = now();
END;
$$ LANGUAGE plpgsql;

-- lithology_observations and age_measured share the same (occurrence_id, sample_id,
-- sampling_line_id) shape, so one trigger function serves both.
CREATE OR REPLACE FUNCTION geochem.trg_geology_summary_refresh() RETURNS trigger AS $$
DECLARE
    old_occ integer;
    new_occ integer;
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN
        old_occ := geochem.effective_occurrence_id(OLD.occurrence_id, OLD.sample_id, OLD.sampling_line_id);
    END IF;
    IF TG_OP IN ('INSERT','UPDATE') THEN
        new_occ := geochem.effective_occurrence_id(NEW.occurrence_id, NEW.sample_id, NEW.sampling_line_id);
    END IF;

    PERFORM core.refresh_geology_summary(new_occ);
    IF old_occ IS DISTINCT FROM new_occ THEN
        PERFORM core.refresh_geology_summary(old_occ);
    END IF;

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_lithology_observations_geology_summary
    AFTER INSERT OR UPDATE OR DELETE ON geochem.lithology_observations
    FOR EACH ROW EXECUTE FUNCTION geochem.trg_geology_summary_refresh();

CREATE TRIGGER trg_age_measured_geology_summary
    AFTER INSERT OR UPDATE OR DELETE ON geochem.age_measured
    FOR EACH ROW EXECUTE FUNCTION geochem.trg_geology_summary_refresh();

-- age_stratigraphic has the identical (occurrence_id, sample_id, sampling_line_id) shape too —
-- same shared trigger function.
CREATE TRIGGER trg_age_stratigraphic_geology_summary
    AFTER INSERT OR UPDATE OR DELETE ON geochem.age_stratigraphic
    FOR EACH ROW EXECUTE FUNCTION geochem.trg_geology_summary_refresh();

-- occurrence_mineralogy has occurrence_id directly (NOT NULL) — no resolution chain needed.
CREATE OR REPLACE FUNCTION geochem.trg_geology_summary_from_mineralogy() RETURNS trigger AS $$
BEGIN
    PERFORM core.refresh_geology_summary(COALESCE(NEW.occurrence_id, OLD.occurrence_id));
    IF TG_OP = 'UPDATE' AND NEW.occurrence_id IS DISTINCT FROM OLD.occurrence_id THEN
        PERFORM core.refresh_geology_summary(OLD.occurrence_id);
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_occurrence_mineralogy_geology_summary
    AFTER INSERT OR UPDATE OR DELETE ON geochem.occurrence_mineralogy
    FOR EACH ROW EXECUTE FUNCTION geochem.trg_geology_summary_from_mineralogy();

-- ============================================================================
-- 5. DOCS
-- ============================================================================

CREATE TABLE docs.documents (
    document_id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title                        text NOT NULL,
    domain                          varchar(30) NOT NULL CHECK (domain IN
                                       ('POLICY','SUPPLY_CHAIN','TECHNOLOGY','TECHNICAL_REPORT','ANNUAL_REPORT','RESEARCH','NEWS')),
    document_type                       varchar(50),
    company_id                             integer REFERENCES core.companies(company_id),
    project_id                                integer REFERENCES core.projects(project_id),
    occurrence_id                                integer REFERENCES core.occurrences(occurrence_id),
    commodity_id                                    integer REFERENCES core.commodities(commodity_id),
    jurisdiction_id                                    integer REFERENCES core.jurisdictions(jurisdiction_id),
    publication_date                                      date,
    source_url                                               text,
    file_path                                                  text,
    page_count                                                   integer,
    language                                                       varchar(10) DEFAULT 'en',
    is_active                                                        boolean NOT NULL DEFAULT true,
    created_by                                                        varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_documents_domain ON docs.documents(domain);
CREATE INDEX idx_documents_company ON docs.documents(company_id);
CREATE INDEX idx_documents_project ON docs.documents(project_id);
CREATE INDEX idx_documents_occurrence ON docs.documents(occurrence_id);
CREATE INDEX idx_documents_jurisdiction ON docs.documents(jurisdiction_id);

-- embedding model CONFIRMED 2026-09-24: voyage-3-large, one model for every domain, 1024
-- dimensions — verified directly against bronze's existing embedding data (criticialmineralsexp
-- .chunks and .financial_chunks, both consistently 1024-dim via vector_dims()), not just assumed.
-- company_id/project_id/occurrence_id/commodity_id/jurisdiction_id are denormalized down from
-- the parent document (same collapse pattern as analytical_results' resolved columns) so a
-- filtered vector search — "chunks about THIS occurrence, ranked by similarity" — is one table,
-- one WHERE clause, no join through documents first. This is what makes cross-domain RAG
-- (structured SQL join + entity-scoped vector search over the same occurrence/company) cheap.
CREATE TABLE docs.document_chunks (
    chunk_id                bigint GENERATED ALWAYS AS IDENTITY,
    document_id                 bigint NOT NULL REFERENCES docs.documents(document_id),
    domain                          varchar(30) NOT NULL,
    company_id                         integer REFERENCES core.companies(company_id),
    project_id                            integer REFERENCES core.projects(project_id),
    occurrence_id                            integer REFERENCES core.occurrences(occurrence_id),
    commodity_id                                integer REFERENCES core.commodities(commodity_id),
    jurisdiction_id                                integer REFERENCES core.jurisdictions(jurisdiction_id),
    chunk_index                        integer NOT NULL,
    page_number                           integer,
    section_heading                          text,
    section_type                                varchar(30) NOT NULL DEFAULT 'BODY'
                                                   CHECK (section_type IN ('BODY','DISCLAIMER','TABLE_OF_CONTENTS','GLOSSARY','APPENDIX','LEGAL','REFERENCES','HEADER_FOOTER','OTHER')),
    content                                     text NOT NULL,
    token_count                                    integer,
    embedding                                        vector(1024),
    embedding_model                                    varchar(100),  -- e.g. 'voyage-3-large' — know which model produced this vector before ever mixing models in one index
    embedding_version                                    varchar(50),
    created_date                                       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, domain),
    UNIQUE (document_id, chunk_index, domain)  -- domain included only because a partitioned table's unique constraints must include the partition key
) PARTITION BY LIST (domain);

CREATE TABLE docs.document_chunks_policy            PARTITION OF docs.document_chunks FOR VALUES IN ('POLICY');
CREATE TABLE docs.document_chunks_supply_chain      PARTITION OF docs.document_chunks FOR VALUES IN ('SUPPLY_CHAIN');
CREATE TABLE docs.document_chunks_technology        PARTITION OF docs.document_chunks FOR VALUES IN ('TECHNOLOGY');
CREATE TABLE docs.document_chunks_technical_report  PARTITION OF docs.document_chunks FOR VALUES IN ('TECHNICAL_REPORT');
CREATE TABLE docs.document_chunks_annual_report     PARTITION OF docs.document_chunks FOR VALUES IN ('ANNUAL_REPORT');  -- added 2026-09-26, RAG ingestion pilot
CREATE TABLE docs.document_chunks_research          PARTITION OF docs.document_chunks FOR VALUES IN ('RESEARCH');       -- added 2026-09-26, RAG ingestion pilot
CREATE TABLE docs.document_chunks_other             PARTITION OF docs.document_chunks DEFAULT;

CREATE INDEX idx_chunks_policy_doc            ON docs.document_chunks_policy(document_id);
CREATE INDEX idx_chunks_supply_chain_doc      ON docs.document_chunks_supply_chain(document_id);
CREATE INDEX idx_chunks_technology_doc        ON docs.document_chunks_technology(document_id);
CREATE INDEX idx_chunks_technical_report_doc  ON docs.document_chunks_technical_report(document_id);
CREATE INDEX idx_chunks_annual_report_doc     ON docs.document_chunks_annual_report(document_id);
CREATE INDEX idx_chunks_research_doc          ON docs.document_chunks_research(document_id);
CREATE INDEX idx_chunks_other_doc             ON docs.document_chunks_other(document_id);

CREATE INDEX idx_chunks_policy_fts            ON docs.document_chunks_policy           USING gin (to_tsvector('english', content));
CREATE INDEX idx_chunks_supply_chain_fts      ON docs.document_chunks_supply_chain     USING gin (to_tsvector('english', content));
CREATE INDEX idx_chunks_technology_fts        ON docs.document_chunks_technology       USING gin (to_tsvector('english', content));
CREATE INDEX idx_chunks_technical_report_fts  ON docs.document_chunks_technical_report USING gin (to_tsvector('english', content));
CREATE INDEX idx_chunks_annual_report_fts     ON docs.document_chunks_annual_report    USING gin (to_tsvector('english', content));
CREATE INDEX idx_chunks_research_fts          ON docs.document_chunks_research         USING gin (to_tsvector('english', content));
CREATE INDEX idx_chunks_other_fts             ON docs.document_chunks_other            USING gin (to_tsvector('english', content));

CREATE INDEX idx_chunks_policy_section_type            ON docs.document_chunks_policy(section_type);
CREATE INDEX idx_chunks_supply_chain_section_type      ON docs.document_chunks_supply_chain(section_type);
CREATE INDEX idx_chunks_technology_section_type        ON docs.document_chunks_technology(section_type);
CREATE INDEX idx_chunks_technical_report_section_type  ON docs.document_chunks_technical_report(section_type);
CREATE INDEX idx_chunks_annual_report_section_type     ON docs.document_chunks_annual_report(section_type);
CREATE INDEX idx_chunks_research_section_type          ON docs.document_chunks_research(section_type);
CREATE INDEX idx_chunks_other_section_type             ON docs.document_chunks_other(section_type);

-- created on the parent partitioned table — Postgres auto-applies to every existing partition
-- AND any future one, unlike the per-partition indexes above (which predate this being noticed).
CREATE INDEX idx_chunks_company      ON docs.document_chunks(company_id);
CREATE INDEX idx_chunks_project      ON docs.document_chunks(project_id);
CREATE INDEX idx_chunks_occurrence   ON docs.document_chunks(occurrence_id);
CREATE INDEX idx_chunks_commodity    ON docs.document_chunks(commodity_id);
CREATE INDEX idx_chunks_jurisdiction ON docs.document_chunks(jurisdiction_id);

CREATE OR REPLACE FUNCTION docs.resolve_chunk_entity_fks() RETURNS trigger AS $$
BEGIN
    SELECT d.company_id, d.project_id, d.occurrence_id, d.commodity_id, d.jurisdiction_id
    INTO NEW.company_id, NEW.project_id, NEW.occurrence_id, NEW.commodity_id, NEW.jurisdiction_id
    FROM docs.documents d WHERE d.document_id = NEW.document_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resolve_chunk_entity_fks
    BEFORE INSERT OR UPDATE OF document_id ON docs.document_chunks
    FOR EACH ROW EXECUTE FUNCTION docs.resolve_chunk_entity_fks();

-- HNSW embedding indexes deferred to 07_post_load.sql — build these AFTER the embedding
-- dimension is confirmed and (ideally) after a first batch of real vectors is loaded, since
-- HNSW build time/quality depends on actual data density.

-- ----------------------------------------------------------------------------
-- docs.hybrid_search: Reciprocal Rank Fusion (RRF) of vector + full-text search, filtered by
-- entity/domain/section_type BEFORE either search runs (not after) — a chunk excluded on
-- section_type never enters either candidate set, regardless of how well it would have scored.
-- RRF (score = sum of 1/(60+rank) per method) rather than blending raw scores directly: cosine
-- similarity and ts_rank live on incomparable scales, but ranks are always comparable, so RRF is
-- robust without per-corpus score-weight tuning. Returns a fused top-K candidate set — an
-- optional cross-encoder/LLM reranking pass on top of that belongs in the calling application,
-- not in SQL. Smoke-tested: a chunk identical to the query on BOTH text and vector but tagged
-- DISCLAIMER was correctly excluded entirely; a chunk strong only on vector and a chunk strong
-- only on text tied for first place; a chunk matching neither ranked last.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION docs.hybrid_search(
    p_query_text            text,
    p_query_embedding       vector(1024),
    p_domain                varchar(30)  DEFAULT NULL,
    p_occurrence_id         integer      DEFAULT NULL,
    p_company_id            integer      DEFAULT NULL,
    p_project_id            integer      DEFAULT NULL,
    p_commodity_id          integer      DEFAULT NULL,
    p_jurisdiction_id       integer      DEFAULT NULL,
    p_exclude_section_types varchar(30)[] DEFAULT ARRAY['DISCLAIMER','TABLE_OF_CONTENTS','GLOSSARY','LEGAL','HEADER_FOOTER'],
    p_candidate_limit       integer      DEFAULT 50,
    p_result_limit          integer      DEFAULT 10
) RETURNS TABLE (
    chunk_id       bigint,
    document_id    bigint,
    domain         varchar(30),
    content        text,
    section_heading text,
    page_number    integer,
    vector_rank    integer,
    text_rank      integer,
    rrf_score      numeric
) AS $$
    WITH vector_matches AS (
        SELECT dc.chunk_id, dc.domain,
               row_number() OVER (ORDER BY dc.embedding <=> p_query_embedding) AS vrank
        FROM docs.document_chunks dc
        WHERE p_query_embedding IS NOT NULL
          AND dc.embedding IS NOT NULL
          AND (p_domain IS NULL OR dc.domain = p_domain)
          AND (p_occurrence_id IS NULL OR dc.occurrence_id = p_occurrence_id)
          AND (p_company_id IS NULL OR dc.company_id = p_company_id)
          AND (p_project_id IS NULL OR dc.project_id = p_project_id)
          AND (p_commodity_id IS NULL OR dc.commodity_id = p_commodity_id)
          AND (p_jurisdiction_id IS NULL OR dc.jurisdiction_id = p_jurisdiction_id)
          AND dc.section_type <> ALL(p_exclude_section_types)
        ORDER BY dc.embedding <=> p_query_embedding
        LIMIT p_candidate_limit
    ),
    text_matches AS (
        SELECT dc.chunk_id, dc.domain,
               row_number() OVER (ORDER BY ts_rank_cd(to_tsvector('english', dc.content), plainto_tsquery('english', p_query_text)) DESC) AS trank
        FROM docs.document_chunks dc
        WHERE p_query_text IS NOT NULL AND trim(p_query_text) <> ''
          AND to_tsvector('english', dc.content) @@ plainto_tsquery('english', p_query_text)
          AND (p_domain IS NULL OR dc.domain = p_domain)
          AND (p_occurrence_id IS NULL OR dc.occurrence_id = p_occurrence_id)
          AND (p_company_id IS NULL OR dc.company_id = p_company_id)
          AND (p_project_id IS NULL OR dc.project_id = p_project_id)
          AND (p_commodity_id IS NULL OR dc.commodity_id = p_commodity_id)
          AND (p_jurisdiction_id IS NULL OR dc.jurisdiction_id = p_jurisdiction_id)
          AND dc.section_type <> ALL(p_exclude_section_types)
        ORDER BY ts_rank_cd(to_tsvector('english', dc.content), plainto_tsquery('english', p_query_text)) DESC
        LIMIT p_candidate_limit
    ),
    fused AS (
        SELECT COALESCE(v.chunk_id, t.chunk_id) AS chunk_id,
               COALESCE(v.domain, t.domain) AS domain,
               v.vrank AS vector_rank,
               t.trank AS text_rank,
               COALESCE(1.0 / (60 + v.vrank), 0) + COALESCE(1.0 / (60 + t.trank), 0) AS rrf_score
        FROM vector_matches v
        FULL OUTER JOIN text_matches t ON t.chunk_id = v.chunk_id AND t.domain = v.domain
    )
    SELECT dc.chunk_id, dc.document_id, dc.domain, dc.content, dc.section_heading, dc.page_number,
           f.vector_rank, f.text_rank, f.rrf_score
    FROM fused f
    JOIN docs.document_chunks dc ON dc.chunk_id = f.chunk_id AND dc.domain = f.domain
    ORDER BY f.rrf_score DESC
    LIMIT p_result_limit;
$$ LANGUAGE sql STABLE;

CREATE TABLE docs.extracted_facts (
    extracted_fact_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id                  bigint NOT NULL REFERENCES docs.documents(document_id),
    occurrence_id                    integer REFERENCES core.occurrences(occurrence_id),
    project_id                          integer REFERENCES core.projects(project_id),
    company_id                             integer REFERENCES core.companies(company_id),
    fact_type                                 varchar(50) NOT NULL,   -- PERMITTING_STATUS / CAPEX / OPEX / MINE_LIFE / ...
    fact_value_text                              text,
    fact_value_numeric                              numeric,
    fact_value_unit                                    varchar(30),
    fact_data                                             jsonb,
    extracted_at                                            timestamptz NOT NULL DEFAULT now(),
    extraction_confidence                                      varchar(20)
);
CREATE INDEX idx_extracted_facts_document ON docs.extracted_facts(document_id);
CREATE INDEX idx_extracted_facts_occurrence ON docs.extracted_facts(occurrence_id);
CREATE INDEX idx_extracted_facts_data ON docs.extracted_facts USING gin(fact_data);

-- ============================================================================
-- 6. FINANCIALS — company-consolidated only (confirmed)
-- ============================================================================

CREATE TABLE financials.balance_sheet (
    balance_sheet_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  integer NOT NULL REFERENCES core.companies(company_id),
    period_end_date                date NOT NULL,
    period_type                       varchar(2) NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','FY')),
    currency                             varchar(3) NOT NULL DEFAULT 'USD',
    total_assets                            numeric,
    total_current_assets                       numeric,
    cash_and_equivalents                          numeric,
    total_liabilities                                numeric,
    total_current_liabilities                           numeric,
    total_debt                                              numeric,
    total_equity                                               numeric,
    line_items                                                    jsonb,   -- overflow for less-common statement lines
    source_document_id                                               bigint REFERENCES docs.documents(document_id),
    is_active                                                          boolean NOT NULL DEFAULT true,
    created_by                                                          varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                          timestamptz NOT NULL DEFAULT now(),
    modified_by                                                           varchar(100),
    modified_date                                                          timestamptz,
    UNIQUE (company_id, period_end_date, period_type)
);

CREATE TABLE financials.income_statement (
    income_statement_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                    integer NOT NULL REFERENCES core.companies(company_id),
    period_end_date                  date NOT NULL,
    period_type                         varchar(2) NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','FY')),
    currency                               varchar(3) NOT NULL DEFAULT 'USD',
    revenue                                   numeric,
    cost_of_revenue                              numeric,
    gross_profit                                    numeric,
    operating_expenses                                 numeric,
    operating_income                                      numeric,
    net_income                                               numeric,
    eps_basic                                                   numeric,
    eps_diluted                                                    numeric,
    line_items                                                       jsonb,
    source_document_id                                                  bigint REFERENCES docs.documents(document_id),
    is_active                                                              boolean NOT NULL DEFAULT true,
    created_by                                                             varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                             timestamptz NOT NULL DEFAULT now(),
    modified_by                                                               varchar(100),
    modified_date                                                              timestamptz,
    UNIQUE (company_id, period_end_date, period_type)
);

CREATE TABLE financials.cash_flow (
    cash_flow_id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                     integer NOT NULL REFERENCES core.companies(company_id),
    period_end_date                   date NOT NULL,
    period_type                          varchar(2) NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','FY')),
    currency                                varchar(3) NOT NULL DEFAULT 'USD',
    operating_cash_flow                        numeric,
    investing_cash_flow                           numeric,
    financing_cash_flow                              numeric,
    capital_expenditures                                numeric,
    free_cash_flow                                         numeric,
    cash_end_of_period                                        numeric,
    line_items                                                   jsonb,
    source_document_id                                              bigint REFERENCES docs.documents(document_id),
    is_active                                                          boolean NOT NULL DEFAULT true,
    created_by                                                         varchar(100) NOT NULL DEFAULT current_user,
    created_date                                                         timestamptz NOT NULL DEFAULT now(),
    modified_by                                                           varchar(100),
    modified_date                                                          timestamptz,
    UNIQUE (company_id, period_end_date, period_type)
);

CREATE TABLE financials.financial_ratios (
    financial_ratio_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                      integer NOT NULL REFERENCES core.companies(company_id),
    period_end_date                    date NOT NULL,
    period_type                           varchar(2) NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','FY')),
    current_ratio                            numeric,
    debt_to_equity                              numeric,
    gross_margin                                   numeric,
    operating_margin                                  numeric,
    net_margin                                           numeric,
    return_on_equity                                        numeric,
    return_on_assets                                           numeric,
    ratio_data                                                    jsonb,
    source_document_id                                              bigint REFERENCES docs.documents(document_id),
    is_active                                                          boolean NOT NULL DEFAULT true,
    created_by                                                          varchar(100) NOT NULL DEFAULT current_user,
    calculated_at                                                        timestamptz NOT NULL DEFAULT now(),
    modified_by                                                           varchar(100),
    modified_date                                                          timestamptz,
    UNIQUE (company_id, period_end_date, period_type)
);

-- ============================================================================
-- 7. DEFERRED CROSS-SCHEMA FOREIGN KEYS
-- (docs.documents didn't exist yet when core.resource_estimates was created)
-- ============================================================================

ALTER TABLE core.resource_estimates
    ADD CONSTRAINT fk_resource_estimates_document
    FOREIGN KEY (source_document_id) REFERENCES docs.documents(document_id);

-- ============================================================================
-- End of gold_ddl.sql
-- ============================================================================
