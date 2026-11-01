-- =====================================================================
-- lithodat_qc_schema.sql
--
-- Deterministic QC audit layer for the criticalmineralsexp database,
-- implementing the 9 checks in "Critical Minerals Exploration Database
-- — Analytical Quality Flag Reference" (analytical_flags.docx), scoped
-- to run one region (country / division) at a time rather than a full
-- 38M-row sweep.
--
-- This is additive: it does NOT touch the existing flag_rules /
-- audit_runs / audit_flags tables. It lives in its own lithodat_*
-- namespace so it can be reviewed, run, and iterated on independently.
--
-- Safe to re-run: all CREATE statements are idempotent
-- (IF NOT EXISTS / OR REPLACE).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Reference table: the 9 deterministic rules, as documented
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lithodat_flag_rules (
    rule_code        varchar(64) PRIMARY KEY,
    rule_name        varchar(255) NOT NULL,
    tier             varchar(2)  NOT NULL CHECK (tier IN ('T1','T2')),
    rule_description text,
    rule_sql         text,          -- human-readable predicate, for documentation
    source_doc       varchar(255) DEFAULT 'Critical Minerals Exploration Database — Analytical Quality Flag Reference',
    is_active        boolean DEFAULT true,
    created_at       timestamp DEFAULT now()
);

INSERT INTO lithodat_flag_rules (rule_code, rule_name, tier, rule_description, rule_sql) VALUES
('ANAL-SENTINEL', 'Sentinel Value', 'T1',
 'Value matches a known sentinel/placeholder (999, -999, 9999, -9999, 99999, -99999). 999/-999 added after confirming the pattern via a live DB check: 412 inactive rows across 9 datasources already carried value=999 (deactivated in bulk, untracked, well before this QC schema existed), plus 7 still-active Greenland/GEUS rows (Sr/Cu/Ba/Ni, ppm) that had been missed by GEUS''s own cleanup pass.',
 'value IN (999, -999, 9999, -9999, 99999, -99999)'),

('ANAL-EXCEEDS-100PCT', 'Exceeds 100% Physical Maximum', 'T1',
 'Value exceeds the absolute physical maximum for its unit (>=100%, >=1e6 ppm, >=1e9 ppb).',
 '(unitcode=''%'' AND value>=100) OR (unitcode=''ppm'' AND value>=1000000) OR (unitcode=''ppb'' AND value>=1000000000)'),

('ANAL-EXCEEDS-PLAUSIBLE-MAX', 'Exceeds Element Physical Maximum', 'T1',
 'Value exceeds analytes.plausible_max_value for that element/unit.',
 'plausible_max_value IS NOT NULL AND plausible_max_unit = unitcode AND value >= plausible_max_value'),

('ANAL-PCT-BELOW-ORE-THRESHOLD', 'Ore-Grade Element Below Ore-Grade Threshold', 'T1',
 'Ore-grade-only element reported in % but below analytes.pct_ore_grade_threshold.',
 'unitcode=''%'' AND pct_ore_grade_only=TRUE AND value < pct_ore_grade_threshold'),

('ANAL-PCT-NOT-VALID', 'Element Not Valid in Percent', 'T1',
 'Element classified as never legitimately reported in percent (analytes.pct_reporting_valid=FALSE).',
 'unitcode=''%'' AND pct_reporting_valid=FALSE'),

('ANAL-SUSPECT-DL', 'Suspect Negative — Not a Recognised Detection Limit Pattern', 'T1',
 'Negative value, no qualifier, and significand not in the 1-2-5 series used for BDL encoding.',
 'value < 0 AND qualifier_id IS NULL AND significand NOT IN (1.0,1.25,1.5,2.0,2.5,3.0,4.0,5.0,7.5)'),

('ANAL-ZERO-UDL', 'Zero Value with Above-UDL Qualifier — Contradictory', 'T1',
 'Value is zero but carries an above-upper-detection-limit qualifier (> or G).',
 'value = 0 AND qualifier_code IN (''>'',''G'')'),

('ANAL-ZERO-BDL-CONVENTION', 'Zero Value with BDL Qualifier — Convention Inconsistency', 'T2',
 'Value is zero with a below-detection-limit qualifier (< or ND); convention is -DL, not 0.',
 'value = 0 AND qualifier_code IN (''<'',''ND'')'),

('ANAL-CROSS-PKG-1000X', 'Cross-Package Ratio > 1000x', 'T1',
 'Same sample+analyte+unit has >1 package with max/min value ratio > 1000 (likely ppm/ppb or decimal error).',
 'COUNT(DISTINCT package_id) > 1 AND MAX(value)/MIN(value) > 1000 -- grouped by sampleid, analyte_id, unitid')
ON CONFLICT (rule_code) DO UPDATE SET
    rule_name        = EXCLUDED.rule_name,
    tier             = EXCLUDED.tier,
    rule_description = EXCLUDED.rule_description,
    rule_sql         = EXCLUDED.rule_sql;

-- ---------------------------------------------------------------------
-- 2. Run metadata (one row per audit pass, tagged with its scope)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lithodat_audit_runs (
    run_id           serial PRIMARY KEY,
    target_table     varchar(64) NOT NULL DEFAULT 'analytical_results',  -- 'analytical_results' | 'geochem_export_detail'
    scope_type       varchar(16) NOT NULL CHECK (scope_type IN ('global','country','division')),
    scope_value      varchar(128),          -- e.g. 'Greenland', 'Tasmania'; NULL for global
    audit_label      varchar(255),
    run_by           varchar(128),
    started_at       timestamp DEFAULT now(),
    finished_at      timestamp,
    run_status       varchar(16) DEFAULT 'running',  -- running | complete | failed
    records_assessed bigint,
    records_flagged  bigint,
    flags_t1         bigint,
    flags_t2         bigint,
    notes            text,
    datasource_filter varchar(255)  -- optional additional filter on locations.datasource, e.g. 'GEUS - Geological Survey of Denmark and Greenland'
);
-- If lithodat_audit_runs already exists from an earlier version of this script, run:
--   ALTER TABLE lithodat_audit_runs ADD COLUMN IF NOT EXISTS datasource_filter varchar(255);

