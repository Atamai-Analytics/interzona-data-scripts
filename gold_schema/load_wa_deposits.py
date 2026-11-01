"""Washington Geological Survey Mines and Minerals sites (DS-30 v2.0, 5,418 canonical sites in bronze, datasource 'Washington State Geological Survey (DGER)')
-> interzona_cm core.occurrences / core.occurrence_commodities / geochem.occurrence_mineralogy / core.external_ids.

Mapping: gold commodity_id = bronze commodity_id + 867 (verified by name for all 287); minerals are matched BY NAME (ids differ); jurisdiction 990 (United States,
country level only - the state and county go into the comments). The bronze records carry no deposit type, status or size, so occurrence_type is NULL and
status/size are UNKNOWN; is_deposit is false (they are mineral locations/sites). Bronze deposits already in gold (core.external_ids) are skipped.
Attribution: Washington Geological Survey, 2023, Mines and Minerals--GIS data, August 2023: WGS Digital Data Series 30, version 2.0.
Usage: python load_wa_deposits.py [--dry]    (--dry = everything, then ROLLBACK)
"""
import os, sys, time, collections
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_wa_deposits_20261013"
DS = "Washington State Geological Survey (DGER)"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def conn(db):
    return psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db, user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


b = conn("criticialmineralsexp"); bc = b.cursor(); bc.execute("SET statement_timeout = 0")
bc.execute("""SELECT d.depositid, l.locationname, l.latitude, l.longitude, l.adminlevel2, d.comments, d."references"
FROM deposits d JOIN locations l ON l.locationid = d.locationid WHERE l.datasource = %s AND d.isactive ORDER BY d.depositid""", (DS,))
deps = bc.fetchall()
bc.execute("""SELECT dc.depositid, dc.commodity_id, dc.commodity_role FROM deposit_commodities dc JOIN deposits d ON d.depositid = dc.depositid JOIN locations l ON l.locationid = d.locationid
WHERE l.datasource = %s AND dc.isactive""", (DS,))
comm = bc.fetchall()
bc.execute("""SELECT dm.depositid, m.mineral_name, dm.mineral_name_local, dm.mineral_role, dm.mineral_zone, dm.role_raw FROM deposit_mineralogy dm JOIN deposits d ON d.depositid = dm.depositid
JOIN locations l ON l.locationid = d.locationid LEFT JOIN minerals m ON m.mineral_id = dm.mineral_id WHERE l.datasource = %s AND dm.isactive""", (DS,))
mins = bc.fetchall()
b.rollback(); b.close()
log("bronze deposits", len(deps), "| commodity links", len(comm), "| mineralogy rows", len(mins))

g = conn("interzona_cm"); g.autocommit = False; c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT source_id::bigint FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = 'BRONZE_CRITICIALMINERALSEXP'")
SKIP = {r[0] for r in c.fetchall()}
deps = [d for d in deps if d[0] not in SKIP]
log("deposits to load", len(deps), "| already in gold", len(SKIP & {d[0] for d in deps}))
c.execute("SELECT commodity_id FROM core.commodities"); GC = {r[0] for r in c.fetchall()}
c.execute("SELECT lower(mineral_name), mineral_id FROM geochem.minerals"); GM = dict(c.fetchall())

CITE = "Source: Washington Geological Survey, 2023, Mines and Minerals--GIS data, August 2023: Washington Geological Survey Digital Data Series 30, version 2.0 (deduplicated compilation of 9 layers)"
rows = []
for did, name, lat, lon, county, dcom, refs in deps:
    parts = [dcom.strip()] if dcom and dcom.strip() else []
    if county: parts.append(f"County: {county}")
    if refs: parts.append(f"References: {refs.strip()}")
    parts.append(CITE + f"; bronze deposit {did}. Load tag {TAG}")
    rows.append((name.strip(), float(lon), float(lat), " | ".join(parts)))
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, comments, is_active, created_by, created_date)
 VALUES %s RETURNING occurrence_id""", rows,
 template="(%s, false, 990, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'UNKNOWN', 'UNKNOWN', %s, true, '" + TAG + "', now())", page_size=1000, fetch=True)
OID = {d[0]: i[0] for d, i in zip(deps, ids)}
assert len(OID) == len(deps)
log("occurrences inserted", len(OID))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("OCCURRENCE", oid, "BRONZE_CRITICIALMINERALSEXP", str(did), TAG) for did, oid in OID.items()], page_size=1000)

# commodities: gold id = bronze id + 867; one row per deposit+commodity, PRIMARY wins over SECONDARY
best = {}
for did, cid, role in comm:
    if did not in OID: continue
    gid = cid + 867
    assert gid in GC, ("commodity not in gold", cid)
    key = (did, gid)
    if key not in best or (role == "PRIMARY" and best[key] != "PRIMARY"): best[key] = role
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s",
               [(OID[did], gid, role, True, TAG) for (did, gid), role in best.items()], template="(%s, %s, %s, %s, %s)", page_size=1000)
log("commodity links", len(best), "(from", len(comm), "bronze links)")

# mineralogy: mineral matched by name; rows without a catalogue mineral keep only the local name
mrows, unmapped = [], collections.Counter()
for did, mname, local, role, zone, rraw in mins:
    if did not in OID: continue
    mid = GM.get(mname.lower()) if mname else None
    if mname and mid is None: unmapped[mname] += 1
    mrows.append((OID[did], mid, (local or mname or "unknown")[:200], role, zone, rraw, True, TAG))
# the per-row trigger recalculates core.geology_summary with full scans of lithology_observations (hours for 5,000 rows): switch it off for the bulk insert
# and build the summary rows for the new occurrences set-based below (same rules as core.refresh_geology_summary, verified against it on a sample)
c.execute("ALTER TABLE geochem.occurrence_mineralogy DISABLE TRIGGER trg_occurrence_mineralogy_geology_summary")
execute_values(c, """INSERT INTO geochem.occurrence_mineralogy (occurrence_id, mineral_id, mineral_name_local, mineral_role, mineral_zone, role_raw, is_active, created_by) VALUES %s""", mrows, page_size=1000)
c.execute("ALTER TABLE geochem.occurrence_mineralogy ENABLE TRIGGER trg_occurrence_mineralogy_geology_summary")
c.execute("""
WITH om AS (SELECT om.occurrence_id, COALESCE(m.mineral_name, om.mineral_name_local) AS nm, om.mineral_role, om.mineral_zone
            FROM geochem.occurrence_mineralogy om LEFT JOIN geochem.minerals m ON m.mineral_id = om.mineral_id WHERE om.created_by = %s AND om.is_active),
