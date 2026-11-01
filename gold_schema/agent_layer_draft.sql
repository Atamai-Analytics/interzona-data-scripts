-- ============================================================================
-- SUPERSEDES the earlier agent_layer_draft.sql. Draft only — nothing here has
-- been executed against interzona_cm.
--
-- The original draft built a separate `agent` schema (occurrences, samples,
-- sample_results, geology_summary) kept in sync with core/geochem via an
-- outbox + async worker. That machinery existed to solve one problem: an LLM
-- shouldn't have to join analytical_results through 5 lookup tables to read
-- one assay value.
--
-- But most of what got denormalized wasn't actually solving that problem:
--   - occurrences -> projects/companies is a join against tables with a few
--     hundred rows. That was never expensive. No reason to duplicate it.
--   - lat/lon/geog are derivable from geom with zero risk of drift — they
--     don't need "syncing" at all, Postgres can compute them itself.
--   - analyte_name/unit_code/laboratory/method_code/digest_name ARE the real
--     case: analytical_results is 38M+ rows, and resolving them via a join at
--     READ time is the expensive part. But resolving them via a cheap
--     BEFORE INSERT trigger against TINY lookup tables (145 rows, 41 rows,
--     138 rows) at WRITE time costs nothing and needs no separate table,
--     no outbox, no worker.
--
-- What's left that's genuinely a derived aggregate (not resolvable from this
-- row's own columns) — commodities array, jurisdiction hierarchy path,
-- geology_summary — gets a small trigger. Everything else lives directly on
-- core.occurrences / geochem.samples / geochem.analytical_results. There is
-- no more `agent` schema.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- core.occurrences — generated spatial columns (zero sync risk, computed by
-- Postgres from geom) + two trigger-maintained derived columns (genuinely
-- aggregated from other tables, so they DO need a sync mechanism — just a
-- small one, since occurrences is thousands of rows, not millions).
-- ----------------------------------------------------------------------------
ALTER TABLE core.occurrences
    ADD COLUMN occurrence_type_name  text,                 -- resolved alongside occurrence_type_id by the same trigger as commodities/jurisdiction, see below
    ADD COLUMN commodities             text[] NOT NULL DEFAULT '{}',   -- kept in sync by a trigger on occurrence_commodities
    ADD COLUMN jurisdiction_path         text[],           -- root-to-leaf, kept in sync by a trigger on THIS row's jurisdiction_id
    ADD COLUMN country_name                text,           -- = jurisdiction_path[1], set by the same trigger
    ADD COLUMN lat                           double precision GENERATED ALWAYS AS (ST_Y(geom)) STORED,
    ADD COLUMN lon                           double precision GENERATED ALWAYS AS (ST_X(geom)) STORED,
    ADD COLUMN geog                            geography(Point,4326) GENERATED ALWAYS AS (geom::geography) STORED;

CREATE INDEX idx_occurrences_commodities       ON core.occurrences USING gin(commodities);
CREATE INDEX idx_occurrences_jurisdiction_path ON core.occurrences USING gin(jurisdiction_path);
CREATE INDEX idx_occurrences_country           ON core.occurrences(country_name);
CREATE INDEX idx_occurrences_geog              ON core.occurrences USING gist(geog);

-- Resolves occurrence_type_name + jurisdiction_path + country_name whenever
-- this row's own occurrence_type_id / jurisdiction_id changes. Recursive CTE
-- walks the jurisdiction hierarchy to arbitrary depth (country -> state ->
-- district), root-to-leaf.
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

-- commodities is aggregated from a CHILD table (occurrence_commodities), so it
-- can change without this row itself being touched — needs its own trigger on
-- that child table, not on occurrences.
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

-- ----------------------------------------------------------------------------
-- geochem.samples — same zero-risk generated-column treatment. No
-- occurrence_name / sampling_line_label denormalization: occurrences and
-- sampling_lines are both small relative to samples, so joining to them is
-- cheap regardless of how many million sample rows exist.
-- ----------------------------------------------------------------------------
ALTER TABLE geochem.samples
    ADD COLUMN lat  double precision GENERATED ALWAYS AS (ST_Y(geom)) STORED,
    ADD COLUMN lon  double precision GENERATED ALWAYS AS (ST_X(geom)) STORED,
    ADD COLUMN geog geography(Point,4326) GENERATED ALWAYS AS (geom::geography) STORED;

CREATE INDEX idx_samples_geog ON geochem.samples USING gist(geog);

-- ----------------------------------------------------------------------------
-- geochem.analytical_results — THE collapse. Keeps every existing FK
-- (analyte_id, unit_id, qualifier_id, package_id, sample_id) for integrity,
-- and adds the resolved text values as plain columns on the SAME row,
-- populated by a BEFORE INSERT/UPDATE trigger doing scalar lookups against
-- tiny reference tables. One row, written once — no second table, no outbox,
-- no worker, no staleness window (beyond the rare case of a lookup table's
-- name being edited after the fact — same accepted tradeoff as before, but
-- now a one-line re-touch to fix: `UPDATE ... SET analyte_id = analyte_id`
-- re-fires the trigger, no architecture needed for that edge case).
-- ----------------------------------------------------------------------------
ALTER TABLE geochem.analytical_results
    ADD COLUMN analyte_name    text,
    ADD COLUMN analyte_symbol  text,
    ADD COLUMN unit_code       text,
    ADD COLUMN qualifier_code  text,
    ADD COLUMN laboratory      text,
    ADD COLUMN method_code     text,
    ADD COLUMN method_name     text,
    ADD COLUMN digest_name     text,
    ADD COLUMN occurrence_id   integer REFERENCES core.occurrences(occurrence_id);  -- denormalized down from sample_id's occurrence at write time — saves the join hop through samples on every "results for occurrence X" query

CREATE INDEX idx_ar_occurrence    ON geochem.analytical_results(occurrence_id);
CREATE INDEX idx_ar_analyte_name  ON geochem.analytical_results(analyte_name);
CREATE INDEX idx_ar_laboratory    ON geochem.analytical_results(laboratory);
CREATE INDEX idx_ar_method_code   ON geochem.analytical_results(method_code);

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

    SELECT occurrence_id INTO NEW.occurrence_id
    FROM geochem.samples WHERE sample_id = NEW.sample_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resolve_analytical_result_labels
    BEFORE INSERT OR UPDATE ON geochem.analytical_results
    FOR EACH ROW EXECUTE FUNCTION geochem.resolve_analytical_result_labels();

-- ----------------------------------------------------------------------------
-- core.geology_summary — the one case left that's genuinely a many-rows-to-one
-- aggregate (lithology + age + mineralogy observations rolled up per
-- occurrence), so it still needs its own table. Moved out of the now-deleted
-- `agent` schema into `core`, since it's occurrence-scoped metadata.
-- Population/refresh trigger deliberately left unbuilt here — same as before,
-- worth designing once this shape is confirmed.
-- ----------------------------------------------------------------------------
CREATE TABLE core.geology_summary (
    occurrence_id         integer PRIMARY KEY REFERENCES core.occurrences(occurrence_id),
    dominant_lithology        text,
    dominant_alteration          text,
    dominant_mineral               text,
    observations                      jsonb NOT NULL DEFAULT '[]',
    updated_at                        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_geology_summary_observations     ON core.geology_summary USING gin(observations);
CREATE INDEX idx_geology_summary_dominant_mineral ON core.geology_summary(dominant_mineral);

-- ============================================================================
-- End — NOT YET EXECUTED against interzona_cm. The live DB still has the
-- pre-collapse shape (no lat/lon/geog, no resolved columns on
-- analytical_results, no commodities/jurisdiction_path on occurrences).
-- ============================================================================
