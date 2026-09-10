-- LithoSurfer deposit extract — source export (v2, DB-driven).
-- Run after Phase 1. Reads the cleaned criticialmineralsexp master.
-- Usage:  sed 's#OUTDIR#/abs/path#' export_sources.sql | psql -f -
\set b   :dir '/v2_base.csv'
\set c   :dir '/v2_commodities.csv'
\set e   :dir '/v2_endowment.csv'
\set a   :dir '/v2_ages.csv'
\set m   :dir '/v2_mineralogy.csv'

\copy (select l.external_id::int as depno, d.depositid, l.locationname as name, l.latitude as lat, l.longitude as lon, d.deposit_type_id, dt.deposit_type_name, d.deposit_type_local, d.deposit_status, d.size_category, d.geological_province, d.geological_district, d.tectonic_setting, d.mineralization_style, d.deposit_form, d.alteration, d.metallogenic_association, d.associated_igneous, f.tipo_deposito as ficha_type_label, f.fecha_actualizacion, l.datasource_url as url from deposits d join locations l on l.locationid = d.locationid and l.locationtype='DEPOSIT' left join deposit_types dt on dt.deposit_type_id = d.deposit_type_id left join sigam_fichas f on f.depno = l.external_id::int where l.external_id ~ '^[0-9]+$' order by depno) to 'OUTDIR/v2_base.csv' csv header

\copy (select l.external_id::int as depno, c.commodity_id, c.commodity_name, dc.commodity_role from deposit_commodities dc join commodities c on c.commodity_id = dc.commodity_id join deposits d on d.depositid = dc.depositid join locations l on l.locationid = d.locationid where l.external_id ~ '^[0-9]+$' order by 1) to 'OUTDIR/v2_commodities.csv' csv header

\copy (select l.external_id::int as depno, e.commodity_id, c.commodity_name, e.commodity_raw, e.data_type, e.measure, e.value_num, e.value_text, e.unit, e.seq from deposit_endowment e join deposits d on d.depositid = e.depositid join locations l on l.locationid = d.locationid left join commodities c on c.commodity_id = e.commodity_id order by 1, e.commodity_raw, e.data_type, e.measure, e.seq) to 'OUTDIR/v2_endowment.csv' csv header

\copy (select l.external_id::int as depno, dm.method_name as method, at.age_type_name, a.age_ma, a.age_error_ma, a.material_dated, a.mineral, a.age_interpretation, a.reference, a.comments from age_measured a join locations l on l.locationid = a.locationid and l.locationtype='DEPOSIT' join dating_method_reference dm on dm.dating_method_id = a.datingmethodid left join age_type_reference at on at.age_type_id = a.age_type_id where a.createdby = 'claude_sigam_20260910' order by 1) to 'OUTDIR/v2_ages.csv' csv header

\copy (select l.external_id::int as depno, string_agg(distinct dmn.mineral_name_local, ', ' order by dmn.mineral_name_local) as minerals from deposit_mineralogy dmn join deposits d on d.depositid = dmn.depositid join locations l on l.locationid = d.locationid where l.external_id ~ '^[0-9]+$' group by 1) to 'OUTDIR/v2_mineralogy.csv' csv header
