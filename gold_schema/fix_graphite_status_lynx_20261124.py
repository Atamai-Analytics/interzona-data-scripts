"""Lynx graphite mine (Zimbabwe): the 4 older records of the same operation as 1200209 (3 MRDS, 1 USGS Minerals Yearbook 2018)
set PRODUCER -> CARE_AND_MAINTENANCE with a sourced note (user OK 2026-11-24, "add the C&M note to the Lynx rows").
Companion to fix_graphite_status_east_africa_20261124.py.
A dated note with the source is appended to comments; modified_by = this tag.
Backup: graphite_status_lynx_backup_<stamp>.csv (occurrence_id, status, comments, modified_by, modified_date).
Rollback: python fix_graphite_status_lynx_20261124.py --undo <backup.csv>
Usage: python fix_graphite_status_lynx_20261124.py [--dry | --undo backup.csv]
"""
import csv, os, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "fix_graphite_status_lynx_20261124"

# occurrence_id: (expected current status, new status, note)
CHANGES = {
    325145: ("PRODUCER", "CARE_AND_MAINTENANCE", "Lynx graphite mine, Karoi (Zimbabwe German Graphite Mines; ZMDC / Graphit Kropfmuehl JV): operations suspended and put on care and maintenance in 2017 for cash-flow reasons (Sunday Mail, 1 Oct 2017); under receivership in Nov 2021 with a ZMDC - Fossil Mining Resources JV and an EIA under way (Genesis Environment Consultancy notice); no confirmed restart found. Same operation as 1200209"),
    426682: ("PRODUCER", "CARE_AND_MAINTENANCE", "Lynx graphite mine, Karoi (Zimbabwe German Graphite Mines; ZMDC / Graphit Kropfmuehl JV): operations suspended and put on care and maintenance in 2017 for cash-flow reasons (Sunday Mail, 1 Oct 2017); under receivership in Nov 2021 with a ZMDC - Fossil Mining Resources JV and an EIA under way (Genesis Environment Consultancy notice); no confirmed restart found. Same operation as 1200209"),
    488420: ("PRODUCER", "CARE_AND_MAINTENANCE", "Lynx graphite mine, Karoi (Zimbabwe German Graphite Mines; ZMDC / Graphit Kropfmuehl JV): operations suspended and put on care and maintenance in 2017 for cash-flow reasons (Sunday Mail, 1 Oct 2017); under receivership in Nov 2021 with a ZMDC - Fossil Mining Resources JV and an EIA under way (Genesis Environment Consultancy notice); no confirmed restart found. Same operation as 1200209"),
    1199210: ("PRODUCER", "CARE_AND_MAINTENANCE", "Lynx graphite mine, Karoi (Zimbabwe German Graphite Mines; ZMDC / Graphit Kropfmuehl JV): operations suspended and put on care and maintenance in 2017 for cash-flow reasons (Sunday Mail, 1 Oct 2017); under receivership in Nov 2021 with a ZMDC - Fossil Mining Resources JV and an EIA under way (Genesis Environment Consultancy notice); no confirmed restart found. Same operation as 1200209"),
}

ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()

if UNDO:
    rows = list(csv.DictReader(open(UNDO, encoding="utf-8")))
    for r in rows:
        c.execute("UPDATE core.occurrences SET status = %s, comments = %s, modified_by = %s, modified_date = %s WHERE occurrence_id = %s",
                  (r["status"], r["comments"] or None, r["modified_by"] or None, r["modified_date"] or None, int(r["occurrence_id"])))
    g.commit(); print("restored", len(rows)); sys.exit(0)

c.execute("SELECT occurrence_id, name, status, comments, modified_by, modified_date FROM core.occurrences WHERE occurrence_id = ANY(%s) ORDER BY 1",
          (list(CHANGES),))
rows = c.fetchall()
assert len(rows) == len(CHANGES), "missing occurrence rows"
for oid, name, st, *_ in rows:
    exp, new, _ = CHANGES[oid]
    assert st == exp, f"{oid} {name}: status is {st}, expected {exp} - stop"
    print(f"{oid} {name}: {st} -> {new}")
if DRY:
    g.rollback(); print("DRY - nothing changed"); sys.exit(0)
path = os.path.join(HERE, f"graphite_status_lynx_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["occurrence_id", "status", "comments", "modified_by", "modified_date"])
    for oid, _, st, cm, mb, md in rows: w.writerow([oid, st, cm or "", mb or "", md or ""])
for oid, (_, new, note) in CHANGES.items():
    c.execute("""UPDATE core.occurrences SET status = %s, modified_by = %s, modified_date = now(),
                 comments = concat_ws(' | ', comments, %s) WHERE occurrence_id = %s""",
              (new, TAG, f"Status updated 2026-11-24 to {new} from company/official sources: {note}", oid))
g.commit(); print("updated", len(CHANGES), "backup", path)
