"""Let the newer USGS Africa status override older statuses on occurrences that the USGS Africa load ATTACHED to (2026-11-10).

Background: load_usgs_africa.py attached 1,027 USGS records to existing occurrences (mostly MRDS, data mostly pre-2011) and left their status
untouched, so e.g. Kansanshi stayed PAST_PRODUCER although USGS lists it as an active facility in 2017.

Rules (conservative):
  A. Facilities (USGS Minerals Yearbook 2018, Zambia 2017; status in core.facility_capacity.facility_status, source USGS_AFRICA_GIS):
     one distinct status per occurrence only (conflicting rows -> skipped). 'Assumed Active'/'Active' -> PRODUCER, 'C&M' -> CARE_AND_MAINTENANCE,
     'Closed' -> CLOSED. Overrides any older status (it is the newer source). Note: 'Assumed Active' is USGS's assumption, not verified.
  B. Exploration projects (USGS WMED, stage as last verified 2004-2018): only FILLS IN statuses that say nothing about activity
     (UNKNOWN, OCCURRENCE, PROSPECT); never overrides PRODUCER / PAST_PRODUCER / other stages (WMED 'Exploration' on a mine is usually
     exploration around it). Stage mapping as in the load. Applied only if rule A did not already change the record.
  Deposits (PP1802) carry no status -> untouched.
Each change: status updated, comment appended ("Status changed <old> -> <new> on 2026-11-10 from ..."), modified_by = TAG.
Backup CSV of old status/comments/modified_by/modified_date written first (rollback: restore those four columns WHERE modified_by = TAG).
Usage: python -P fix_africa_status_20261110.py [--dry]   (--dry = do it, verify, ROLLBACK)
"""
import os, sys, csv, time, collections
import psycopg2, pyogrio

DRY = "--dry" in sys.argv
TAG = "fix_africa_status_20261110"
SRC = "USGS_AFRICA_GIS"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


FAC = {"assumed active": "PRODUCER", "active": "PRODUCER", "c&m": "CARE_AND_MAINTENANCE", "closed": "CLOSED"}
EXP = {"exploration": "EXPLORATION", "feasibility study": "FEASIBILITY", "reserves development": "DEVELOPMENT", "pre-production": "DEVELOPMENT",
       "construction": "DEVELOPMENT", "development": "DEVELOPMENT", "production": "PRODUCER", "expansion": "PRODUCER",
       "care and maintenance": "CARE_AND_MAINTENANCE", "suspended": "CARE_AND_MAINTENANCE", "closed": "CLOSED"}
FILLABLE = {"UNKNOWN", "OCCURRENCE", "PROSPECT"}

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                     user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("SELECT count(*) FROM core.occurrences WHERE modified_by = %s", (TAG,))
assert c.fetchone()[0] == 0, "already applied (rows carry the tag)"

# attached = HIGH-confidence external ids from the load on occurrences the load did not create
c.execute("""SELECT o.occurrence_id, o.name, o.status, o.comments, o.modified_by, o.modified_date, e.source_id
             FROM core.external_ids e JOIN core.occurrences o ON o.occurrence_id = e.entity_id
             WHERE e.source_system = %s AND e.entity_type = 'OCCURRENCE' AND e.match_confidence = 'HIGH'
               AND o.created_by <> 'migration_usgs_africa_20261110' AND o.is_active""", (SRC,))
rows = c.fetchall()
occ = {r[0]: r for r in rows}
log("attached occurrences", len(occ), "| external ids", len(rows))

c.execute("""SELECT occurrence_id, array_agg(DISTINCT facility_status), max(data_year) FROM core.facility_capacity
             WHERE source_system = %s AND facility_status IS NOT NULL GROUP BY 1""", (SRC,))
facstat = {oid: (sts, yr) for oid, sts, yr in c.fetchall()}
x = pyogrio.read_dataframe("D:/CriticalMineralsDB/Africa/download_20261110/gdb/Africa_GIS.gdb", layer="AFR_Mineral_Exploration", read_geometry=False)
expstage = {"exp:" + u: (s, y) for u, s, y in zip(x.FeatureUID, x.LocOpStat, x.DsgAttr11)}

change, skipped = {}, collections.Counter()
for oid, name, status, *_ in rows:
    if oid in change: continue
    sids = [r[6] for r in rows if r[0] == oid]
    # rule A
    if any(s.startswith("fac:") for s in sids) and oid in facstat:
        sts, yr = facstat[oid]
        new = {FAC.get((s or "").lower()) for s in sts}
        if len(new) != 1 or None in new:
            skipped[f"facility: conflicting/unmapped statuses {sorted(sts)}"] += 1
        elif new.pop() != status:
            nv = FAC[sts[0].lower()]
            note = (f"Status changed {status} -> {nv} on 2026-11-10 from USGS Minerals Yearbook facility status '{sts[0]}' ({yr}), "
                    f"USGS Africa GIS compilation doi:10.5066/P97EQWXP" + ("; 'Assumed Active' is USGS's assumption, not verified" if sts[0].lower() == "assumed active" else ""))
            change[oid] = (status, nv, "A", note)
            continue
        else:
            skipped["facility: same status already"] += 1
            continue
    # rule B
    exps = [expstage[s] for s in sids if s in expstage]
    if exps:
        if status not in FILLABLE:
            skipped[f"exploration: not overriding {status}"] += 1; continue
        st, yr = max(exps, key=lambda t: t[1] or 0)
        nv = EXP.get((st or "").lower())
        if not nv:
            skipped[f"exploration: unmapped stage {st}"] += 1; continue
        note = (f"Status changed {status} -> {nv} on 2026-11-10 from USGS World Minerals Exploration Database stage '{st}' "
                f"as last verified in {int(yr) if yr else '?'} (may be out of date), USGS Africa GIS compilation doi:10.5066/P97EQWXP")
        change[oid] = (status, nv, "B", note)

log("changes", len(change), "| by rule", collections.Counter(v[2] for v in change.values()))
log("transitions", collections.Counter((v[0], v[1]) for v in change.values()).most_common())
log("skipped", dict(skipped))

bk = os.path.join(HERE, f"backup_{TAG}.csv")
with open(bk, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["occurrence_id", "name", "old_status", "new_status", "rule", "old_comments", "old_modified_by", "old_modified_date"])
    for oid, (old, nv, rule, note) in sorted(change.items()):
        r = occ[oid]; w.writerow([oid, r[1], old, nv, rule, r[3], r[4], r[5]])
log("backup", bk)

for oid, (old, nv, rule, note) in change.items():
    c.execute("""UPDATE core.occurrences SET status = %s, comments = concat_ws(' | ', comments, %s), modified_by = %s, modified_date = now()
                 WHERE occurrence_id = %s AND status = %s""", (nv, note, TAG, oid, old))
    assert c.rowcount == 1, oid

c.execute("SELECT count(*) FROM core.occurrences WHERE modified_by = %s", (TAG,))
n = c.fetchone()[0]; assert n == len(change), (n, len(change))
c.execute("""SELECT name, status, country_name FROM core.occurrences WHERE occurrence_id IN
             (SELECT occurrence_id FROM core.occurrences WHERE modified_by = %s) AND name IN
             ('Kansanshi','Tenke Fungurume','Kolwezi','Etoile','Kinsenda','Baluba','Nampundwe','Dikulushi','Fitwaola') ORDER BY 1""", (TAG,))
for r in c.fetchall(): log("  check", r)
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED", n, "rows")
