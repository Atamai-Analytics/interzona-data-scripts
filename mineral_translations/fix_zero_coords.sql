-- Fix the 2 AR deposit locations with a zero coordinate axis (WFS-sourced). 2026-09-10.
-- 25722 Ischilín: lat was 0 -> -30.6393 (Córdoba).  26259 El Desecho: lon was 0 -> -65.8879 (Salta).
-- Backup: locations_zerocoord_bak_20260910. Rollback: restore lat/lon/geom from that table.
BEGIN;
UPDATE locations SET latitude=-30.6393, longitude=-64.3317, modifiedby='claude_zerocoord_20260910', modifieddate=now()
WHERE locationtype='DEPOSIT' AND external_id='25722' AND latitude=0;
UPDATE locations SET latitude=-25.6661, longitude=-65.8879, modifiedby='claude_zerocoord_20260910', modifieddate=now()
WHERE locationtype='DEPOSIT' AND external_id='26259' AND longitude=0;
COMMIT;
