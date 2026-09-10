-- Rollback for fix_deposit_coords_round2.sql (restores the 2026-09-08 WFS values).

BEGIN;

UPDATE locations l
SET latitude = b.latitude,
    longitude = b.longitude,
    geom = b.geom,
    modifieddate = now()
FROM locations_deposit_coords_bak_20260909_r2 b
WHERE l.locationid = b.locationid;

UPDATE sigam_deposits d
SET lat = b.lat, lon = b.lon
FROM sigam_deposits_coords_bak_20260909_r2 b
WHERE d.deposit_id = b.deposit_id;

COMMIT;

-- DROP TABLE locations_deposit_coords_bak_20260909_r2;
-- DROP TABLE sigam_deposits_coords_bak_20260909_r2;
