"""East African graphite: update the status of 10 occurrences (mostly USGS Africa 2021 / WMED rows that reflect ~2018 stages)
to their 2026 stage, each confirmed from a company or official source (user OK 2026-11-24, "Yes, verify from company sources").
The S&P Global map of Oct 2026 was used only as a lead and is NOT cited; projects not confirmed from a company/official source are left.
A dated note with the source is appended to comments; modified_by = this tag.
Backup: graphite_status_backup_<stamp>.csv (occurrence_id, status, comments, modified_by, modified_date).
Rollback: python fix_graphite_status_east_africa_20261124.py --undo <backup.csv>
Usage: python fix_graphite_status_east_africa_20261124.py [--dry | --undo backup.csv]
"""
import csv, os, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "fix_graphite_status_20261124"

# occurrence_id: (expected current status, new status, note)
CHANGES = {
    1199856: ("FEASIBILITY", "PRODUCER", "Molo (NextSource Materials): Phase 1 (17 kt/y concentrate) in production and exporting via Toliara; Phase 2 expansion FS July 2026, no decision yet (NextSource releases)"),
    1199736: ("FEASIBILITY", "PRODUCER", "Lindi Jumbo (Lindi Jumbo Ltd): producing, reported at 40 kt/y capacity by June 2025; owner Walkabout Resources in administration since Nov 2024; Tanzanian state 16% via Ndovu Graphite JV signed 28 May 2026 (TanzaniaInvest/government)"),
    1198526: ("PRODUCER", "CARE_AND_MAINTENANCE", "Graphmada (Greenwing Resources): on care and maintenance since 2020, still so in the April 2026 quarterly report (Greenwing ASX)"),
    1200164: ("DEVELOPMENT", "CARE_AND_MAINTENANCE", "Vatomina (Total Graphite): was producing; production temporarily halted July 2026 for optimisation, restart targeted December 2026 (Total Graphite RNS 17 Jul 2026)"),
    1198682: ("PRODUCER", "CARE_AND_MAINTENANCE", "Ancuabe mine (AMG Graphit Kropfmuehl): operations suspended under force majeure after insurgent attacks, about June 2022 (Zitamar); no confirmed restart found"),
    1200209: ("EXPLORATION", "CARE_AND_MAINTENANCE", "Zimbabwe German Graphite Mines (Lynx mine, Karoi; ZMDC / Graphit Kropfmuehl JV): put on care and maintenance in 2017 for cash-flow reasons; no confirmed restart found"),
    1199301: ("EXPLORATION", "FEASIBILITY", "Balama Central (Total Graphite, ex Battery Minerals): feasibility study 2018 (58 kt/y, 27 yr), mining licence granted Nov 2021; not in construction"),
    1199796: ("EXPLORATION", "FEASIBILITY", "Maniry (Evion Group): DFS 2022 (up to 60 kt/y), mining permits granted July 2026, financing/FID pending (Evion ASX); see also 578946"),
    1199662: ("EXPLORATION", "FEASIBILITY", "Kitgum = Orom-Cross project (Blencowe Resources): DFS December 2025, model update May 2026, Phase 1 first production targeted H1 2027, funding not closed (Blencowe RNS)"),
    1199471: ("FEASIBILITY", "DEVELOPMENT", "Epanko (EcoGraf): bankable feasibility study, special mining licence held, KfW IPEX-Bank lead lender (up to USD 105m) and compensation under way; no FID yet (EcoGraf ASX)"),
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
path = os.path.join(HERE, f"graphite_status_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["occurrence_id", "status", "comments", "modified_by", "modified_date"])
    for oid, _, st, cm, mb, md in rows: w.writerow([oid, st, cm or "", mb or "", md or ""])
for oid, (_, new, note) in CHANGES.items():
    c.execute("""UPDATE core.occurrences SET status = %s, modified_by = %s, modified_date = now(),
                 comments = concat_ws(' | ', comments, %s) WHERE occurrence_id = %s""",
              (new, TAG, f"Status updated 2026-11-24 to {new} from company/official sources: {note}", oid))
g.commit(); print("updated", len(CHANGES), "backup", path)
