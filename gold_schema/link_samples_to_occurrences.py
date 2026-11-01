"""Link geochemistry samples to nearby occurrences: geochem.sample_occurrence_links (sample_id, occurrence_id, distance_m, is_nearest).

One row per sample/occurrence pair within 2,000 m (geography distance, metres), for every sample that has chemistry (all geochemical sources;
the age-only Swedish points and the bare Wu zircon points are excluded).  is_nearest marks the closest occurrence of each sample.
Nothing else is changed: geochem.samples.occurrence_id (the older 'sample belongs to occurrence' link set for Argentina, Greenland and Finland) is left alone,
and results / wide-table rows are NOT touched (the table is joined when needed).
Occurrences whose position is only approximate (core.occurrences.position_accuracy not NULL: town / area / county centres from the USGS facilities load) are NOT linked.
Tiers for the app: distance_m <= 500 = at the site, <= 2000 = near.  Positional accuracy of many occurrences is +/- hundreds of metres to kilometres.
Usage: python link_samples_to_occurrences.py [--dry]   (--dry = build, verify, ROLLBACK)
"""
import os, sys, time
import psycopg2

DRY = "--dry" in sys.argv
RADIUS = 2000
BATCHES = 20
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '256MB'")
c.execute("""CREATE TABLE IF NOT EXISTS geochem.sample_occurrence_links (
  sample_id bigint NOT NULL REFERENCES geochem.samples (sample_id),
  occurrence_id integer NOT NULL REFERENCES core.occurrences (occurrence_id),
  distance_m integer NOT NULL,
  is_nearest boolean NOT NULL DEFAULT false,
  PRIMARY KEY (sample_id, occurrence_id))""")
c.execute("DELETE FROM geochem.sample_occurrence_links")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system NOT IN ('SWEDEN_SGU_BEDROCK_AGE', 'GLOBAL_ZIRCON_WU')"); log("samples considered", c.fetchone()[0])
t0 = time.time(); total = 0
for b in range(BATCHES):
    c.execute(f"""
    INSERT INTO geochem.sample_occurrence_links (sample_id, occurrence_id, distance_m, is_nearest)
    SELECT sample_id, occurrence_id, d::int, row_number() OVER (PARTITION BY sample_id ORDER BY d, occurrence_id) = 1
    FROM (SELECT s.sample_id, o.occurrence_id, ST_Distance(s.geog, o.geog) AS d
          FROM geochem.samples s JOIN core.occurrences o ON o.is_active AND o.position_accuracy IS NULL AND ST_DWithin(o.geog, s.geog, {RADIUS})
          WHERE s.sample_id % {BATCHES} = {b} AND s.source_system NOT IN ('SWEDEN_SGU_BEDROCK_AGE', 'GLOBAL_ZIRCON_WU')) x""")
    total += c.rowcount
    if b % 4 == 3: log(f"batch {b + 1}/{BATCHES}: {total} links so far, {round(time.time() - t0)} s")
log("links inserted", total)
c.execute("CREATE INDEX IF NOT EXISTS idx_sol_occurrence ON geochem.sample_occurrence_links (occurrence_id)")
c.execute("CREATE INDEX IF NOT EXISTS idx_sol_nearest ON geochem.sample_occurrence_links (sample_id) WHERE is_nearest")
c.execute("ANALYZE geochem.sample_occurrence_links")

# verification
c.execute("""SELECT s.source_system, count(DISTINCT l.sample_id) AS samples_linked, count(*) AS links,
  count(DISTINCT l.sample_id) FILTER (WHERE l.distance_m <= 500) AS within_500m, count(*) FILTER (WHERE l.is_nearest) AS nearest_rows
  FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) GROUP BY 1 ORDER BY 3 DESC""")
log("per source (samples linked, links, samples within 500 m, nearest rows)", c.fetchall())
c.execute("SELECT count(*) FROM (SELECT sample_id FROM geochem.sample_occurrence_links WHERE is_nearest GROUP BY 1 HAVING count(*) <> 1) x"); log("samples with not exactly one nearest row (must be 0)", c.fetchone()[0])
c.execute("SELECT count(*) FROM geochem.sample_occurrence_links WHERE distance_m > %s", (RADIUS,)); log("links beyond radius (must be 0)", c.fetchone()[0])
c.execute("""SELECT count(*) FROM (SELECT l.sample_id, l.occurrence_id, l.distance_m FROM geochem.sample_occurrence_links l WHERE l.sample_id % 5000 = 7) x
  JOIN geochem.samples s ON s.sample_id = x.sample_id JOIN core.occurrences o ON o.occurrence_id = x.occurrence_id WHERE abs(ST_Distance(s.geog, o.geog) - x.distance_m) > 1""")
log("spot-check distance mismatches (must be 0)", c.fetchone()[0])
c.execute("""SELECT o.country_name, count(DISTINCT l.sample_id) FROM geochem.sample_occurrence_links l JOIN core.occurrences o USING (occurrence_id) WHERE l.is_nearest AND l.distance_m <= 500 GROUP BY 1 ORDER BY 2 DESC LIMIT 6""")
log("samples within 500 m of an occurrence, by occurrence country", c.fetchall())
c.execute("SELECT pg_size_pretty(pg_total_relation_size('geochem.sample_occurrence_links'))"); log("table size", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
