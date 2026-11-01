#!/bin/bash
# usage: nsw_dedupe_batch.sh LO HI   (sampleid range [LO, HI)) - one transaction per call
LO=$1; HI=$2
cd /c/Users/dean/claude_lithosurfer/lithosurfer-work
set -a; . ./.env; set +a
export PGPASSWORD="$LITHODAT_DB_PASSWORD"
OUT="C:/Users/dean/claude_lithosurfer/lithosurfer-work/finland_fix_backups/nsw_dedupe/batch_${LO}_$(date +%H%M%S).csv"
TAG="claude_nsw_dedupe_20261009"
SQLF="$(mktemp --suffix=.sql)"
cat > "$SQLF" <<SQL
\set ON_ERROR_STOP on
SET work_mem = '256MB';
BEGIN;
CREATE TEMP TABLE d ON COMMIT DROP AS
WITH grp AS (
  SELECT sampleid, package_id, analyte_id, unitid, coalesce(qualifier_id, 0) AS q, min(result_id) AS keep_id
    FROM analytical_results
   WHERE isactive AND sampleid >= $LO AND sampleid < $HI AND sampleid <= 2377092
   GROUP BY sampleid, package_id, analyte_id, unitid, coalesce(qualifier_id, 0)
  HAVING count(*) > 1 AND count(DISTINCT row(value, report_number, date_analysed, lower_detection_limit, upper_detection_limit)) = 1)
SELECT ar.result_id, grp.keep_id
  FROM analytical_results ar JOIN grp ON ar.sampleid = grp.sampleid AND ar.package_id = grp.package_id AND ar.analyte_id = grp.analyte_id AND ar.unitid = grp.unitid AND coalesce(ar.qualifier_id, 0) = grp.q
 WHERE ar.isactive AND ar.sampleid >= $LO AND ar.sampleid < $HI AND ar.result_id <> grp.keep_id;
\copy (SELECT result_id, keep_id FROM d ORDER BY result_id) TO '$OUT' CSV HEADER
DO \$\$ DECLARE n int; u int; l int; c int; rem int; BEGIN
  SELECT count(*) INTO n FROM d;
  UPDATE analytical_results ar SET isactive = false, modified_by = '$TAG', modified_date = CURRENT_TIMESTAMP FROM d WHERE ar.result_id = d.result_id AND ar.isactive;
  GET DIAGNOSTICS u = ROW_COUNT;
  IF u <> n THEN RAISE EXCEPTION 'updated % of %', u, n; END IF;
  INSERT INTO lithodat_isactive_updates_log (result_id, old_isactive, new_isactive, rule_code, reason, updated_by)
  SELECT result_id, true, false, 'DUP-IDENTICAL-BLOCK', 'NSW assay block loaded more than once: identical value/report/date/limits in the same sample+package+analyte+unit; lowest result_id kept', '$TAG' FROM d;
  GET DIAGNOSTICS l = ROW_COUNT;
  IF l <> n THEN RAISE EXCEPTION 'logged % of %', l, n; END IF;
  DELETE FROM lithodat_datapoint_concentrations dc USING d WHERE dc.result_id = d.result_id;
  GET DIAGNOSTICS c = ROW_COUNT;
  SELECT count(*) INTO rem FROM (SELECT 1 FROM analytical_results WHERE isactive AND sampleid >= $LO AND sampleid < $HI AND sampleid <= 2377092 GROUP BY sampleid, package_id, analyte_id, unitid, coalesce(qualifier_id, 0) HAVING count(*) > 1 AND count(DISTINCT row(value, report_number, date_analysed, lower_detection_limit, upper_detection_limit)) = 1) x;
  IF rem <> 0 THEN RAISE EXCEPTION '% identical duplicate groups remain in range - rolling back', rem; END IF;
  RAISE NOTICE 'BATCH $LO-$HI: deactivated %, logged %, conc rows removed %', n, l, c;
END \$\$;
COMMIT;
SQL
"/c/Program Files/QGIS 4.0.1/bin/psql.exe" -h "$LITHODAT_DB_HOST" -p "${LITHODAT_DB_PORT:-5432}" -U "$LITHODAT_DB_USER" -d "$LITHODAT_DB_NAME" -P pager=off -q -f "$SQLF" 2>&1 | grep -E "BATCH|ERROR" || echo "BATCH $LO-$HI: no output (error?)"
rm -f "$SQLF"
