-- WA deposit extract — Step 2e: apply review decisions (2026-09-10).
--   * DROP 5 iaml processing facilities (mills / smelter) — not deposits.
--     Dutch Miller (src_id 1101) is a real prospect, kept.
--   * ACCEPT 11 name-variant merges (X <-> "X Mine" / OCR typo). Applied as extra
--     edges in 02_edges.sql; this file only records them for the audit trail.
--   * KEEP coal "coalfield / area / composite" entries as centroid-level deposits.

BEGIN;

ALTER TABLE wa_deposits_staging
    ADD COLUMN IF NOT EXISTS excluded      boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS exclude_reason text;

UPDATE wa_deposits_staging
SET excluded = true,
    exclude_reason = 'iaml processing facility (mill/smelter), not a deposit'
WHERE wa_source = 'iaml'
  AND src_id IN ('5009','5024','5052','5095','5501');   -- Talisman/Republic/Bonanza/Red Shirt Mill, Northport Smelter

COMMIT;

\echo '--- excluded rows ---'
SELECT staging_id, src_id, site_name, exclude_reason
FROM wa_deposits_staging WHERE excluded ORDER BY src_id;
