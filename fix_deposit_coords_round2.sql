-- Round-2 coordinate correction, 2026-09-09.
-- The 2026-09-08 WFS fix used sigam:e250K.* geometry, which stores these 5 deposits with a
-- truncated (whole-number) longitude. Their SIGAM fact sheets carry the full-precision value;
-- latitude agrees exactly between both sources. Applying the fact-sheet lat/lon.
--
--   depno  name                 WFS coord (applied 09-08)   fact-sheet coord (this fix)
--   3045   Quebrada Sunchal     -24.5689, -66               -24.56888, -66.03333
--   3248   Atalaya/Las Choicas  -34.9167, -70               -34.91666, -70.28333
--   3395   Rio Hielo            -43.45,   -71               -43.45,    -71.71666
--   5080   San Martin           -32.9333, -65               -32.93333, -65.9
--   5202   El Chacho            -29.5833, -67               -29.58333, -67.66666

BEGIN;

CREATE TABLE locations_deposit_coords_bak_20260909_r2 AS
SELECT locationid, external_id, latitude, longitude, geom, now() AS backed_up_at
FROM locations
WHERE locationtype = 'DEPOSIT' AND external_id IN ('3045','3248','3395','5080','5202');

CREATE TABLE sigam_deposits_coords_bak_20260909_r2 AS
SELECT deposit_id, lat, lon, now() AS backed_up_at
FROM sigam_deposits
WHERE deposit_id IN (3045,3248,3395,5080,5202);

UPDATE locations l
SET latitude = v.lat,
    longitude = v.lon,
    geom = ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326),
    modifieddate = now()
FROM (VALUES
  ('3045', -24.56888, -66.03333),
  ('3248', -34.91666, -70.28333),
  ('3395', -43.45,    -71.71666),
  ('5080', -32.93333, -65.9),
  ('5202', -29.58333, -67.66666)
) AS v(depno, lat, lon)
WHERE l.external_id = v.depno AND l.locationtype = 'DEPOSIT';

UPDATE sigam_deposits d
SET lat = v.lat, lon = v.lon
FROM (VALUES
  (3045, -24.56888, -66.03333),
  (3248, -34.91666, -70.28333),
  (3395, -43.45,    -71.71666),
  (5080, -32.93333, -65.9),
  (5202, -29.58333, -67.66666)
) AS v(depno, lat, lon)
WHERE d.deposit_id = v.depno;

COMMIT;
