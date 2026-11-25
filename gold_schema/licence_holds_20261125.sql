-- Licence holds, 25 Nov 2026 (interzona_cm). Withholds three sources until their licensors reply.
-- Held data go to schema licence_hold, which the app role (cm_app_readonly) cannot read, so neither the app
-- nor the assistant's ad-hoc SQL can reach them. App side: src/lib/flags.ts (SGS_SAUDI_ENABLED, WGI_ENABLED = false).
--
-- 1. SAUDI_SGS_NGD (Saudi Geological Survey stream sediments): permission covers internal use only; client-facing
--    display asked 15 Nov 2026, no reply. Results, classifications and wide-table rows moved to licence_hold;
--    1,903 samples set is_active = false.
-- 2. World Bank WGI (core.country_governance): licence for commercial display unconfirmed (emails 20 + 22 Nov).
--    Table moved to licence_hold.
-- 3. Five occurrences whose only source is Mindat.org (load tag claude_mindat_20261002): deactivated, then (same day, after an
--    eval showed ad-hoc SQL still found them) moved with their 8 commodity rows to licence_hold.occ_mindat / occ_commodities_mindat.

-- ================================ APPLY ================================
BEGIN;
CREATE SCHEMA IF NOT EXISTS licence_hold;
REVOKE ALL ON SCHEMA licence_hold FROM PUBLIC;
REVOKE ALL ON SCHEMA licence_hold FROM cm_app_readonly;

CREATE TABLE licence_hold.rc_saudi_sgs_ngd AS SELECT * FROM geochem.result_classifications_saudi_sgs_ngd;
CREATE TABLE licence_hold.ar_saudi_sgs_ngd AS SELECT * FROM geochem.analytical_results_saudi_sgs_ngd;
CREATE TABLE licence_hold.wide_saudi_sgs_ngd AS SELECT * FROM geochem.sample_chemistry_wide WHERE source_system = 'SAUDI_SGS_NGD';
DELETE FROM geochem.result_classifications_saudi_sgs_ngd;
DELETE FROM geochem.analytical_results_saudi_sgs_ngd;
DELETE FROM geochem.sample_chemistry_wide WHERE source_system = 'SAUDI_SGS_NGD';
UPDATE geochem.samples SET is_active = false, modified_by = 'licence_hold_20261125', modified_date = now()
 WHERE source_system = 'SAUDI_SGS_NGD' AND is_active;

ALTER TABLE core.country_governance SET SCHEMA licence_hold;

UPDATE core.occurrences SET is_active = false, modified_by = 'licence_hold_20261125', modified_date = now(),
       comments = comments || E'\nDEACTIVATED 2026-11-25: only source is Mindat.org, whose content is not licensed for commercial reuse; no government or literature source found for this locality.'
 WHERE created_by = 'claude_mindat_20261002' AND is_active;

REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM cm_app_readonly;
COMMIT;

-- Step 2 for the Mindat rows (applied after the first run):
BEGIN;
CREATE TABLE licence_hold.occ_mindat AS SELECT * FROM core.occurrences WHERE created_by = 'claude_mindat_20261002';
CREATE TABLE licence_hold.occ_commodities_mindat AS SELECT * FROM core.occurrence_commodities WHERE occurrence_id IN (SELECT occurrence_id FROM licence_hold.occ_mindat);
DELETE FROM core.occurrence_commodities WHERE occurrence_id IN (SELECT occurrence_id FROM licence_hold.occ_mindat);
DELETE FROM core.occurrences WHERE occurrence_id IN (SELECT occurrence_id FROM licence_hold.occ_mindat);
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM cm_app_readonly;
COMMIT;

-- ================================ ROLLBACK (run only the part being released) ================================
-- SGS Saudi:
--   BEGIN;
--   INSERT INTO geochem.analytical_results SELECT * FROM licence_hold.ar_saudi_sgs_ngd;
--   INSERT INTO geochem.result_classifications SELECT * FROM licence_hold.rc_saudi_sgs_ngd;
--   INSERT INTO geochem.sample_chemistry_wide SELECT * FROM licence_hold.wide_saudi_sgs_ngd;
--   UPDATE geochem.samples SET is_active = true, modified_by = 'licence_release', modified_date = now()
--    WHERE source_system = 'SAUDI_SGS_NGD' AND modified_by = 'licence_hold_20261125';
--   DROP TABLE licence_hold.ar_saudi_sgs_ngd, licence_hold.rc_saudi_sgs_ngd, licence_hold.wide_saudi_sgs_ngd;
--   COMMIT;
--   then set SGS_SAUDI_ENABLED = true in src/lib/flags.ts, rebuild core.country_coverage and deploy.
-- WGI:
--   ALTER TABLE licence_hold.country_governance SET SCHEMA core;
--   GRANT SELECT ON core.country_governance TO cm_app_readonly;
--   then set WGI_ENABLED = true and deploy.
-- Mindat rows (only if Mindat grants permission; better: replace with a primary source):
--   INSERT INTO core.occurrences SELECT * FROM licence_hold.occ_mindat;
--   INSERT INTO core.occurrence_commodities SELECT * FROM licence_hold.occ_commodities_mindat;
--   UPDATE core.occurrences SET is_active = true WHERE created_by = 'claude_mindat_20261002';
