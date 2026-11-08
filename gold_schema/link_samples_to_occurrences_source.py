"""Rebuild geochem.sample_occurrence_links for ONE sample source_system (same rules as link_samples_to_occurrences.py, which rebuilds all).

Use after new occurrences are loaded in an area, so that one source's samples are re-linked without touching the other 1.2M links.
Rules (unchanged): one row per sample/occurrence pair within 2,000 m (geography distance), active occurrences with a precise position only
(position_accuracy NULL), is_nearest marks each sample's closest occurrence. geochem.samples.occurrence_id and results are not touched.
The old links for the source are written to sol_backup_<source>_<stamp>.csv before they are replaced (rollback = delete the source's links
and re-insert the CSV).
Usage: python link_samples_to_occurrences_source.py SOURCE_SYSTEM [--dry]
"""
import csv, datetime, os, sys, time
import psycopg2

SRC = sys.argv[1]
DRY = "--dry" in sys.argv
RADIUS = 2000
HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '256MB'")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); n = c.fetchone()[0]
assert n > 0, f"no samples for {SRC}"
assert SRC not in ("SWEDEN_SGU_BEDROCK_AGE", "GLOBAL_ZIRCON_WU"), "age-only / bare points are never linked"
log(SRC, "samples", n)

c.execute("""SELECT l.sample_id, l.occurrence_id, l.distance_m, l.is_nearest FROM geochem.sample_occurrence_links l
             JOIN geochem.samples s USING (sample_id) WHERE s.source_system = %s""", (SRC,))
old = c.fetchall()
path = os.path.join(HERE, f"sol_backup_{SRC}_{STAMP}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["sample_id", "occurrence_id", "distance_m", "is_nearest"]); w.writerows(old)
log("old links", len(old), "| samples", len({r[0] for r in old}), "| backup", path)

c.execute("DELETE FROM geochem.sample_occurrence_links l USING geochem.samples s WHERE s.sample_id = l.sample_id AND s.source_system = %s", (SRC,))
log("deleted", c.rowcount)
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.sample_occurrence_links (sample_id, occurrence_id, distance_m, is_nearest)
SELECT sample_id, occurrence_id, d::int, row_number() OVER (PARTITION BY sample_id ORDER BY d, occurrence_id) = 1
FROM (SELECT s.sample_id, o.occurrence_id, ST_Distance(s.geog, o.geog) AS d
      FROM geochem.samples s JOIN core.occurrences o ON o.is_active AND o.position_accuracy IS NULL AND ST_DWithin(o.geog, s.geog, {RADIUS})
      WHERE s.source_system = %s) x""", (SRC,))
log("inserted", c.rowcount, f"in {round(time.time() - t0)} s")

c.execute("""SELECT count(*), count(DISTINCT l.sample_id), count(DISTINCT l.sample_id) FILTER (WHERE l.distance_m <= 500), count(DISTINCT l.occurrence_id)
             FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) WHERE s.source_system = %s""", (SRC,))
log("new: links, samples linked, samples within 500 m, occurrences reached", c.fetchone())
c.execute("""SELECT o.created_by, count(DISTINCT l.sample_id) FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id)
             JOIN core.occurrences o ON o.occurrence_id = l.occurrence_id WHERE s.source_system = %s AND l.is_nearest GROUP BY 1 ORDER BY 2 DESC""", (SRC,))
log("nearest occurrence by occurrence source", c.fetchall())
c.execute("""SELECT count(*) FROM (SELECT l.sample_id FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id)
             WHERE s.source_system = %s AND l.is_nearest GROUP BY 1 HAVING count(*) <> 1) x""", (SRC,)); log("samples with not exactly one nearest (must be 0)", c.fetchone()[0])
c.execute("""SELECT count(*) FROM (SELECT DISTINCT l.sample_id FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) WHERE s.source_system = %s) a
             LEFT JOIN (SELECT DISTINCT l.sample_id FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) WHERE s.source_system = %s AND l.is_nearest) b USING (sample_id)
             WHERE b.sample_id IS NULL""", (SRC, SRC)); log("linked samples without a nearest row (must be 0)", c.fetchone()[0])
c.execute("""SELECT count(*) FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) JOIN core.occurrences o ON o.occurrence_id = l.occurrence_id
             WHERE s.source_system = %s AND l.sample_id %% 50 = 3 AND abs(ST_Distance(s.geog, o.geog) - l.distance_m) > 1""", (SRC,)); log("spot-check distance mismatches (must be 0)", c.fetchone()[0])
c.execute("""SELECT o.name, o.status, count(*) FILTER (WHERE l.distance_m <= 500) AS at_site, count(*) AS within_2km
             FROM geochem.sample_occurrence_links l JOIN geochem.samples s USING (sample_id) JOIN core.occurrences o ON o.occurrence_id = l.occurrence_id
             WHERE s.source_system = %s GROUP BY o.name, o.status ORDER BY 3 DESC LIMIT 8""", (SRC,)); log("most-sampled occurrences", c.fetchall())
c.execute("SELECT count(*) FROM geochem.sample_occurrence_links"); log("table total now", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
