-- =====================================================================
-- WA_fossil_age  ->  age_stratigraphic  (criticialmineralsexp)
-- Free-text reported_age -> stratigraphic_age_id resolved offline in
-- build/parse_ages.py (100% of 242 distinct strings; see build/_coverage.json).
-- Tag: created_by = 'claude_wa_fossil_20260911'
-- Prereq: S4 columns on age_stratigraphic (age_reference_id, age_type_id,
--         fossil_taxa, reported_age_raw) already applied.
-- Idempotent: guards on external_id / created_by + [WA-AGE:fossil:...] token.
-- =====================================================================

-- STEP 0: load the resolved crosswalk (build/build_crosswalk.py output)
DROP TABLE IF EXISTS wa_fossil_age_crosswalk;
CREATE TABLE wa_fossil_age_crosswalk (
  reported_age          text PRIMARY KEY,
  stratigraphic_age_id  integer NOT NULL REFERENCES stratigraphic_age_reference,
  matched_age_name      text,
  confidence_level      varchar(20),
  match_method          text
);
\copy wa_fossil_age_crosswalk FROM 'wa_fossil_extract/build/crosswalk_reported_age.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

-- STEP 1: locations (one SURFACE point per fossil-age row)
INSERT INTO locations (locationcode, locationname, locationtype, latitude, longitude,
                       srid_geographic, countryid, divisionid, adminlevel2,
                       datasource, external_id, legacy_id, comments,
                       createdby, isactive)
SELECT
  'WA-AGE:fossil:'||f.age_analysis_id,
  left(coalesce(nullif(f.geologic_unit_name,''), nullif(f.location_description,''),
               'WA fossil locality'), 255),
  'SURFACE',
  f.latitude, f.longitude, 4326,
  246, 48, nullif(trim(f.county_name), ''),
  'Washington DGER - geochronology compilation',
  'WA-AGE:fossil:'||f.age_analysis_id,
  left(f.db_source_record_id, 100),
  nullif(concat_ws('; ',
     nullif(concat_ws(' ', f.township, f.range, 'sec '||f.section, f.section_part), ''),
     nullif(f.location_description,''),
     nullif(f.location_quality,'')
  ), ''),
  'claude_wa_fossil_20260911',
  true
FROM "WA_fossil_age" f
WHERE NOT EXISTS (SELECT 1 FROM locations l
                  WHERE l.external_id = 'WA-AGE:fossil:'||f.age_analysis_id);

-- STEP 2: age_stratigraphic
INSERT INTO age_stratigraphic (
  stratigraphic_age_id, observation_context, locationid,
  confidence_level, determination_method, comments,
  created_by, created_date, is_active,
  age_reference_id, age_type_id, fossil_taxa, reported_age_raw
)
SELECT
  xw.stratigraphic_age_id, 'POINT_LOCATION', l.locationid,
  xw.confidence_level,
  left('Fossil assemblage: '||coalesce(nullif(f.fossil_type,''),'unspecified'), 100),
  nullif(concat_ws(' | ',
     '[WA-AGE:fossil:'||f.age_analysis_id||']',
     nullif(f.age_comments,''),
     nullif(f.original_comments,''),
     nullif(f.additional_comments,'')
  ), ''),
  'claude_wa_fossil_20260911', now(), true,
  ar.age_reference_id,
  22,                                  -- age_type_reference: 'Stratigraphic'
  f.fossil_type,
  f.reported_age
FROM "WA_fossil_age" f
JOIN wa_fossil_age_crosswalk xw ON xw.reported_age = f.reported_age
JOIN locations l
  ON l.external_id = 'WA-AGE:fossil:'||f.age_analysis_id
 AND l.createdby   = 'claude_wa_fossil_20260911'
LEFT JOIN age_reference ar
  ON ar.source_name = f.db_source AND ar.source_record_id IS NULL
WHERE NOT EXISTS (
  SELECT 1 FROM age_stratigraphic ags
  WHERE ags.created_by = 'claude_wa_fossil_20260911'
    AND ags.comments LIKE '%[WA-AGE:fossil:'||f.age_analysis_id||']%'
);
