"""Creates core.facility_capacity_published: core.facility_capacity plus ready-made text columns that say exactly what each published capacity
figure is, so answers cannot relabel ore tonnage as metal or add up a figure USGS repeats across several facilities of one complex.

Added columns:
  usgs_facility_id       the USGS facility id (source_row_id before the '-'; for the US the site)
  facility_key           usgs_facility_id + site: the unit to list and count (one line each)
  stage_group            Mine / Concentrator / Smelter / Refinery / Brine operation / Other processing plant (for counting per stage)
  published_product      product_form + product_descriptor as published, or 'product not stated'
  measure                what the tonnage measures: contained metal / compound weight / gross weight / ore or concentrate / metal or refined
                         product / 'measure not stated by USGS' (from capacity_basis, else from the product wording)
  capacity_as_published  e.g. '1,300,000 t - Copper' (unit 'mt' = metric tons is written 't')
  shared_capacity_note   when USGS gives ONE capacity for several facilities (shared_with_rows): 'one capacity shared by facilities ... - count once'
  release                which USGS compilation and data year the row comes from
View only (no data change). Re-runnable. Grants SELECT to the app's read-only role.
"""
import psycopg2

ENV = {}
for line in open(r"C:\Users\dean\claude_lithosurfer\lithosurfer-work\.env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        ENV[k] = v.strip().strip('"')

SQL = r"""
DROP VIEW IF EXISTS core.facility_capacity_published;
CREATE VIEW core.facility_capacity_published AS
-- is_latest_year: false for older-release rows listed in core.facility_superseded (built by build_facility_supersede.py: a 2024 Minerals
-- Yearbook row of the same commodity and a compatible stage in the same complex - core.facility_site_clusters, sites within ~3 km - or within
-- 10 km of an area-centroid point with a shared name word). 2024 rows placed only at a town point supersede nothing; older releases never
-- supersede each other.
SELECT v.*,
       NOT EXISTS (SELECT 1 FROM core.facility_superseded s WHERE s.facility_capacity_id = v.facility_capacity_id) AS is_latest_year
FROM (
SELECT fc.*, cl.cluster_id,
       (fc.source_system = 'USGS_MYB2024' AND o.position_accuracy IS DISTINCT FROM 'TOWN_CENTROID') AS is_2024_anchor,
       CASE WHEN fc.source_system = 'USGS_US_FACILITIES' THEN 'US-site-' || fc.occurrence_id  -- US ids are per metal row, so the site is the facility
            WHEN fc.source_system = 'USGS_MYB2024' THEN regexp_replace(fc.source_row_id, '^FAC_|_[0-9]+$', '', 'g')   -- FAC_CHL0041_02 -> CHL0041
            ELSE split_part(fc.source_row_id, '-', 1) END AS usgs_facility_id,
       -- The unit to list and count: one USGS facility at one site. Several USGS facilities can share a site (three Baotou separation plants)
       -- and one USGS facility id can cover several named points (Nkana open pits A and E), so neither the site nor the id alone works.
       CASE WHEN fc.source_system = 'USGS_US_FACILITIES' THEN 'US:' || fc.occurrence_id
            WHEN fc.source_system = 'USGS_MYB2024' THEN regexp_replace(fc.source_row_id, '^FAC_|_[0-9]+$', '', 'g') || ':' || fc.occurrence_id
            ELSE split_part(fc.source_row_id, '-', 1) || ':' || fc.occurrence_id END AS facility_key,
       coalesce(nullif(trim(concat_ws(' ', fc.product_form, fc.product_descriptor)), ''), 'product not stated') AS published_product,
       CASE WHEN fc.feature_type ILIKE 'Brine%' OR fc.feature_type = 'B' THEN 'Brine operation'
            WHEN fc.facility_stage = 'Mine' OR (fc.facility_stage IS NULL AND (fc.feature_type ILIKE 'Mines%' OR fc.feature_type = 'M')) THEN 'Mine'
            WHEN fc.facility_stage IN ('Smelter', 'Refinery', 'Concentrator') THEN fc.facility_stage
            WHEN fc.facility_stage ILIKE '%Smelter%' THEN 'Smelter'
            ELSE 'Other processing plant' END AS stage_group,
       CASE
         WHEN fc.capacity_basis = 'ELEMENTAL_CONTENT' THEN 'contained metal/element content'
         WHEN fc.capacity_basis = 'COMPOUND_WEIGHT' THEN 'weight of the compound'
         WHEN fc.capacity_basis = 'GROSS_WEIGHT' THEN 'gross weight of the product, not metal content'
         WHEN fc.product_form ~* '(ore|concentrat|\mmine\M|crude|run.of.mine)' THEN 'ore or concentrate tonnage, not metal content'
         WHEN fc.product_form ~* '(metal|cathode|refined|ingot|blister|anode|bullion|pig iron|ferro|steel|content|matte)' THEN 'metal, alloy, matte or refined product'
         WHEN fc.product_form IS NULL THEN 'measure not stated by USGS'
         ELSE 'measure not stated by USGS'
       END AS measure,
       CASE WHEN fc.annual_capacity IS NULL THEN 'capacity not published'
            ELSE to_char(fc.annual_capacity, 'FM999,999,999,990.##') || ' ' || CASE lower(trim(fc.capacity_unit)) WHEN 'mt' THEN 't' WHEN 'metric tons' THEN 't' WHEN '' THEN '(unit not stated)' ELSE coalesce(trim(fc.capacity_unit), '(unit not stated)') END
                 || ' - ' || coalesce(nullif(trim(concat_ws(' ', fc.product_form, fc.product_descriptor)), ''), 'product not stated')
       END AS capacity_as_published,
       CASE WHEN fc.shared_with_rows IS NOT NULL AND cardinality(fc.shared_with_rows) > 0
            THEN 'one capacity shared by facilities ' || replace(array_to_string(fc.shared_with_rows, ', '), '***', '') || ' - count it once'
       END AS shared_capacity_note,
       CASE fc.source_system
         WHEN 'USGS_LAC_GIS' THEN 'USGS Latin America and Caribbean mineral-industry GIS compilation'
         WHEN 'USGS_SWASIA_GIS' THEN 'USGS Southwest Asia mineral-industry GIS compilation'
         WHEN 'USGS_INDOPAC_GIS' THEN 'USGS Indo-Pacific mineral-industry GIS compilation'
         WHEN 'USGS_CHINA_GIS' THEN 'USGS China mineral-industry GIS compilation'
         WHEN 'USGS_AFRICA_GIS' THEN 'USGS Africa mineral-industry GIS compilation'
         WHEN 'USGS_US_FACILITIES' THEN 'USGS U.S. mineral facilities'
         WHEN 'USGS_MYB2024' THEN 'USGS 2024 Minerals Yearbook global facilities table'
         ELSE fc.source_system
       END || CASE WHEN fc.source_system = 'USGS_US_FACILITIES' THEN '' ELSE coalesce(' (Minerals Yearbook ' || fc.data_year || ' data)', '') END AS release
FROM core.facility_capacity fc
JOIN core.occurrences o ON o.occurrence_id = fc.occurrence_id
LEFT JOIN core.facility_site_clusters cl ON cl.occurrence_id = fc.occurrence_id
WHERE fc.is_active IS DISTINCT FROM false
) v;
COMMENT ON VIEW core.facility_capacity_published IS 'facility_capacity with published_product, measure, capacity_as_published, shared_capacity_note and release text columns; use for any capacity answer.';
GRANT SELECT ON core.facility_capacity_published TO cm_app_readonly;
"""

con = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"], dbname="interzona_cm")
with con, con.cursor() as cur:
    cur.execute(SQL)
    cur.execute("SELECT source_system, data_year, count(*) FROM core.facility_capacity_published GROUP BY 1, 2 ORDER BY 1, 2")
    for r in cur.fetchall():
        print(r)
    cur.execute("""SELECT o.name, p.capacity_as_published, p.measure, p.shared_capacity_note, p.release FROM core.facility_capacity_published p
                   JOIN core.occurrences o USING (occurrence_id) WHERE o.name IN ('Escondida', 'Weda Bay', 'Bayan Obo') OR o.name ILIKE 'Kansanshi%' LIMIT 8""")
    for r in cur.fetchall():
        print(r)
    cur.execute("SELECT measure, count(*) FROM core.facility_capacity_published GROUP BY 1 ORDER BY 2 DESC")
    print(cur.fetchall())
con.close()
