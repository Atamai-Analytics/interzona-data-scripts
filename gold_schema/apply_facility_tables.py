"""Applies DRAFT_facility_tables.sql (approved by the user 2026-10-14, including core.occurrences.position_accuracy) in one transaction.
The draft's optional ALTER is commented out there, so it is enabled here.  Re-runnable only before the tables exist (CREATE TABLE fails otherwise, rolling everything back)."""
import os, re
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
sql = open(os.path.join(HERE, "DRAFT_facility_tables.sql"), encoding="utf-8").read()
sql = sql.replace("-- ALTER TABLE core.occurrences ADD COLUMN position_accuracy", "ALTER TABLE core.occurrences ADD COLUMN position_accuracy")
sql = re.sub(r"^\s*BEGIN;\s*$|^\s*COMMIT;\s*$", "", sql, flags=re.M)   # run inside our own transaction
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("SET lock_timeout = '10s'")
c.execute(sql)
c.execute("COMMENT ON COLUMN core.occurrences.position_accuracy IS 'NULL = position as published by the source; SNAPPED = taken from a matching nearby record; TOWN_CENTROID = only the town centre is known (approximate, excluded from sample-to-occurrence links)'")
c.execute("""SELECT table_name, count(*) FROM information_schema.columns WHERE table_schema='core' AND table_name IN ('facility_capacity','occurrence_ownership') GROUP BY 1 ORDER BY 1""")
print("new tables (columns):", c.fetchall())
c.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='core' AND table_name='occurrences' AND column_name='position_accuracy'")
print("occurrences.position_accuracy:", c.fetchall())
c.execute("SELECT has_table_privilege('cm_app_readonly','core.facility_capacity','select'), has_table_privilege('cm_app_readonly','core.occurrence_ownership','select')")
print("cm_app_readonly can select:", c.fetchall())
c.execute("SELECT count(*) FROM core.occurrences"); print("occurrences rows unchanged:", c.fetchone())
g.commit(); print("COMMITTED")
