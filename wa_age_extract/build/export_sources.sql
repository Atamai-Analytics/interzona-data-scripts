-- WA age LithoSurfer extract — Step A: export the loaded age_measured rows.
-- Reads the criticialmineralsexp rows tagged createdby='claude_wa_age_20260910'
-- (staging/01_load.sql), joined to their locations and age_reference.
-- Output: build/age_export.csv (UTF-8).  Run: psql ... -f wa_age_extract/build/export_sources.sql
--   cwd = lithosurfer-work/    (or edit the \copy path)

\encoding UTF8

\copy (SELECT am.age_measured_id, l.external_id AS source_token, split_part(l.external_id, ':', 2) AS wa_table, split_part(l.external_id, ':', 3) AS wa_age_analysis_id, am.datingmethodid, dm.method_name, dm.method_type, am.age_ma, am.age_error_ma, am.age_qualifier, am.age_unit, am.n_grains, am.decay_constant, am.dated_unit_name, am.analytical_notes::text AS analytical_notes, am.material_dated, am.laboratory, am.lab_sample_id, am.comments, am.age_reference_id, ar.source_name AS ref_source_name, ar.citation AS ref_citation, l.locationname, l.latitude, l.longitude, l.adminlevel2 AS county, l.comments AS location_comments FROM age_measured am JOIN locations l ON l.locationid = am.locationid JOIN dating_method_reference dm ON dm.dating_method_id = am.datingmethodid LEFT JOIN age_reference ar ON ar.age_reference_id = am.age_reference_id WHERE am.createdby = 'claude_wa_age_20260910' ORDER BY l.external_id) TO 'wa_age_extract/build/age_export.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

\echo 'wa_age_extract/build/age_export.csv written'
