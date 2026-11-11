"""Merges MRDS 10255234 'Lippenwerke Lunen' (occurrence 528999) into MRDS 10239510 'Lippewerke Lunen' (occurrence 515942), 2026-11-11.
Both are the Lünen (North Rhine-Westphalia) aluminium plant; 528999's MRDS position (50.43 N, 7.07 E) is ~130 km south of Lünen, in
Rhineland-Palatinate, although its own location text says Nordrhein-Westfalen. Same procedure as review_aus_mrds_leftovers.py: re-point
child rows, move the MRDS external id, deactivate the duplicate, note it in comments. Writes a before-snapshot + log CSV. Usage: python
merge_lippenwerke_lunen.py [--dry]
"""
import os, sys, csv, datetime, psycopg2

DRY = "--dry" in sys.argv
OLD, NEW = 528999, 515942
TAG = "merge_lippenwerke_20261111"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
stamp = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"

c.execute("SELECT occurrence_id, name, lat, lon, is_active, commodities, comments FROM core.occurrences WHERE occurrence_id IN (%s, %s)", (OLD, NEW))
snap = c.fetchall()
assert len(snap) == 2 and all(r[4] for r in snap), snap
with open(os.path.join(HERE, f"lippenwerke_merge_before_{stamp}.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["occurrence_id", "name", "lat", "lon", "is_active", "commodities", "comments"]); w.writerows(snap)

REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
           ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
           ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id"),
           ("core.facility_capacity", "occurrence_id")]
log = []
c.execute("""DELETE FROM geochem.sample_occurrence_links WHERE occurrence_id = %s
             AND sample_id IN (SELECT sample_id FROM geochem.sample_occurrence_links WHERE occurrence_id = %s)""", (OLD, NEW))
if c.rowcount: log.append(("drop_duplicate_link", "geochem.sample_occurrence_links", c.rowcount))
for tbl, col in REPOINT:
    c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (NEW, OLD))
    if c.rowcount: log.append(("repoint", tbl, c.rowcount))
c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (NEW, OLD))
if c.rowcount: log.append(("move_external_id", "core.external_ids", c.rowcount))
c.execute("UPDATE core.occurrence_commodities SET is_active = false WHERE occurrence_id = %s AND is_active", (OLD,))
if c.rowcount: log.append(("deactivate_commodities", "core.occurrence_commodities", c.rowcount))
c.execute("""UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now(),
             comments = coalesce(comments, '') || %s WHERE occurrence_id = %s""",
          (TAG, f" | MERGED 2026-11-11 into occurrence {NEW} (Lippewerke Lunen, MRDS 10239510): same Lünen aluminium plant; this MRDS position "
                "(50.43 N, 7.07 E) is ~130 km from Lünen and wrong", OLD))
log.append(("deactivate", "core.occurrences", c.rowcount))
c.execute("""UPDATE core.occurrences SET comments = coalesce(comments, '') || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s""",
          (" | Also MRDS 10255234 'Lippenwerke Lunen' (merged 2026-11-11; its MRDS position was wrong)", TAG, NEW))
for r in log: print(r)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    with open(os.path.join(HERE, f"lippenwerke_merge_log_{stamp}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["action", "table", "rows"]); w.writerows(log)
    g.commit(); print("merged", OLD, "->", NEW)