dom AS (SELECT DISTINCT ON (occurrence_id) occurrence_id, nm FROM (SELECT occurrence_id, nm, count(*) AS n FROM om GROUP BY 1, 2) x ORDER BY occurrence_id, n DESC, nm),
obs AS (SELECT occurrence_id, jsonb_agg(jsonb_build_object('type', 'mineral', 'name', nm, 'role', mineral_role, 'zone', mineral_zone)) AS o FROM om GROUP BY 1)
INSERT INTO core.geology_summary (occurrence_id, dominant_mineral, observations, updated_at)
SELECT dom.occurrence_id, dom.nm, obs.o, now() FROM dom JOIN obs USING (occurrence_id)
ON CONFLICT (occurrence_id) DO NOTHING""", (TAG,))
log("geology_summary rows added", c.rowcount)
# check the set-based rows against the real function on 3 occurrences (function result must be identical)
c.execute("SELECT occurrence_id, dominant_mineral, observations FROM core.geology_summary WHERE occurrence_id IN (SELECT occurrence_id FROM core.occurrences WHERE created_by = %s) ORDER BY occurrence_id LIMIT 3 OFFSET 40", (TAG,))
chk = c.fetchall()
for oid, dm, ob in chk:
    c.execute("SELECT core.refresh_geology_summary(%s)", (oid,))
    c.execute("SELECT dominant_mineral, observations FROM core.geology_summary WHERE occurrence_id = %s", (oid,))
    dm2, ob2 = c.fetchone()
    srt = lambda x: sorted(x, key=lambda e: str(e))
    assert dm == dm2 and srt(ob) == srt(ob2), ("geology_summary mismatch", oid, dm, dm2)
log("geology_summary set-based rows identical to core.refresh_geology_summary on", len(chk), "occurrences")
log("mineralogy rows", len(mrows), "| with catalogue mineral", sum(1 for m in mrows if m[1]), "| name-only", sum(1 for m in mrows if not m[1]), "| names not in gold catalogue", dict(unmapped))

# verification
c.execute("SELECT count(*), count(DISTINCT name), min(lat), max(lat), min(lon), max(lon), count(*) FILTER (WHERE country_name = 'United States'), count(*) FILTER (WHERE array_length(commodities,1) > 0) FROM core.occurrences WHERE created_by = %s", (TAG,))
log("occurrences (count, distinct names, lat range, lon range, country US, with commodities array)", c.fetchone())
c.execute("""SELECT cm.commodity_name, count(*) FILTER (WHERE oc.commodity_role = 'PRIMARY'), count(*) FROM core.occurrence_commodities oc JOIN core.commodities cm USING (commodity_id)
 WHERE oc.created_by = %s GROUP BY 1 ORDER BY 3 DESC LIMIT 12""", (TAG,)); log("top commodities (primary, all)", c.fetchall())
c.execute("""SELECT count(DISTINCT oc.occurrence_id) FROM core.occurrence_commodities oc JOIN core.commodities cm USING (commodity_id) WHERE oc.created_by = %s AND cm.is_critical_mineral""", (TAG,)); log("occurrences with a critical-mineral commodity", c.fetchone()[0])
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND (comments IS NULL OR comments = '')", (TAG,)); log("occurrences without comments (must be 0)", c.fetchone()[0])
c.execute("SELECT name, round(lat::numeric,4), round(lon::numeric,4), commodities, left(comments, 140) FROM core.occurrences WHERE created_by = %s ORDER BY occurrence_id LIMIT 3", (TAG,))
for r in c.fetchall(): log("  ", r)
c.execute("SELECT count(*) FROM core.occurrences"); log("core.occurrences total", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
