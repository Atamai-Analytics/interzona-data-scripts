-- PHASE 0: a sample no longer needs to belong to an occurrence or a
-- sampling_line to exist -- it already carries its own point geometry,
-- which is sufficient on its own. Linkage stays fully supported when one
-- genuinely exists nearby; it is just no longer mandatory.

BEGIN;

ALTER TABLE geochem.samples DROP CONSTRAINT IF EXISTS chk_sample_parent;

-- Verify: should show NO row for chk_sample_parent any more.
SELECT conname FROM pg_constraint
WHERE conrelid = 'geochem.samples'::regclass AND contype = 'c';

-- Review the output above, then type COMMIT; or ROLLBACK;
