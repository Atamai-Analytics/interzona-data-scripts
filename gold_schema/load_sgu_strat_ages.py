"""Swedish lithogeochemistry samples: stratigraphic age descriptors (bronze age_stratigraphic) -> interzona_cm geochem.age_stratigraphic.

Source: bronze rows built from bergartskemi.strat_anm (SGU free-text comment on stratigraphic position/age), mapped by Atamai to a
named period/unit. They are interpretive descriptors, loaded as confidence UNCERTAIN with SGU's original wording in reported_age_raw.
The 978 bronze age_measured rows from the same field are NOT loaded: strat_anm numbers (112, 122, 142, 999 ...) are not ages.
Usage: python load_sgu_strat_ages.py [--dry]
"""
import os, sys, time
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_sgu_strat_age_20261012"
CB = "sgu_strat_age_20261012"
DS = "SGU - Geological Survey of Sweden"
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def conn(db):
    return psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db, user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


b = conn("criticialmineralsexp"); bc = b.cursor(); bc.execute("SET statement_timeout = 0")
bc.execute("""
SELECT a.sampleid, a.age_local, sar.age_name, a.confidence_level
FROM age_stratigraphic a JOIN samples s ON s.sampleid = a.sampleid JOIN locations l ON l.locationid = s.locationid
JOIN stratigraphic_age_reference sar ON sar.stratigraphic_age_id = a.stratigraphic_age_id
WHERE l.datasource = %s AND a.is_active AND s.isactive ORDER BY a.sampleid, a.age_stratigraphic_id""", (DS,))
rows = bc.fetchall(); b.rollback(); b.close()
log("bronze Swedish stratigraphic age rows", len(rows))

g = conn("interzona_cm"); g.autocommit = False; c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT age_name, stratigraphic_age_id FROM geochem.stratigraphic_age_reference WHERE is_active")
SAR = dict(c.fetchall())
c.execute("""SELECT e.source_id::bigint, e.entity_id FROM core.external_ids e JOIN geochem.samples s ON s.sample_id = e.entity_id
 WHERE e.entity_type = 'SAMPLE' AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP' AND s.source_system = 'SWEDEN_SGU_LITHOGEOCHEMISTRY'""")
SID = dict(c.fetchall())
out, miss_sar, miss_s = [], set(), 0
for sid, local, name, conf in rows:
    if name not in SAR: miss_sar.add(name); continue
    if sid not in SID: miss_s += 1; continue
    out.append((SAR[name], local, "POINT_LOCATION", SID[sid], "UNCERTAIN",
                "Interpretive: SGU stratigraphic comment mapped to a named period/unit",
                local,
                "Derived from the SGU lithogeochemistry field strat_anm (free-text comment on stratigraphic position), mapped by Atamai; not a measured age.",
                True, CB))
log("to insert", len(out), "unmapped names", miss_sar, "unmatched samples", miss_s)
assert not miss_sar and miss_s == 0
c.execute("SELECT count(*) FROM geochem.age_stratigraphic"); before = c.fetchone()[0]
execute_values(c, """INSERT INTO geochem.age_stratigraphic (stratigraphic_age_id, age_local, observation_context, sample_id, confidence_level, determination_method,
 reported_age_raw, comments, is_active, created_by) VALUES %s""", out, page_size=1000)
c.execute("SELECT count(*), count(DISTINCT sample_id) FROM geochem.age_stratigraphic WHERE created_by = %s", (CB,)); log("inserted (rows, samples)", c.fetchone())
c.execute("""SELECT r.age_name, count(*) FROM geochem.age_stratigraphic a JOIN geochem.stratigraphic_age_reference r USING (stratigraphic_age_id) WHERE a.created_by = %s GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", (CB,)); log("top", c.fetchall())
c.execute("SELECT count(*) FROM geochem.age_stratigraphic"); log("age_stratigraphic total", before, "->", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