-- ---------------------------------------------------------------------
-- 3. Individual flags produced by a run
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lithodat_audit_flags (
    flag_id      bigserial PRIMARY KEY,
    run_id       integer NOT NULL REFERENCES lithodat_audit_runs(run_id),
    rule_code    varchar(64) NOT NULL REFERENCES lithodat_flag_rules(rule_code),
    tier         varchar(2)  NOT NULL,
    result_id    integer NOT NULL REFERENCES analytical_results(result_id),
    sampleid     integer,
    analyte_id   integer,
    unitid       integer,
    value        numeric,
    flag_reason  text,
    flag_detail  text,
    reviewed     boolean DEFAULT false,
    reviewed_by  varchar(128),
    reviewed_at  timestamp,
    created_at   timestamp DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lithodat_idx_audit_flags_run   ON lithodat_audit_flags (run_id);
CREATE INDEX IF NOT EXISTS lithodat_idx_audit_flags_rule  ON lithodat_audit_flags (rule_code);
CREATE INDEX IF NOT EXISTS lithodat_idx_audit_flags_result ON lithodat_audit_flags (result_id);

-- ---------------------------------------------------------------------
-- 4. Helper functions
--
-- lithodat_significand() and lithodat_is_preferred_significand() are a
-- corrected replacement for the existing is_preferred_significand():
-- that function queries a table called "preferred_significands", which
-- does not exist — the real table is "WA_preferred_significands"
-- (mixed case, must be quoted). It would error if actually called.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lithodat_significand(p_value numeric)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_value IS NULL OR p_value = 0 THEN NULL
        ELSE ROUND((ABS(p_value) / POWER(10, FLOOR(LOG(ABS(p_value)))))::numeric, 4)
    END;
$$;

CREATE OR REPLACE FUNCTION lithodat_is_preferred_significand(p_value numeric)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM "WA_preferred_significands" ps
        WHERE ps.significand = lithodat_significand(p_value)
    );
$$;

-- ---------------------------------------------------------------------
-- 5. Main orchestrator
--
-- Usage:
--   SELECT lithodat_run_deterministic_audit('global',   NULL,        'Full DB pass');
--   SELECT lithodat_run_deterministic_audit('country',  'Greenland', 'Greenland QC');
--   SELECT lithodat_run_deterministic_audit('division', 'Tasmania',  'Tasmania QC');
--   SELECT lithodat_run_deterministic_audit('country',  'Greenland', 'Greenland + GEUS QC',
--                                            NULL, 'GEUS - Geological Survey of Denmark and Greenland');
--
-- Returns the run_id. All 9 rules are evaluated against a single scoped
-- snapshot of analytical_results (built once per call), so this is a
-- single scan of the region's data regardless of rule count.
--
-- If you already have an OLDER version of this function installed with a
-- different argument count, drop it first so the current version replaces
-- it cleanly instead of creating an overload:
--   DROP FUNCTION IF EXISTS lithodat_run_deterministic_audit(text,text,text,text);
--   DROP FUNCTION IF EXISTS lithodat_run_deterministic_audit(text,text,text,text,text);
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lithodat_run_deterministic_audit(
    p_scope_type      text,
    p_scope_value     text DEFAULT NULL,
    p_audit_label     text DEFAULT NULL,
    p_run_by          text DEFAULT NULL,
    p_datasource      text DEFAULT NULL,   -- optional: further restrict to locations.datasource, e.g. 'GEUS - Geological Survey of Denmark and Greenland'
    p_sample_type_id  integer[] DEFAULT NULL -- optional: further restrict to samples.sample_type_id, e.g. ARRAY[31] for GTK Finland Rock (ROCK_SURFACE) vs. TILL/SEDIMENT under the same country+datasource, or ARRAY[2,13,14,70,71,72] for all SOIL-category types (Resources Victoria)
) RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id   integer;
    v_assessed bigint;
    v_flagged  bigint;
    v_t1       bigint;
    v_t2       bigint;
