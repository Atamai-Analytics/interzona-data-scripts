-- =====================================================================
-- WA_*_age  ->  native age model  (criticialmineralsexp)
-- Scope: RADIOMETRIC ONLY  (argon, uranium, fission track, Rb-Sr/Sm-Nd)
-- Excluded: WA_carbon_age, WA_luminescence_age, WA_fossil_age, 36Cl rows
-- Tag: createdby = 'claude_wa_age_20260910'   (rollback.sql keys off this)
-- Prereq: schema changes S1-S4 applied (age_reference table, age_measured
--         S2 columns + CHECKs, dating_method_reference ids 20-27).
-- Idempotent: each step guards with NOT EXISTS on the tag / external_id /
--             bracketed [WA-AGE:...] token, so a partial re-run is safe.
-- =====================================================================

-- ---------------------------------------------------------------------
-- STEP 1  age_reference  (one row per distinct db_source)
-- ---------------------------------------------------------------------
INSERT INTO age_reference (source_name, citation, comments, createdby)
SELECT s.db_source,
       CASE s.db_source
         WHEN 'National Geochronological Database'
           THEN 'U.S. Geological Survey National Geochronological Database (NGDB)'
         WHEN 'Washington State Division of Geology and Earth Resources 1:100,000-scale digital data'
           THEN 'Washington Division of Geology and Earth Resources, Surface geology 1:100,000-scale GIS data'
         ELSE s.db_source
       END,
       'WA_*_age.db_source; per-record ids kept in age_measured.comments / locations.legacy_id',
       'claude_wa_age_20260910'
FROM (
  SELECT db_source FROM "WA_argon_age"
  UNION SELECT db_source FROM "WA_uranium_age"
  UNION SELECT db_source FROM "WA_fission_track_age"
  UNION SELECT db_source FROM "WA_other_analysis_age"
) s
WHERE s.db_source IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM age_reference r
                  WHERE r.source_name = s.db_source AND r.source_record_id IS NULL);

-- ---------------------------------------------------------------------
-- STEP 2  locations  (one SURFACE point per in-scope age row)
--   external_id = legacy_id-style token  'WA-AGE:<tbl>:<age_analysis_id>'
-- ---------------------------------------------------------------------
WITH src AS (
  SELECT 'argon'::text tbl, age_analysis_id, latitude, longitude, geologic_unit_name,
         location_description, location_quality, township, range, section, section_part,
         county_name, db_source_record_id
  FROM "WA_argon_age"           WHERE age_ma IS NOT NULL AND age_ma >= 0
  UNION ALL
  SELECT 'uranium', age_analysis_id, latitude, longitude, geologic_unit_name,
         location_description, location_quality, township, range, section, section_part,
         county_name, db_source_record_id
  FROM "WA_uranium_age"         WHERE age_ma IS NOT NULL AND age_ma >= 0
  UNION ALL
  SELECT 'ft', age_analysis_id, latitude, longitude, geologic_unit_name,
         location_description, location_quality, township, range, section, section_part,
         county_name, db_source_record_id
  FROM "WA_fission_track_age"   WHERE age_ma IS NOT NULL AND age_ma >= 0
  UNION ALL
  SELECT 'other', age_analysis_id, latitude, longitude, geologic_unit_name,
         location_description, location_quality, township, range, section, section_part,
         county_name, db_source_record_id
  FROM "WA_other_analysis_age"  WHERE age_ma IS NOT NULL AND age_ma >= 0
                                 AND analysis_type <> '36 Cl'
)
INSERT INTO locations (locationcode, locationname, locationtype, latitude, longitude,
                       srid_geographic, countryid, divisionid, adminlevel2,
                       datasource, external_id, legacy_id, comments,
                       createdby, isactive)
SELECT
  'WA-AGE:'||s.tbl||':'||s.age_analysis_id,
  left(coalesce(nullif(s.geologic_unit_name,''), nullif(s.location_description,''),
               'WA geochronology site'), 255),
  'SURFACE',
  s.latitude, s.longitude, 4326,
  246,                              -- United States
  48,                               -- Washington (US-WA)
  nullif(trim(s.county_name), ''),  -- county -> adminlevel2
  'Washington DGER - geochronology compilation',
  'WA-AGE:'||s.tbl||':'||s.age_analysis_id,
  left(s.db_source_record_id, 100),
  nullif(concat_ws('; ',
     nullif(concat_ws(' ', s.township, s.range, 'sec '||s.section, s.section_part), ''),
     nullif(s.location_description,''),
     nullif(s.location_quality,'')
  ), ''),
  'claude_wa_age_20260910',
  true
FROM src s
WHERE NOT EXISTS (SELECT 1 FROM locations l
                  WHERE l.external_id = 'WA-AGE:'||s.tbl||':'||s.age_analysis_id);

