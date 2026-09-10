-- Reconciliation / integrity checks for 01_load.sql   (all should return 0 / match)

-- 1. source vs loaded, per table
SELECT 'argon'  t, (SELECT count(*) FROM "WA_argon_age"          WHERE age_ma>=0) src,
       (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND comments LIKE '%[WA-AGE:argon:%') loaded
UNION ALL SELECT 'uranium', (SELECT count(*) FROM "WA_uranium_age"       WHERE age_ma>=0),
       (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND comments LIKE '%[WA-AGE:uranium:%')
UNION ALL SELECT 'ft', (SELECT count(*) FROM "WA_fission_track_age" WHERE age_ma>=0),
       (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND comments LIKE '%[WA-AGE:ft:%')
UNION ALL SELECT 'other', (SELECT count(*) FROM "WA_other_analysis_age" WHERE age_ma>=0 AND analysis_type<>'36 Cl'),
       (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND comments LIKE '%[WA-AGE:other:%');

-- 2. integrity: all must be 0
SELECT
 (SELECT count(*) FROM age_measured am WHERE am.createdby='claude_wa_age_20260910'
    AND (am.observation_context<>'POINT_LOCATION' OR am.locationid IS NULL OR am.sampleid IS NOT NULL OR am.collarid IS NOT NULL)) bad_context,
 (SELECT count(*) FROM age_measured am LEFT JOIN locations l ON l.locationid=am.locationid
    WHERE am.createdby='claude_wa_age_20260910' AND l.locationid IS NULL) orphan_location,
 (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND datingmethodid=1) unknown_method,
 (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND (age_ma<0 OR age_ma IS NULL)) bad_age,
 (SELECT count(*) FROM age_measured WHERE createdby='claude_wa_age_20260910' AND age_error_ma<0) neg_error,
 (SELECT count(*) FROM locations WHERE createdby='claude_wa_age_20260910'
    AND locationid NOT IN (SELECT locationid FROM age_measured WHERE createdby='claude_wa_age_20260910')) unused_location;

-- 3. method distribution
SELECT dm.method_name, count(*)
FROM age_measured am JOIN dating_method_reference dm ON dm.dating_method_id=am.datingmethodid
WHERE am.createdby='claude_wa_age_20260910'
GROUP BY dm.method_name ORDER BY 2 DESC;