BEGIN
    IF p_scope_type NOT IN ('global','country','division') THEN
        RAISE EXCEPTION 'p_scope_type must be global, country, or division (got %)', p_scope_type;
    END IF;
    IF p_scope_type <> 'global' AND p_scope_value IS NULL THEN
        RAISE EXCEPTION 'p_scope_value is required when p_scope_type = %', p_scope_type;
    END IF;

    INSERT INTO lithodat_audit_runs (target_table, scope_type, scope_value, audit_label, run_by, run_status, datasource_filter)
    VALUES (
        'analytical_results', p_scope_type, p_scope_value,
        COALESCE(p_audit_label, p_scope_type || ':' || COALESCE(p_scope_value, 'all')
            || COALESCE(' + datasource=' || p_datasource, '')
            || COALESCE(' + sample_type_id=' || p_sample_type_id::text, '')),
        COALESCE(p_run_by, current_user),
        'running',
        p_datasource
    )
    RETURNING run_id INTO v_run_id;

    -- Build the scoped result set once; every rule below reuses it.
    DROP TABLE IF EXISTS lithodat_scope_results;
    CREATE TEMP TABLE lithodat_scope_results ON COMMIT DROP AS
    SELECT ar.result_id, ar.sampleid, ar.package_id, ar.analyte_id, ar.unitid,
           ar.qualifier_id, ar.value
    FROM analytical_results ar
    JOIN samples   s ON s.sampleid   = ar.sampleid
    JOIN locations l ON l.locationid = s.locationid
    LEFT JOIN countries c ON c.countryid = l.countryid
    LEFT JOIN divisions d ON d.divisionid = l.divisionid
    WHERE ar.isactive = TRUE
      AND (
            p_scope_type = 'global'
            OR (p_scope_type = 'country'  AND c.countryname  = p_scope_value)
            OR (p_scope_type = 'division' AND d.divisionname = p_scope_value)
          )
      AND (p_datasource IS NULL OR l.datasource = p_datasource)
      AND (p_sample_type_id IS NULL OR s.sample_type_id = ANY(p_sample_type_id));

    CREATE INDEX ON lithodat_scope_results (analyte_id, unitid, sampleid);

    SELECT count(*) INTO v_assessed FROM lithodat_scope_results;

    -- R1: ANAL-SENTINEL
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-SENTINEL', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Sentinel/placeholder value', 'value=' || r.value::text
    FROM lithodat_scope_results r
    WHERE r.value IN (999, -999, 9999, -9999, 99999, -99999);

    -- R2: ANAL-EXCEEDS-100PCT
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-EXCEEDS-100PCT', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Exceeds 100% physical maximum', 'unit=' || u.unitcode || ' value=' || r.value::text
    FROM lithodat_scope_results r
    JOIN units u ON u.unitid = r.unitid
    WHERE (u.unitcode = '%'   AND r.value >= 100)
       OR (u.unitcode = 'ppm' AND r.value >= 1000000)
       OR (u.unitcode = 'ppb' AND r.value >= 1000000000);

    -- R3: ANAL-EXCEEDS-PLAUSIBLE-MAX
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-EXCEEDS-PLAUSIBLE-MAX', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Exceeds element plausible maximum',
           'plausible_max=' || a.plausible_max_value::text || ' ' || a.plausible_max_unit
    FROM lithodat_scope_results r
    JOIN analytes a ON a.analyte_id = r.analyte_id
    JOIN units u ON u.unitid = r.unitid
    WHERE a.plausible_max_value IS NOT NULL
      AND a.plausible_max_unit = u.unitcode
      AND r.value >= a.plausible_max_value;

    -- R4: ANAL-PCT-BELOW-ORE-THRESHOLD
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-PCT-BELOW-ORE-THRESHOLD', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Ore-grade element below ore-grade threshold in %',
           'threshold=' || a.pct_ore_grade_threshold::text || '%'
    FROM lithodat_scope_results r
    JOIN analytes a ON a.analyte_id = r.analyte_id
    JOIN units u ON u.unitid = r.unitid
    WHERE u.unitcode = '%'
      AND a.pct_ore_grade_only = TRUE
      AND r.value < a.pct_ore_grade_threshold;

    -- R5: ANAL-PCT-NOT-VALID
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-PCT-NOT-VALID', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Element not valid in percent', 'analyte never legitimately reported in %'
    FROM lithodat_scope_results r
    JOIN analytes a ON a.analyte_id = r.analyte_id
    JOIN units u ON u.unitid = r.unitid
    WHERE u.unitcode = '%'
      AND a.pct_reporting_valid = FALSE;

    -- R6: ANAL-SUSPECT-DL
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-SUSPECT-DL', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Suspect negative — not a recognised DL pattern',
           'significand=' || lithodat_significand(r.value)::text
    FROM lithodat_scope_results r
    WHERE r.value < 0
      AND r.qualifier_id IS NULL
      AND NOT lithodat_is_preferred_significand(r.value);

    -- R7: ANAL-ZERO-UDL
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-ZERO-UDL', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Zero value with above-UDL qualifier — contradictory', 'qualifier=' || q.qualifier_code
    FROM lithodat_scope_results r
    JOIN qualifiers q ON q.qualifier_id = r.qualifier_id
    WHERE r.value = 0
      AND q.qualifier_code IN ('>', 'G');

    -- R8: ANAL-ZERO-BDL-CONVENTION (T2)
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-ZERO-BDL-CONVENTION', 'T2', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Zero value with BDL qualifier — convention inconsistency', 'qualifier=' || q.qualifier_code
    FROM lithodat_scope_results r
    JOIN qualifiers q ON q.qualifier_id = r.qualifier_id
    WHERE r.value = 0
      AND q.qualifier_code IN ('<', 'ND');

    -- R9: ANAL-CROSS-PKG-1000X
    WITH grp AS (
        SELECT sampleid, analyte_id, unitid,
               max(value) AS max_val, min(value) AS min_val,
               max(value) / NULLIF(min(value), 0) AS ratio
        FROM lithodat_scope_results
        WHERE value > 0
        GROUP BY sampleid, analyte_id, unitid
        HAVING count(DISTINCT package_id) > 1
           AND max(value) / NULLIF(min(value), 0) > 1000
    )
    INSERT INTO lithodat_audit_flags (run_id, rule_code, tier, result_id, sampleid, analyte_id, unitid, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-CROSS-PKG-1000X', 'T1', r.result_id, r.sampleid, r.analyte_id, r.unitid, r.value,
           'Cross-package ratio exceeds 1000x',
           'ratio=' || round(g.ratio, 1)::text || ' (min=' || g.min_val::text || ', max=' || g.max_val::text || ')'
    FROM grp g
    JOIN lithodat_scope_results r
      ON r.sampleid = g.sampleid AND r.analyte_id = g.analyte_id AND r.unitid = g.unitid
     AND r.value > 0;

    SELECT count(*),
           count(*) FILTER (WHERE tier = 'T1'),
           count(*) FILTER (WHERE tier = 'T2')
    INTO v_flagged, v_t1, v_t2
    FROM lithodat_audit_flags WHERE run_id = v_run_id;

    UPDATE lithodat_audit_runs
    SET finished_at      = now(),
        run_status       = 'complete',
        records_assessed = v_assessed,
        records_flagged  = v_flagged,
        flags_t1         = v_t1,
        flags_t2         = v_t2
    WHERE run_id = v_run_id;

    RETURN v_run_id;
END;
$$;

-- =====================================================================
-- 6. geochem_export_detail variant
--
-- geochem_export_detail is structurally different from analytical_results
-- and needs its own runner, not just a different WHERE clause:
--
--  * No primary key / surrogate id of any kind. ("aliquotName",
--    element_oxide) was verified unique in a 0.5% sample of the table
--    (178,082 distinct pairs across 178,082 sampled rows) and is used
--    here as a natural key. It is NOT a database-enforced constraint —
--    if you later find a collision, this needs revisiting.
--  * No analyte_id — joins to analytes on analyte_code = element_oxide
--    instead (verified: every element_oxide value in a sample matched
--    an analytes.analyte_code, including oxide forms like SiO2/K2O,
--    and analyte_code is unique).
--  * No unitid — sourceunit already holds the same short codes
--    ('%','ppm','ppb', ...) that unitcode holds on the normalized side,
--    used directly.
--  * No qualifier_id — qualifier_code is already the same short text
--    ('<','>','ND','G', ...), used directly.
--  * No package_id / analytical_packages. There is no faithful analog
--    for "two packages disagree by >1000x" here. This runner
--    approximates a "package" as the (laboratorycode, sourcemethodcode)
--    pair — i.e. it flags the same datapoint+analyte reported at
--    wildly different values by two different lab/method combinations.
--    Treat ANAL-CROSS-PKG-1000X results from this runner as lower
--    confidence than the analytical_results version.
--  * countryname is a direct column here (no join to
--    samples/locations/countries needed) — but there is no
--    state/province column, so 'division' scope (e.g. Tasmania) is
--    NOT supported against this table. Only 'global' and 'country'
--    are valid here.
--  * geochem_export_detail's row count (~35.3M) is close to
--    analytical_results' active row count, which strongly suggests
--    this export table is largely a flattened copy of the same
--    underlying measurements rather than an independent dataset.
--    Worth confirming with whoever owns the export/ETL job before
--    treating flags from the two runners as covering different data.
-- =====================================================================

CREATE TABLE IF NOT EXISTS lithodat_audit_flags_ged (
    flag_id        bigserial PRIMARY KEY,
    run_id         integer NOT NULL REFERENCES lithodat_audit_runs(run_id),
    rule_code      varchar(64) NOT NULL REFERENCES lithodat_flag_rules(rule_code),
    tier           varchar(2) NOT NULL,
    aliquot_name   text NOT NULL,      -- natural key, part 1 (geochem_export_detail."aliquotName")
    analyte_code   varchar(32),        -- natural key, part 2 (geochem_export_detail.element_oxide)
    datapoint_name text,
    sample_name    text,
    unit_code      varchar(16),
    value          numeric,
    flag_reason    text,
    flag_detail    text,
    reviewed       boolean DEFAULT false,
    reviewed_by    varchar(128),
    reviewed_at    timestamp,
    created_at     timestamp DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lithodat_idx_audit_flags_ged_run  ON lithodat_audit_flags_ged (run_id);
CREATE INDEX IF NOT EXISTS lithodat_idx_audit_flags_ged_rule ON lithodat_audit_flags_ged (rule_code);
CREATE INDEX IF NOT EXISTS lithodat_idx_audit_flags_ged_key  ON lithodat_audit_flags_ged (aliquot_name, analyte_code);

-- Usage:
--   SELECT lithodat_run_deterministic_audit_ged('global',  NULL,       'Full export pass');
--   SELECT lithodat_run_deterministic_audit_ged('country', 'Greenland','Greenland export QC');
-- 'division' is not supported here — see notes above.
CREATE OR REPLACE FUNCTION lithodat_run_deterministic_audit_ged(
    p_scope_type  text,
    p_scope_value text DEFAULT NULL,
    p_audit_label text DEFAULT NULL,
    p_run_by      text DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id   integer;
    v_assessed bigint;
    v_flagged  bigint;
    v_t1       bigint;
    v_t2       bigint;
BEGIN
    IF p_scope_type NOT IN ('global','country') THEN
        RAISE EXCEPTION 'p_scope_type must be global or country for geochem_export_detail (got %) — division scope is not available on this table', p_scope_type;
    END IF;
    IF p_scope_type = 'country' AND p_scope_value IS NULL THEN
        RAISE EXCEPTION 'p_scope_value is required when p_scope_type = country';
    END IF;

    INSERT INTO lithodat_audit_runs (target_table, scope_type, scope_value, audit_label, run_by, run_status)
    VALUES (
        'geochem_export_detail', p_scope_type, p_scope_value,
        COALESCE(p_audit_label, 'ged:' || p_scope_type || ':' || COALESCE(p_scope_value, 'all')),
        COALESCE(p_run_by, current_user),
        'running'
    )
    RETURNING run_id INTO v_run_id;

    DROP TABLE IF EXISTS lithodat_scope_ged;
    CREATE TEMP TABLE lithodat_scope_ged ON COMMIT DROP AS
    SELECT
        ged."aliquotName"    AS aliquot_name,
        ged.element_oxide    AS analyte_code,
        ged.sourceunit       AS unit_code,
        ged.qualifier_code   AS qualifier_code,
        ged.value            AS value,
        ged.laboratorycode   AS laboratorycode,
        ged.sourcemethodcode AS sourcemethodcode,
        ged."datapointName"  AS datapoint_name,
        ged."sampleName"     AS sample_name
    FROM geochem_export_detail ged
    WHERE ged.isactive = TRUE
      AND ged."aliquotName" IS NOT NULL
      AND (
            p_scope_type = 'global'
            OR (p_scope_type = 'country' AND ged.countryname = p_scope_value)
          );

    CREATE INDEX ON lithodat_scope_ged (analyte_code, unit_code);
    CREATE INDEX ON lithodat_scope_ged (aliquot_name, analyte_code);

    SELECT count(*) INTO v_assessed FROM lithodat_scope_ged;

    -- R1: ANAL-SENTINEL
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-SENTINEL', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Sentinel/placeholder value', 'value=' || r.value::text
    FROM lithodat_scope_ged r
    WHERE r.value IN (999, -999, 9999, -9999, 99999, -99999);

    -- R2: ANAL-EXCEEDS-100PCT
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-EXCEEDS-100PCT', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Exceeds 100% physical maximum', 'unit=' || r.unit_code || ' value=' || r.value::text
    FROM lithodat_scope_ged r
    WHERE (r.unit_code = '%'   AND r.value >= 100)
       OR (r.unit_code = 'ppm' AND r.value >= 1000000)
       OR (r.unit_code = 'ppb' AND r.value >= 1000000000);

    -- R3: ANAL-EXCEEDS-PLAUSIBLE-MAX
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-EXCEEDS-PLAUSIBLE-MAX', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Exceeds element plausible maximum',
           'plausible_max=' || a.plausible_max_value::text || ' ' || a.plausible_max_unit
    FROM lithodat_scope_ged r
    JOIN analytes a ON a.analyte_code = r.analyte_code
    WHERE a.plausible_max_value IS NOT NULL
      AND a.plausible_max_unit = r.unit_code
      AND r.value >= a.plausible_max_value;

    -- R4: ANAL-PCT-BELOW-ORE-THRESHOLD
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-PCT-BELOW-ORE-THRESHOLD', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Ore-grade element below ore-grade threshold in %',
           'threshold=' || a.pct_ore_grade_threshold::text || '%'
    FROM lithodat_scope_ged r
    JOIN analytes a ON a.analyte_code = r.analyte_code
    WHERE r.unit_code = '%'
      AND a.pct_ore_grade_only = TRUE
      AND r.value < a.pct_ore_grade_threshold;

    -- R5: ANAL-PCT-NOT-VALID
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-PCT-NOT-VALID', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Element not valid in percent', 'analyte never legitimately reported in %'
    FROM lithodat_scope_ged r
    JOIN analytes a ON a.analyte_code = r.analyte_code
    WHERE r.unit_code = '%'
      AND a.pct_reporting_valid = FALSE;

    -- R6: ANAL-SUSPECT-DL
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-SUSPECT-DL', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Suspect negative — not a recognised DL pattern',
           'significand=' || lithodat_significand(r.value)::text
    FROM lithodat_scope_ged r
    WHERE r.value < 0
      AND r.qualifier_code IS NULL
      AND NOT lithodat_is_preferred_significand(r.value);

    -- R7: ANAL-ZERO-UDL
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-ZERO-UDL', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Zero value with above-UDL qualifier — contradictory', 'qualifier=' || r.qualifier_code
    FROM lithodat_scope_ged r
    WHERE r.value = 0
      AND r.qualifier_code IN ('>', 'G');

    -- R8: ANAL-ZERO-BDL-CONVENTION (T2)
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-ZERO-BDL-CONVENTION', 'T2', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Zero value with BDL qualifier — convention inconsistency', 'qualifier=' || r.qualifier_code
    FROM lithodat_scope_ged r
    WHERE r.value = 0
      AND r.qualifier_code IN ('<', 'ND');

    -- R9: ANAL-CROSS-PKG-1000X (approximated — see notes above:
    -- "package" here = distinct (laboratorycode, sourcemethodcode) pairs
    -- reporting the same datapoint+analyte)
    WITH grp AS (
        SELECT datapoint_name, analyte_code, unit_code,
               max(value) AS max_val, min(value) AS min_val,
               max(value) / NULLIF(min(value), 0) AS ratio
        FROM lithodat_scope_ged
        WHERE value > 0
        GROUP BY datapoint_name, analyte_code, unit_code
        HAVING count(DISTINCT (laboratorycode, sourcemethodcode)) > 1
           AND max(value) / NULLIF(min(value), 0) > 1000
    )
    INSERT INTO lithodat_audit_flags_ged (run_id, rule_code, tier, aliquot_name, analyte_code, datapoint_name, sample_name, unit_code, value, flag_reason, flag_detail)
    SELECT v_run_id, 'ANAL-CROSS-PKG-1000X', 'T1', r.aliquot_name, r.analyte_code, r.datapoint_name, r.sample_name, r.unit_code, r.value,
           'Cross-package ratio exceeds 1000x (package approximated as lab+method)',
           'ratio=' || round(g.ratio, 1)::text || ' (min=' || g.min_val::text || ', max=' || g.max_val::text || ')'
    FROM grp g
    JOIN lithodat_scope_ged r
      ON r.datapoint_name = g.datapoint_name AND r.analyte_code = g.analyte_code AND r.unit_code = g.unit_code
     AND r.value > 0;

    SELECT count(*),
           count(*) FILTER (WHERE tier = 'T1'),
           count(*) FILTER (WHERE tier = 'T2')
    INTO v_flagged, v_t1, v_t2
    FROM lithodat_audit_flags_ged WHERE run_id = v_run_id;

    UPDATE lithodat_audit_runs
    SET finished_at      = now(),
        run_status       = 'complete',
        records_assessed = v_assessed,
        records_flagged  = v_flagged,
        flags_t1         = v_t1,
        flags_t2         = v_t2
    WHERE run_id = v_run_id;

    RETURN v_run_id;
END;
$$;

-- =====================================================================
-- 7. Correction audit trail
--
-- Whenever a flagged value is actually corrected (backfilled, recoded,
-- deactivated) rather than just reported, log the old state here first.
-- These are plain log tables, not automated by the runner — corrections
-- are reviewed and applied by hand (or by a follow-up script), one
-- rule/pattern at a time, logging before each UPDATE. Kept here so the
-- full picture — detection AND correction — lives in one schema file.
-- =====================================================================

CREATE TABLE IF NOT EXISTS lithodat_value_updates_log (
    log_id            bigserial PRIMARY KEY,
    result_id         integer NOT NULL,
    old_value         numeric,
    new_value         numeric,
    old_qualifier_id  integer,
    new_qualifier_id  integer,
    reason            varchar(255),
    updated_by        varchar(128),
    updated_at        timestamp DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lithodat_isactive_updates_log (
    log_id       bigserial PRIMARY KEY,
    result_id    integer NOT NULL,
    old_isactive boolean,
    new_isactive boolean,
    rule_code    varchar(64),
    reason       varchar(255),
    updated_by   varchar(128),
    updated_at   timestamp DEFAULT now()
);

-- Example correction pattern (log first, then update, then re-run the
-- audit to confirm the flag cleared):
--
--   INSERT INTO lithodat_isactive_updates_log (result_id, old_isactive, new_isactive, rule_code, reason, updated_by)
--   SELECT DISTINCT f.result_id, TRUE, FALSE, f.rule_code, '<why>', current_user
--   FROM lithodat_audit_flags f
--   WHERE f.run_id = <run_id> AND f.rule_code = '<RULE_CODE>';
--
--   UPDATE analytical_results ar
--   SET isactive = FALSE, modified_by = 'lithodat_qc_deactivate', modified_date = now()
--   FROM (SELECT DISTINCT f.result_id FROM lithodat_audit_flags f
--         WHERE f.run_id = <run_id> AND f.rule_code = '<RULE_CODE>') x
--   WHERE ar.result_id = x.result_id;

-- =====================================================================
-- Section 8: lithodat_recode_negative_dl_values() — reusable, region-
-- scoped negative-value cleanup, generalized from the Greenland/GEUS
-- pass.
--
-- Background: analytical_results sometimes encodes "below detection
-- limit" as a negative value with no qualifier (an informal convention)
-- rather than the DB-wide dominant convention (qualifier_id = 1 '<',
-- positive value). A negative value is only a *safe* candidate for
-- recoding to that convention when BOTH:
--   (a) its leading digit matches the preferred detection-limit
--       significand series (lithodat_is_preferred_significand) — e.g.
--       1.0, 2.5, 5.0 x 10^n rather than an arbitrary value like -3.14
--   (b) the resulting positive magnitude is physically plausible for
--       that element/unit (lithodat_is_plausible_dl, new below)
--
-- (b) exists because (a) alone is not sufficient: -10,000,000 ppb Pt/Pd
-- has a "preferred" significand (1.0 x 10^7) but is ~200x the element's
-- plausible_max_value (50,000 ppb) once made positive — clearly not a
-- real detection limit. This was caught during the Greenland/GEUS
-- cleanup (run 7 surfaced 506 new ANAL-EXCEEDS-PLAUSIBLE-MAX flags
-- immediately after a recode that didn't check magnitude) and is why
-- this check exists.
--
-- Anything that fails either check is deactivated rather than guessed
-- at, per the standing rule: recode only where it's unambiguous, flag
-- everything else inactive for human review.
-- =====================================================================

-- ---------------------------------------------------------------------
-- lithodat_is_plausible_dl(analyte_id, unitid, value)
--
-- TRUE if abs(value) is under analytes.plausible_max_value for the
-- result's unit — i.e. physically plausible as a detection limit for
-- that element. If no plausible_max is defined for this element/unit
-- combination (or the units don't match), this can't rule anything
-- out, so it returns TRUE and defers entirely to the significand check.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lithodat_is_plausible_dl(p_analyte_id integer, p_unitid integer, p_value numeric)
RETURNS boolean
LANGUAGE plpgsql
AS $$
DECLARE
    v_max      numeric;
    v_max_unit text;
    v_unitcode text;
BEGIN
    SELECT a.plausible_max_value, a.plausible_max_unit
      INTO v_max, v_max_unit
    FROM analytes a WHERE a.analyte_id = p_analyte_id;

    SELECT u.unitcode INTO v_unitcode FROM units u WHERE u.unitid = p_unitid;

    IF v_max IS NULL OR v_max_unit IS NULL OR v_unitcode IS NULL OR v_max_unit <> v_unitcode THEN
        RETURN TRUE;
    END IF;

    RETURN abs(p_value) < v_max;
END;
$$;

-- ---------------------------------------------------------------------
-- lithodat_recode_negative_dl_values(scope_type, scope_value, datasource, run_by)
--
-- For every ACTIVE analytical_results row in scope with value < 0:
--   - preferred significand AND plausible magnitude
--       -> recode as a real DL: qualifier_id = 1, value = abs(value),
--          modified_by = 'lithodat_qc_bdl_recode'
--   - otherwise (not a recognised DL pattern, or a recognised pattern
--     that's implausible in magnitude)
--       -> deactivate: isactive = FALSE,
--          modified_by = 'lithodat_qc_deactivate'
--
-- Every change is logged to lithodat_value_updates_log and/or
-- lithodat_isactive_updates_log BEFORE being applied, so every
-- correction is reversible and auditable. Re-running against a scope
-- that's already clean is a safe no-op (0 candidates matched).
--
-- Usage:
--   SELECT * FROM lithodat_recode_negative_dl_values('country', 'Greenland',
--                    'GEUS - Geological Survey of Denmark and Greenland');
--   SELECT * FROM lithodat_recode_negative_dl_values('division', 'Tasmania');
--   SELECT * FROM lithodat_recode_negative_dl_values('global');
--
-- Returns one row: (n_recoded, n_deactivated). Always re-run
-- lithodat_run_deterministic_audit() afterwards to confirm the scope
-- comes back clean.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lithodat_recode_negative_dl_values(
    p_scope_type  text,
    p_scope_value text DEFAULT NULL,
    p_datasource  text DEFAULT NULL,
    p_run_by      text DEFAULT NULL
) RETURNS TABLE(n_recoded bigint, n_deactivated bigint)
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_by        text := COALESCE(p_run_by, current_user);
    v_n_recoded     bigint;
    v_n_deactivated bigint;
BEGIN
    IF p_scope_type NOT IN ('global','country','division') THEN
        RAISE EXCEPTION 'p_scope_type must be global, country, or division (got %)', p_scope_type;
    END IF;
    IF p_scope_type <> 'global' AND p_scope_value IS NULL THEN
        RAISE EXCEPTION 'p_scope_value is required when p_scope_type = %', p_scope_type;
    END IF;

    DROP TABLE IF EXISTS lithodat_recode_candidates;
    CREATE TEMP TABLE lithodat_recode_candidates ON COMMIT DROP AS
    SELECT ar.result_id, ar.value, ar.qualifier_id,
           lithodat_is_preferred_significand(ar.value) AS is_preferred,
           lithodat_is_plausible_dl(ar.analyte_id, ar.unitid, ar.value) AS is_plausible
    FROM analytical_results ar
    JOIN samples   s ON s.sampleid   = ar.sampleid
    JOIN locations l ON l.locationid = s.locationid
    LEFT JOIN countries c ON c.countryid = l.countryid
    LEFT JOIN divisions d ON d.divisionid = l.divisionid
    WHERE ar.isactive = TRUE
      AND ar.value < 0
      AND (
            p_scope_type = 'global'
            OR (p_scope_type = 'country'  AND c.countryname  = p_scope_value)
            OR (p_scope_type = 'division' AND d.divisionname = p_scope_value)
          )
      AND (p_datasource IS NULL OR l.datasource = p_datasource);

    -- Log + recode: preferred significand AND plausible magnitude
    INSERT INTO lithodat_value_updates_log (result_id, old_value, new_value, old_qualifier_id, new_qualifier_id, reason, updated_by)
    SELECT result_id, value, abs(value), qualifier_id, 1,
           'Negative value: preferred DL significand + plausible magnitude - normalized to qualifier_id=1, value=abs(value)',
           v_run_by
    FROM lithodat_recode_candidates
    WHERE is_preferred AND is_plausible;

    UPDATE analytical_results ar
    SET value = abs(ar.value), qualifier_id = 1, modified_by = 'lithodat_qc_bdl_recode', modified_date = now()
    FROM lithodat_recode_candidates x
    WHERE ar.result_id = x.result_id AND x.is_preferred AND x.is_plausible;
    GET DIAGNOSTICS v_n_recoded = ROW_COUNT;

    -- Log + deactivate: everything else
    INSERT INTO lithodat_isactive_updates_log (result_id, old_isactive, new_isactive, rule_code, reason, updated_by)
    SELECT result_id, TRUE, FALSE, 'ANAL-SUSPECT-DL',
           CASE WHEN is_preferred THEN 'Preferred DL significand but implausible magnitude for element/unit - deactivated'
                ELSE 'Negative value does not match a recognised DL pattern - deactivated' END,
           v_run_by
    FROM lithodat_recode_candidates
    WHERE NOT (is_preferred AND is_plausible);

    UPDATE analytical_results ar
    SET isactive = FALSE, modified_by = 'lithodat_qc_deactivate', modified_date = now()
    FROM lithodat_recode_candidates x
    WHERE ar.result_id = x.result_id AND NOT (x.is_preferred AND x.is_plausible);
    GET DIAGNOSTICS v_n_deactivated = ROW_COUNT;

    RETURN QUERY SELECT v_n_recoded, v_n_deactivated;
END;
$$;

-- =====================================================================
-- Section 9: lithodat_refresh_geochem_exports() — scoped version of the
-- pre-existing aafn_refresh_geochem_exports().
--
-- Background: aafn_refresh_geochem_exports() TRUNCATEs and rebuilds
-- lithodat_datapoint_concentrations (35M rows, ~16GB) and
-- lithodat_datapoint_export (3.6M rows, ~1.2GB) from scratch, unscoped.
-- On this database that took 20+ minutes and repeatedly failed to
-- finish before the client connection (a device-bridge session) gave
-- out, leaving the export tables stale. This scoped version only
-- touches the requested datasource/country, so a single-region refresh
-- (e.g. after a QC cleanup pass) is a DELETE+INSERT over ~1M rows
-- instead of the full 35M — seconds/minutes instead of 20+.
--
-- Requires idx_ldc_datasource / idx_lde_datasource (below) — without
-- them the scoped DELETE still has to seq-scan the full table looking
-- for matching rows, which was the actual root cause of the slowness
-- (confirmed via pg_stat_activity: DataFileRead waits, not a stuck
-- connection). Both indexes are created once, IF NOT EXISTS, and then
-- benefit every future scoped call regardless of which datasource is
-- passed in.
--
-- Usage:
--   SELECT lithodat_refresh_geochem_exports(p_datasource := 'GEUS - Geological Survey of Denmark and Greenland');
--   SELECT lithodat_refresh_geochem_exports(p_country := 'Tasmania');
--   SELECT lithodat_refresh_geochem_exports();  -- both NULL: full TRUNCATE+rebuild, same as aafn_refresh_geochem_exports()
--
-- The original aafn_refresh_geochem_exports() is untouched.
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_ldc_datasource ON lithodat_datapoint_concentrations (datasource);
CREATE INDEX IF NOT EXISTS idx_lde_datasource ON lithodat_datapoint_export (datasource);

CREATE OR REPLACE FUNCTION lithodat_refresh_geochem_exports(
    p_datasource text DEFAULT NULL,
    p_country    text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
AS $function$
DECLARE
  v_start timestamp := clock_timestamp();
  v_detail_count bigint;
  v_header_count bigint;
BEGIN
  SET LOCAL work_mem = '512MB';

  IF p_datasource IS NULL AND p_country IS NULL THEN
    TRUNCATE TABLE lithodat_datapoint_concentrations;
  ELSE
    DELETE FROM lithodat_datapoint_concentrations
    WHERE (p_datasource IS NULL OR datasource = p_datasource)
      AND (p_country    IS NULL OR countryname = p_country);
  END IF;

  INSERT INTO lithodat_datapoint_concentrations
  SELECT
      s.sampleid||'_'||ap.package_id||'_'||un.unitcode||'//AA' AS "datapointName",
      l.locationname as datapackageName,
      l.locationid || '//AA'                  AS "sampleName",
      NULL::text                              AS "referenceMaterial",
      NULL::text                              AS description,
      'Other'                                 AS "geochemAnalyticalType",
      'Crushed Powder'                        AS "analyteMaterial",
      NULL::text                              AS "analyticalSessionID",
      NULL::text                              AS analyst,
      NULL::text                              AS "batchID",
      NULL::text                              AS "mountID",
      'Whole Rock'                            AS "analysisScale",
      NULL::text                              AS mineral,
      NULL::text                              AS "oxideUncertaintyType",
      NULL::text                              AS "elementUncertaintyType",
      dm.ls_digestion_category_name           AS digestionCategory,
      dm.ls_digestion_method_name             AS digestionMethod,
      NULL::text as digestionTempCelsius,
      NULL::text as digestionNotes,
      NULL::text as quantitationLevel,
      ap.package_code   as sourceMethodCode,
      ap.package_name as sourceMethodDesc,
      lab.lab_code as laboratoryCode,
      un.unitcode as sourceUnit,
      NULL::text as sampleWeightGm,
      TO_CHAR(ar.date_analysed, 'DD.MM.YYYY')   analysisDate,
      NULL::text as sourceAnalysisId,
      c.countryname||'; '||INITCAP(SPLIT_PART(st.category_code, '_', 1))||'; Multi-element; oxide' AS "Tag",
      NULL::text                              AS literature,
      lab.lab_name                            AS laboratory,
      NULL::text                              AS funding,
      NULL::text                              AS machine,
      s.sampleid||'_'||ap.package_id||'_'||un.unitcode||'//AA' as "aliquotName",
      NULL::text                              AS "spotID",
      anl.analyte_code  as element_oxide,
      ql.qualifier_code as "RelativeOperator",
      ar.value * uc.conversionfactor          as "Conc",
      NULL::text                              AS "Uncertainty",
      ar.lower_detection_limit as DetectionLimit,
      NULL::text                              AS MeasuredMass,
      c.countryname,
      l.datasource,
      s.sample_type_id,
      ar.isactive,
      anl.element_symbol,
      am.method_code,
      am.method_name,
      un.unitname,
      ql.qualifier_code,
      ql.qualifier_name,
      ar.value,
      ar.upper_detection_limit,
      ar.result_id,
      anl.analysis_group
  FROM analytical_results ar
  INNER JOIN samples s
      ON s.sampleid = ar.sampleid
  INNER JOIN locations l
      ON l.locationid = s.locationid
  INNER JOIN countries c
      ON c.countryid = l.countryid
  INNER JOIN analytical_packages ap
      ON ap.package_id = ar.package_id
  INNER JOIN laboratories lab
      ON lab.lab_id = ap.lab_id
  INNER JOIN analytical_methods am
      ON am.method_id = ap.method_id
  INNER JOIN analytes anl
      ON anl.analyte_id = ar.analyte_id
  INNER JOIN units un
      ON un.unitid = ar.unitid
  LEFT OUTER JOIN qualifiers ql
      ON ql.qualifier_id = ar.qualifier_id
  LEFT JOIN analytical_method_lithosurfer_digestion_mapping dm
      ON dm.method_id = am.method_id
  LEFT JOIN sample_types st
      ON st.sample_type_id = s.sample_type_id
  LEFT JOIN unitconversions uc
      ON uc.fromunitid = ar.unitid
     AND uc.tounitid = CASE anl.analysis_group
                          WHEN 'Oxide'   THEN 8
                          WHEN 'Element' THEN 6
                        END
  WHERE ar.isactive = True
    AND (p_datasource IS NULL OR l.datasource = p_datasource)
    AND (p_country    IS NULL OR c.countryname = p_country);

  GET DIAGNOSTICS v_detail_count = ROW_COUNT;

  IF p_datasource IS NULL AND p_country IS NULL THEN
    TRUNCATE TABLE lithodat_datapoint_export;
  ELSE
    DELETE FROM lithodat_datapoint_export
    WHERE (p_datasource IS NULL OR datasource = p_datasource)
      AND (p_country    IS NULL OR countryname = p_country);
  END IF;

  INSERT INTO lithodat_datapoint_export
  SELECT DISTINCT
      "datapointName",
      datapackagename,
      "sampleName",
      "referenceMaterial",
      description,
      "geochemAnalyticalType",
      "analyteMaterial",
      "analyticalSessionID",
      analyst,
      "batchID",
      "mountID",
      "analysisScale",
      mineral,
      "oxideUncertaintyType",
      "elementUncertaintyType",
      digestioncategory,
      digestionmethod,
      digestiontempcelsius,
      digestionnotes,
      quantitationlevel,
      sourcemethodcode,
      sourcemethoddesc,
      laboratorycode,
      sourceunit,
      sampleweightgm,
      analysisdate,
      sourceanalysisid,
      "Tag",
      literature,
      laboratory,
      funding,
      countryname,
      datasource,
      sample_type_id
  FROM lithodat_datapoint_concentrations
  WHERE (p_datasource IS NULL OR datasource = p_datasource)
    AND (p_country    IS NULL OR countryname = p_country);

  GET DIAGNOSTICS v_header_count = ROW_COUNT;

  RAISE NOTICE 'lithodat_datapoint_concentrations: % rows, lithodat_datapoint_export: % rows, scope: datasource=%, country=%, elapsed: %',
    v_detail_count, v_header_count, COALESCE(p_datasource,'ALL'), COALESCE(p_country,'ALL'), clock_timestamp() - v_start;
END;
$function$;
