-- Direct SQL changes applied to interzona_cm on 2026-11-08 (record; already applied).

-- 1. New commodities for facility capacity rows that had no commodity_id (81 rows: helium 22, ferroalloys 20, iron oxide pigments 20,
--    coke 15, direct-reduced iron 4). commodity_id is an identity column (1155-1159 assigned).
INSERT INTO core.commodities (parent_commodity_id, commodity_name, commodity_symbol, commodity_category, is_critical_mineral, description, is_active, created_by, created_date)
SELECT v.parent, v.name, v.sym, v.cat, v.crit, v.descr, true, 'claude_commodity_additions_20261108', now()
FROM (VALUES
 (NULL::int, 'Helium', 'He'::varchar, 'Non-Metal', true, 'Helium gas, recovered from natural gas (US helium plants). On the EU critical raw materials list.'),
 (1111, 'Ferroalloys', NULL, 'Metal', false, 'Iron alloys with Mn, Si, Cr and other metals (ferromanganese, ferrosilicon, ferrochromium ...); a processed product.'),
 (1055, 'Iron Oxide Pigments', NULL, 'Industrial Mineral', false, 'Natural and synthetic iron oxide pigments; a processed product.'),
 (961, 'Coke', NULL, 'Carbonaceous Material', false, 'Metallurgical coke made from coking coal; a processed product.'),
 (1111, 'Direct-Reduced Iron', 'DRI', 'Metal', false, 'Direct-reduced (sponge) iron and hot briquetted iron; a processed product.')
) v(parent, name, sym, cat, crit, descr)
WHERE NOT EXISTS (SELECT 1 FROM core.commodities c WHERE c.commodity_name = v.name);
UPDATE core.facility_capacity f SET commodity_id = c.commodity_id FROM core.commodities c
WHERE f.commodity_id IS NULL AND c.created_by = 'claude_commodity_additions_20261108'
  AND c.commodity_name = CASE f.commodity_name WHEN 'Helium' THEN 'Helium' WHEN 'Ferroalloys' THEN 'Ferroalloys' WHEN 'Iron oxide pigments' THEN 'Iron Oxide Pigments'
                                               WHEN 'Coke' THEN 'Coke' WHEN 'Direct-reduced iron' THEN 'Direct-Reduced Iron' END;
-- rollback: UPDATE core.facility_capacity SET commodity_id = NULL WHERE commodity_id BETWEEN 1155 AND 1159; DELETE FROM core.commodities WHERE created_by = 'claude_commodity_additions_20261108';

-- 2. Austrade Prospectus midstream entries: inferred stage (Austrade publishes only 'Midstream').
ALTER TABLE core.project_prospectus ADD COLUMN IF NOT EXISTS status_inferred varchar(40), ADD COLUMN IF NOT EXISTS status_inferred_basis text;
-- 36 rows (prospectus_project_id 59-94) set from each project's description; values and basis phrases are in the table
-- (status_inferred_basis ends '(inferred by Interzona from the Prospectus description, 8 Nov 2026; Austrade gives only "Midstream")').
-- rollback: UPDATE core.project_prospectus SET status_inferred = NULL, status_inferred_basis = NULL WHERE stage = 'midstream';

-- 3. Curated lithium / MRDS lithium follow-ups
--    Kamativi (378288) and Zhabuye (396703): Li set PRIMARY, other commodities SECONDARY.
--    Curated rows (created_by claude_li_curated_20261108): comments restructured to lead with 'Reference: <url> (dated ...)'.
--    MRDS Li notes restructured to 'Lithium added 2026-11-08 (not in MRDS). Reference: <url> (dated ...): <text>'.
--    Big Sandy (curated): position set to the Wikipedia project coordinates (34.704297, -113.578503), position_accuracy NULL.
