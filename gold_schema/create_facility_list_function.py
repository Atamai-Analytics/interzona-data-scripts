"""Creates core.facility_list(country, commodity, stage, include_superseded): a ready-made facility list with every count already worked out,
so answers copy their headline counts instead of counting (answers mixing the 2024 Minerals Yearbook table with older USGS regional releases
kept getting the release split wrong, e.g. '6 with 2024 figures, 15 from 2018' when the list had 7 and 14).

One row per facility line = facility_key x stage_group (one USGS facility at one site, per stage), built from core.facility_capacity_published
with is_latest_year = true (newest figure per complex) unless include_superseded. Count columns on every row:
  n                 row number within stage_group (ordered by name)  -> number the table rows
  stage_total       lines in this stage_group                         -> per-stage headings
  release_total     lines from this row's release                     -> the split by release
  facilities_total  all lines                                         -> the headline count
  sites_total       distinct sites (occurrence_id)                    -> "N facilities on M sites" when different
Arguments (all optional, NULL = no filter): p_country = country_name, case-insensitive exact; p_commodity = substring of commodity_name
(e.g. 'nickel', 'rare'); p_stage = stage_group exact (Mine / Concentrator / Smelter / Refinery / Brine operation / Other processing plant).
capacity_sort = the largest annual_capacity number on the line, for ORDER BY only (units and measures differ - never add or compare across them).
Usage: SELECT * FROM core.facility_list('Indonesia', 'nickel');   Re-runnable; grants EXECUTE to the app's read-only role.
"""
import os, psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')

SQL = r"""
DROP FUNCTION IF EXISTS core.facility_list(text, text, text, boolean);
CREATE FUNCTION core.facility_list(p_country text DEFAULT NULL, p_commodity text DEFAULT NULL, p_stage text DEFAULT NULL,
                                   p_include_superseded boolean DEFAULT false)
RETURNS TABLE (n bigint, stage_group text, name text, country text, facility_key text, data_year integer, release text,
               commodities text, capacity_as_published text, capacity_sort numeric, measure text, shared_capacity_note text, status text, owners text,
               position_accuracy text, lat double precision, lon double precision, occurrence_id integer,
               stage_total bigint, release_total bigint, facilities_total bigint, sites_total bigint)
LANGUAGE sql STABLE AS $f$
WITH r AS (
  SELECT p.*, o.name AS site_name, o.country_name, o.position_accuracy AS pos, o.lat AS olat, o.lon AS olon
  FROM core.facility_capacity_published p
  JOIN core.occurrences o ON o.occurrence_id = p.occurrence_id
  WHERE o.is_active
    AND (p_include_superseded OR p.is_latest_year)
    AND (p_country IS NULL OR lower(o.country_name) = lower(p_country))
    AND (p_commodity IS NULL OR p.commodity_name ILIKE '%' || p_commodity || '%')
    AND (p_stage IS NULL OR lower(p.stage_group) = lower(p_stage))
), f AS (
  SELECT r.facility_key, r.stage_group, min(r.site_name) AS name, min(r.country_name) AS country,
         max(r.data_year)::integer AS data_year, min(r.release) AS release,
         string_agg(DISTINCT r.commodity_name, ', ') AS commodities,
         string_agg(DISTINCT r.capacity_as_published, '; ') AS capacity_as_published,
         max(r.annual_capacity) AS capacity_sort,
         string_agg(DISTINCT r.measure, '; ') AS measure,
         string_agg(DISTINCT r.shared_capacity_note, '; ') AS shared_capacity_note,
         string_agg(DISTINCT r.facility_status, '; ') AS status,
         min(r.pos) AS position_accuracy, min(r.olat) AS lat, min(r.olon) AS lon, min(r.occurrence_id) AS occurrence_id,
         min(r.source_system) AS source_system
  FROM r GROUP BY r.facility_key, r.stage_group
)
SELECT row_number() OVER (PARTITION BY f.stage_group ORDER BY f.name, f.facility_key) AS n,
       f.stage_group, f.name, f.country, f.facility_key, f.data_year, f.release, f.commodities, f.capacity_as_published, f.capacity_sort, f.measure,
       f.shared_capacity_note, f.status,
       (SELECT string_agg(DISTINCT w.owner_name || coalesce(' ' || to_char(w.share_pct, 'FM990.##') || '%', ''), '; ')
          FROM core.occurrence_ownership w
         WHERE w.occurrence_id = f.occurrence_id AND w.is_active IS DISTINCT FROM false AND w.source_system = f.source_system) AS owners,
       f.position_accuracy, f.lat, f.lon, f.occurrence_id,
       count(*) OVER (PARTITION BY f.stage_group) AS stage_total,
       count(*) OVER (PARTITION BY f.release) AS release_total,
       count(*) OVER () AS facilities_total,
       (SELECT count(DISTINCT r2.occurrence_id) FROM r r2) AS sites_total
FROM f
ORDER BY f.stage_group, f.name, f.facility_key
$f$;
COMMENT ON FUNCTION core.facility_list(text, text, text, boolean) IS
  'Facility list (newest figure per complex) with n, stage_total, release_total, facilities_total, sites_total already counted. SELECT * FROM core.facility_list(country, commodity_substring, stage, include_superseded).';
GRANT EXECUTE ON FUNCTION core.facility_list(text, text, text, boolean) TO cm_app_readonly;
"""

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
with g, g.cursor() as c:
    c.execute(SQL)
    for args in [("Indonesia", "nickel"), ("China", "rare"), ("Chile", "copper")]:
        c.execute("SELECT release, max(release_total), max(facilities_total), max(sites_total) FROM core.facility_list(%s, %s) GROUP BY 1", args)
        print(args, c.fetchall())
    c.execute("SELECT n, stage_group, name, data_year, capacity_as_published, owners FROM core.facility_list('Indonesia', 'nickel') LIMIT 4")
    for r in c.fetchall():
        print(r)
g.close()