-- ---------------------------------------------------------------------
-- STEP 3  age_measured  (POINT_LOCATION, locationid only)
-- ---------------------------------------------------------------------
WITH src AS (
  SELECT 'argon'::text tbl, a.age_analysis_id, a.age_ma, a.error_ma, a.age_modifier,
         left(a.material_dated,100) material_dated, a.geologic_unit_name, a.decay_constant,
         a.analytical_data, NULL::text grain_count, left(a.lab_id,200) lab_id,
         left(a.sample_id,100) sample_id, a.age_comments, a.original_comments, a.db_source,
         CASE a.analysis_type
           WHEN 'K-Ar' THEN 2 WHEN 'Ar-Ar' THEN 3
           WHEN '40Ar/36Ar-40K/36Ar isochron' THEN 20 WHEN 'Laser-Ar' THEN 21
           ELSE 1 END dm
  FROM "WA_argon_age" a
  UNION ALL
  SELECT 'uranium', u.age_analysis_id, u.age_ma, u.error_ma, u.age_modifier,
         left(u.material_dated,100), u.geologic_unit_name, u.decay_constant,
         u.analytical_data, NULL, left(u.lab_id,200), left(u.sample_id,100),
         u.age_comments, u.original_comments, u.db_source,
         CASE u.analysis_type
           WHEN '206 Pb/238 U' THEN 11 WHEN '207 Pb/235 U' THEN 12
           WHEN '207 Pb/206 Pb' THEN 13 WHEN '208 Pb/232 Th' THEN 14
           WHEN 'U-Pb' THEN 15 WHEN 'Pb-Alpha' THEN 22
           WHEN '206 Pb/238 U: SIMS' THEN 16 WHEN 'U-Pb: LA-ICP-MS' THEN 27
           WHEN 'U-Th-Pb' THEN 26 ELSE 1 END
  FROM "WA_uranium_age" u
  UNION ALL
  SELECT 'ft', f.age_analysis_id, f.age_ma, f.error_ma, f.age_modifier,
         left(f.material_dated,100), f.geologic_unit_name, f.decay_constant,
         NULL, f.grain_count, left(f.lab_id,200), left(f.sample_id,100),
         f.age_comments, f.original_comments, f.db_source, 10
  FROM "WA_fission_track_age" f
  UNION ALL
  SELECT 'other', o.age_analysis_id, o.age_ma, o.error_ma, NULL,
         left(o.material_dated,100), o.geologic_unit_name, o.decay_constant,
         o.analytical_data, NULL, left(o.lab_id,200), left(o.sample_id,100),
         o.age_comments, o.original_comments, o.db_source,
         CASE o.analysis_type WHEN 'Rb-Sr' THEN 5 WHEN 'Sm-Nd' THEN 17 ELSE 1 END
  FROM "WA_other_analysis_age" o
  WHERE o.analysis_type <> '36 Cl'
)
INSERT INTO age_measured (
  datingmethodid, observation_context, locationid,
  age_ma, age_error_ma, age_qualifier, age_unit,
  n_grains, decay_constant, dated_unit_name, analytical_notes,
  material_dated, laboratory, lab_sample_id, age_reference_id,
  comments, isactive, createdby
)
SELECT
  s.dm, 'POINT_LOCATION', l.locationid,
  s.age_ma,
  CASE WHEN s.error_ma IS NULL OR s.error_ma < 0 THEN NULL ELSE s.error_ma END,
  CASE s.age_modifier WHEN '>' THEN '>' WHEN '>/=' THEN '>=' WHEN '<' THEN '<'
                      WHEN '</=' THEN '<=' WHEN '~' THEN '~' ELSE NULL END,
  'Ma',
  (regexp_match(coalesce(s.grain_count,''), '^\s*(\d+)'))[1]::int,
  s.decay_constant,
  left(nullif(s.geologic_unit_name,''), 255),
  NULLIF(
    coalesce(CASE WHEN nullif(s.analytical_data,'') IS NOT NULL
                  THEN jsonb_build_object('wa_analytical_data', s.analytical_data) ELSE '{}'::jsonb END, '{}'::jsonb)
    || coalesce(CASE WHEN nullif(s.grain_count,'') IS NOT NULL
                  THEN jsonb_build_object('wa_grain_count', s.grain_count) ELSE '{}'::jsonb END, '{}'::jsonb),
    '{}'::jsonb),
  s.material_dated, s.lab_id, s.sample_id, r.age_reference_id,
  nullif(concat_ws(' | ',
     '[WA-AGE:'||s.tbl||':'||s.age_analysis_id||']',
     nullif(s.age_comments,''),
     nullif(s.original_comments,'')
  ), ''),
  true,
  'claude_wa_age_20260910'
FROM src s
JOIN locations l
  ON l.external_id = 'WA-AGE:'||s.tbl||':'||s.age_analysis_id
 AND l.createdby   = 'claude_wa_age_20260910'
LEFT JOIN age_reference r
  ON r.source_name = s.db_source AND r.source_record_id IS NULL
 AND r.createdby   = 'claude_wa_age_20260910'
WHERE s.age_ma IS NOT NULL AND s.age_ma >= 0
  AND NOT EXISTS (
    SELECT 1 FROM age_measured am
    WHERE am.createdby = 'claude_wa_age_20260910'
      AND am.comments LIKE '%[WA-AGE:'||s.tbl||':'||s.age_analysis_id||']%'
  );
