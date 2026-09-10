\set O 'C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad'

-- A. deposit base: all OK fact sheets, with best coords + existing-deposit context
\copy (select f.depno, f.nombre as name, case when d.depositid is not null then 'existing' else 'new' end as origin, coalesce(l.latitude, f.lat) as lat, coalesce(l.longitude, f.lon) as lon, l.latitude as loc_lat, f.lat as ficha_lat, d.deposit_type_id as db_deposit_type_id, d.deposit_type_local, d.deposit_status, d.geological_province, d.geological_district, d.tectonic_setting, d.mineralization_style, d.deposit_form, d.alteration, d.metallogenic_association, d.associated_igneous, split_part(f.tipo_deposito,' ',1) as ficha_type_code, f.tipo_deposito as ficha_type_label, f.estado_deposito as ficha_estado, f.commodities as ficha_commodities, f.fecha_actualizacion, f.n_grades, f.n_ages, f.url from sigam_fichas f left join locations l on l.external_id = f.depno::text and l.locationtype='DEPOSIT' left join deposits d on d.locationid = l.locationid where f.is_ok order by f.depno) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_base.csv csv header

-- B. commodities for EXISTING deposits (curated)
\copy (select l.external_id::int as depno, c.commodity_name, dc.commodity_role from deposit_commodities dc join commodities c on c.commodity_id = dc.commodity_id join deposits d on d.depositid = dc.depositid join locations l on l.locationid = d.locationid where l.external_id ~ '^[0-9]+$' order by 1) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_commodities_existing.csv csv header

-- C. grades / tonnages (staging)
\copy (select depno, seq, kind, slot, commodity, value, unit_note from sigam_ficha_grades order by depno, kind, slot, seq) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_grades.csv csv header

-- D. radiometric ages (staging)
\copy (select depno, seq, age_ma, uncertainty, method, objeto_datado, concentrado, origen_roca, nombre_formal, evento, referencia from sigam_ficha_ages order by depno, seq) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_ages.csv csv header

-- E. deposit type mapping (SIGAM code -> Hofstra id)
\copy (select sigam_code, sigam_name, deposit_type_id, mapping_confidence from sigam_deposit_type_mapping order by sigam_code) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_type_mapping.csv csv header

-- F. mineralogy summary for description synthesis (existing)
\copy (select l.external_id::int as depno, string_agg(distinct dm.mineral_name_local, ', ' order by dm.mineral_name_local) as minerals from deposit_mineralogy dm join deposits d on d.depositid = dm.depositid join locations l on l.locationid = d.locationid where l.external_id ~ '^[0-9]+$' group by 1) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_mineralogy.csv csv header

-- G. references free text (existing)
\copy (select l.external_id::int as depno, d."references" as refs, d.comments from deposits d join locations l on l.locationid = d.locationid where l.external_id ~ '^[0-9]+$' and (d."references" is not null or d.comments is not null)) to C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/b7dee605-079c-4830-8d35-2b4df883cc10/scratchpad/src_refs.csv csv header
