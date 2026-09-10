-- Backfill locations.divisionid for the 363 AR deposit locations that were NULL.
-- SIGAM records a province in the location text for only ~half; the fact sheet often just says
-- "Argentina". So: assign each NULL location the divisionid of the nearest AR deposit that
-- already has one (PostGIS KNN on geom - coordinates are the 2026-09-08 WFS-fixed set).
-- 2026-09-10. modifiedby = 'claude_divid_20260910'.

BEGIN;

CREATE TABLE locations_divid_bak_20260910 AS
SELECT locationid, divisionid FROM locations
WHERE locationtype = 'DEPOSIT' AND datasource LIKE 'Argentine%' AND divisionid IS NULL;

UPDATE locations l
SET divisionid = (
      SELECT l2.divisionid
      FROM locations l2
      WHERE l2.locationtype = 'DEPOSIT'
        AND l2.datasource LIKE 'Argentine%'
        AND l2.divisionid IS NOT NULL
        AND l2.locationid <> l.locationid
      ORDER BY l.geom <-> l2.geom
      LIMIT 1
    ),
    modifiedby = 'claude_divid_20260910', modifieddate = now()
WHERE l.locationtype = 'DEPOSIT'
  AND l.datasource LIKE 'Argentine%'
  AND l.divisionid IS NULL;

-- report: distribution + the low-confidence ones (nearest known deposit > 25 km away)
SELECT dv.divisionname, count(*) AS assigned
FROM locations l
JOIN locations_divid_bak_20260910 b ON b.locationid = l.locationid
JOIN divisions dv ON dv.divisionid = l.divisionid
GROUP BY 1 ORDER BY 2 DESC;

SELECT l.external_id AS depno, l.latitude, l.longitude, dv.divisionname,
       round((ST_Distance(l.geom::geography, nn.geom::geography) / 1000)::numeric, 1) AS nearest_km
FROM locations l
JOIN locations_divid_bak_20260910 b ON b.locationid = l.locationid
JOIN divisions dv ON dv.divisionid = l.divisionid
CROSS JOIN LATERAL (
  SELECT l2.geom FROM locations l2
  WHERE l2.locationtype='DEPOSIT' AND l2.datasource LIKE 'Argentine%'
    AND l2.divisionid IS NOT NULL AND l2.locationid <> l.locationid
  ORDER BY l.geom <-> l2.geom LIMIT 1
) nn
WHERE ST_Distance(l.geom::geography, nn.geom::geography) / 1000 > 25
ORDER BY nearest_km DESC;

SELECT count(*) AS ar_deposit_locations_still_null
FROM locations WHERE locationtype='DEPOSIT' AND datasource LIKE 'Argentine%' AND divisionid IS NULL;

COMMIT;
