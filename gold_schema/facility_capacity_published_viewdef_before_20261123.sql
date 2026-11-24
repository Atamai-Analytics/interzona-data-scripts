CREATE OR REPLACE VIEW core.facility_capacity_published AS
 SELECT facility_capacity_id,
    occurrence_id,
    commodity_id,
    commodity_name,
    commodity_group,
    feature_type,
    facility_stage,
    phase,
    product_form,
    product_descriptor,
    annual_capacity,
    capacity_unit,
    capacity_basis,
    capacity_notes,
    shared_with_rows,
    facility_status,
    multiple_commodities,
    multiple_products,
    data_year,
    source_system,
    source_row_id,
    footnote,
    source_urls,
    is_active,
    created_by,
    created_date,
    cluster_id,
    is_2024_anchor,
    usgs_facility_id,
    facility_key,
    published_product,
    stage_group,
    measure,
    capacity_as_published,
    shared_capacity_note,
    release,
    NOT (EXISTS ( SELECT 1
           FROM core.facility_superseded s
          WHERE s.facility_capacity_id = v.facility_capacity_id)) AS is_latest_year
   FROM ( SELECT fc.facility_capacity_id,
            fc.occurrence_id,
            fc.commodity_id,
            fc.commodity_name,
            fc.commodity_group,
            fc.feature_type,
            fc.facility_stage,
            fc.phase,
            fc.product_form,
            fc.product_descriptor,
            fc.annual_capacity,
            fc.capacity_unit,
            fc.capacity_basis,
            fc.capacity_notes,
            fc.shared_with_rows,
            fc.facility_status,
            fc.multiple_commodities,
            fc.multiple_products,
            fc.data_year,
            fc.source_system,
            fc.source_row_id,
            fc.footnote,
            fc.source_urls,
            fc.is_active,
            fc.created_by,
            fc.created_date,
            cl.cluster_id,
            fc.source_system::text = 'USGS_MYB2024'::text AND o.position_accuracy::text IS DISTINCT FROM 'TOWN_CENTROID'::text AS is_2024_anchor,
                CASE
                    WHEN fc.source_system::text = 'USGS_US_FACILITIES'::text THEN 'US-site-'::text || fc.occurrence_id
                    WHEN fc.source_system::text = 'USGS_MYB2024'::text THEN regexp_replace(fc.source_row_id::text, '^FAC_|_[0-9]+$'::text, ''::text, 'g'::text)
                    ELSE split_part(fc.source_row_id::text, '-'::text, 1)
                END AS usgs_facility_id,
                CASE
                    WHEN fc.source_system::text = 'USGS_US_FACILITIES'::text THEN 'US:'::text || fc.occurrence_id
                    WHEN fc.source_system::text = 'USGS_MYB2024'::text THEN (regexp_replace(fc.source_row_id::text, '^FAC_|_[0-9]+$'::text, ''::text, 'g'::text) || ':'::text) || fc.occurrence_id
                    ELSE (split_part(fc.source_row_id::text, '-'::text, 1) || ':'::text) || fc.occurrence_id
                END AS facility_key,
            COALESCE(NULLIF(TRIM(BOTH FROM concat_ws(' '::text, fc.product_form, fc.product_descriptor)), ''::text), 'product not stated'::text) AS published_product,
                CASE
                    WHEN fc.feature_type::text ~~* 'Brine%'::text OR fc.feature_type::text = 'B'::text THEN 'Brine operation'::character varying
                    WHEN fc.facility_stage::text = 'Mine'::text OR fc.facility_stage IS NULL AND (fc.feature_type::text ~~* 'Mines%'::text OR fc.feature_type::text = 'M'::text) THEN 'Mine'::character varying
                    WHEN fc.facility_stage::text = ANY (ARRAY['Smelter'::character varying, 'Refinery'::character varying, 'Concentrator'::character varying]::text[]) THEN fc.facility_stage
                    WHEN fc.facility_stage::text ~~* '%Smelter%'::text THEN 'Smelter'::character varying
                    ELSE 'Other processing plant'::character varying
                END AS stage_group,
                CASE
                    WHEN fc.capacity_basis::text = 'ELEMENTAL_CONTENT'::text THEN 'contained metal/element content'::text
                    WHEN fc.capacity_basis::text = 'COMPOUND_WEIGHT'::text THEN 'weight of the compound'::text
                    WHEN fc.capacity_basis::text = 'GROSS_WEIGHT'::text THEN 'gross weight of the product, not metal content'::text
                    WHEN concat_ws(' '::text, fc.product_form, fc.product_descriptor) ~* '\mcontent\M'::text THEN 'contained metal/element content'::text
                    WHEN fc.product_form ~* '(ore|concentrat|\mmine\M|crude|run.of.mine)'::text THEN 'ore or concentrate tonnage, not metal content'::text
                    WHEN fc.product_form ~* '(metal|cathode|refined|ingot|blister|anode|bullion|pig iron|ferro|steel|content|matte)'::text THEN 'metal, alloy, matte or refined product'::text
                    WHEN fc.product_form IS NULL THEN 'measure not stated by USGS'::text
                    ELSE 'measure not stated by USGS'::text
                END AS measure,
                CASE
                    WHEN fc.annual_capacity IS NULL THEN 'capacity not published'::text
                    ELSE (((to_char(fc.annual_capacity, 'FM999,999,999,990.##'::text) || ' '::text) ||
                    CASE lower(TRIM(BOTH FROM fc.capacity_unit))
                        WHEN 'mt'::text THEN 't'::text
                        WHEN 'metric tons'::text THEN 't'::text
                        WHEN ''::text THEN '(unit not stated)'::text
                        ELSE COALESCE(TRIM(BOTH FROM fc.capacity_unit), '(unit not stated)'::text)
                    END) || ' - '::text) || COALESCE(NULLIF(TRIM(BOTH FROM concat_ws(' '::text, fc.product_form, fc.product_descriptor)), ''::text), 'product not stated'::text)
                END AS capacity_as_published,
                CASE
                    WHEN fc.shared_with_rows IS NOT NULL AND cardinality(fc.shared_with_rows) > 0 THEN ('one capacity shared by facilities '::text || replace(array_to_string(fc.shared_with_rows, ', '::text), '***'::text, ''::text)) || ' - count it once'::text
                    ELSE NULL::text
                END AS shared_capacity_note,
                CASE fc.source_system
                    WHEN 'USGS_LAC_GIS'::text THEN 'USGS Latin America and Caribbean mineral-industry GIS compilation'::character varying
                    WHEN 'USGS_SWASIA_GIS'::text THEN 'USGS Southwest Asia mineral-industry GIS compilation'::character varying
                    WHEN 'USGS_INDOPAC_GIS'::text THEN 'USGS Indo-Pacific mineral-industry GIS compilation'::character varying
                    WHEN 'USGS_CHINA_GIS'::text THEN 'USGS China mineral-industry GIS compilation'::character varying
                    WHEN 'USGS_AFRICA_GIS'::text THEN 'USGS Africa mineral-industry GIS compilation'::character varying
                    WHEN 'USGS_US_FACILITIES'::text THEN 'USGS U.S. mineral facilities'::character varying
                    WHEN 'USGS_MYB2024'::text THEN 'USGS 2024 Minerals Yearbook global facilities table'::character varying
                    ELSE fc.source_system
                END::text ||
                CASE
                    WHEN fc.source_system::text = 'USGS_US_FACILITIES'::text THEN ''::text
                    ELSE COALESCE((' (Minerals Yearbook '::text || fc.data_year) || ' data)'::text, ''::text)
                END AS release
           FROM core.facility_capacity fc
             JOIN core.occurrences o ON o.occurrence_id = fc.occurrence_id
             LEFT JOIN core.facility_site_clusters cl ON cl.occurrence_id = fc.occurrence_id
          WHERE fc.is_active IS DISTINCT FROM false) v;