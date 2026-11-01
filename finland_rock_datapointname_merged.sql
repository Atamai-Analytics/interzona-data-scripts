-- Populate datapointname_merged for GTK: Finland Rock Samples with a
-- unique, human-readable data-point name.
--
-- Current lithodat_datapoint_export."datapointName" is already unique for
-- this subset (verified: 48,341 distinct / 48,341 rows), but it's built
-- from an opaque internal numeric fragment (not sourceanalysisid, which is
-- null here) plus a short method-code suffix, e.g. "3786560_108_ppm//AA" -
-- not traceable to anything recognisable.
--
-- New formula: "<sampleName> <sourcemethodcode> [<sourceunit>]"
--   - verified unique: sampleName + sourcemethodcode + sourceunit has
--     48,341 distinct combos for the same 48,341 rows (sampleName +
--     sourcemethodcode alone only has 42,300 - unit is required)
--   - laboratorycode is constant ("GTK") for this subset, so it adds no
--     disambiguating value and is left out
--   - sourcemethodcode and sourceunit are both 100% non-null for this
--     subset, so no COALESCE is needed
--
-- Run this against lithodat_datapoint_export (and lithodat_datapoint_concentrations
-- if datapointname_merged needs to stay in sync there too - check whether
-- that table already carries a Finland Rock subset before running there).

UPDATE lithodat_datapoint_export
SET datapointname_merged = "sampleName" || ' ' || sourcemethodcode || ' [' || sourceunit || ']'
WHERE datasource = 'Geological Survey of Finland'
  AND countryname = 'Finland'
  AND sample_type_id = 31;

-- lithodat_datapoint_concentrations is the analyte-level table underneath
-- the above (one row per element/oxide result rather than per data point -
-- 525,333 rows for the same 6,054 samples, ~10.9 analytes per data point).
-- Verified against the live data: grouping by the same
-- sampleName+sourcemethodcode+sourceunit formula on this table also yields
-- exactly 48,341 distinct groups (matching lithodat_datapoint_export
-- one-for-one), with 0 nulls in sourcemethodcode/sourceunit here too - the
-- same UPDATE is safe to run unmodified.

UPDATE lithodat_datapoint_concentrations
SET datapointname_merged = "sampleName" || ' ' || sourcemethodcode || ' [' || sourceunit || ']'
WHERE datasource = 'Geological Survey of Finland'
  AND countryname = 'Finland'
  AND sample_type_id = 31;

-- Sanity checks to run after the update:

-- 1. Row counts updated should be 48341 (lithodat_datapoint_export) and
--    525333 (lithodat_datapoint_concentrations) - or current row counts
--    for this filter if the source data has changed since this was written.
-- 2. No collisions in lithodat_datapoint_export:
--    SELECT datapointname_merged, count(*)
--    FROM lithodat_datapoint_export
--    WHERE datasource = 'Geological Survey of Finland' AND countryname = 'Finland' AND sample_type_id = 31
--    GROUP BY 1 HAVING count(*) > 1;
--    -- should return 0 rows
-- 3. No nulls left in either table:
--    SELECT count(*) FROM lithodat_datapoint_export
--    WHERE datasource = 'Geological Survey of Finland' AND countryname = 'Finland' AND sample_type_id = 31
--      AND datapointname_merged IS NULL;
--    SELECT count(*) FROM lithodat_datapoint_concentrations
--    WHERE datasource = 'Geological Survey of Finland' AND countryname = 'Finland' AND sample_type_id = 31
--      AND datapointname_merged IS NULL;
--    -- both should be 0
-- 4. The two tables agree - every distinct datapointname_merged value in
--    lithodat_datapoint_export should have a matching set of rows in
--    lithodat_datapoint_concentrations with the same value:
--    SELECT count(distinct datapointname_merged) FROM lithodat_datapoint_concentrations
--    WHERE datasource = 'Geological Survey of Finland' AND countryname = 'Finland' AND sample_type_id = 31;
--    -- should be 48341, matching lithodat_datapoint_export's distinct count
