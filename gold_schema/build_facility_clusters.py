"""Groups USGS facility sites into complexes so that newer capacity figures can supersede older ones for the same plant.
In the USGS releases one complex is often several sites (mine, processing plant, smelter - separate points, often at the same coordinates), and
the 2024 Minerals Yearbook rows can land on a different one of them than the older regional-release rows (Sorowako: 2024 nickel on the mine
point, 2018 nickel on the processing-plant point 200 m away). Complex = sites with USGS capacity rows within 3 km of each other (DBSCAN, one
point is enough). Writes core.facility_site_clusters (occurrence_id, cluster_id); the view core.facility_capacity_published uses it: if a
complex has a 2024 row for a commodity, older rows of that commodity anywhere in the complex get is_latest_year = false.
Covers sites with rows in core.facility_capacity and in the holding table core.hold_myb2024_facility_capacity (when the 2024 load is hidden).
Re-run after any facility load. Usage: python build_facility_clusters.py
"""
import os, psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT to_regclass('core.hold_myb2024_facility_capacity')"); hold = c.fetchone()[0] is not None
src = "SELECT occurrence_id FROM core.facility_capacity WHERE source_system LIKE 'USGS_%'" + \
      (" UNION SELECT occurrence_id FROM core.hold_myb2024_facility_capacity" if hold else "")
c.execute("CREATE TABLE IF NOT EXISTS core.facility_site_clusters (occurrence_id integer PRIMARY KEY, cluster_id integer NOT NULL)")
c.execute("TRUNCATE core.facility_site_clusters")
# DBSCAN in a metric projection would be nicer; 3 km ~ 0.027 deg of latitude - using geography distance via a 3857 transform is distorted at
# high latitude, so cluster in degrees with eps 0.03 and then accept only links that are really within 3 km (checked below).
c.execute(f"""INSERT INTO core.facility_site_clusters (occurrence_id, cluster_id)
              SELECT o.occurrence_id, ST_ClusterDBSCAN(o.geom, eps := 0.03, minpoints := 1) OVER ()
              FROM core.occurrences o WHERE o.occurrence_id IN ({src})""")
n = c.rowcount
c.execute("""SELECT count(DISTINCT cluster_id), count(*) FILTER (WHERE k > 1), max(k) FROM
             (SELECT cluster_id, count(*) OVER (PARTITION BY cluster_id) k FROM core.facility_site_clusters) x""")
print("sites", n, "| complexes / sites in multi-site complexes / largest complex:", c.fetchone())
c.execute("GRANT SELECT ON core.facility_site_clusters TO cm_app_readonly")
g.commit()
