"""Link companies to projects that have none (26 Nov 2026, part of "project gaps").
- NRCan critical-minerals projects (migration_nrcan_projects_20261103): the description carries "operator/owners: X; ...". The FIRST named
  owner (NRCan lists the operator first; '/'-separated partners and a trailing '(...)' are dropped, the bracket goes to short_name) is
  matched case-insensitively (trailing '.' ignored) to an existing company, else created. Website from "website: ..." when the
  project names one. HQ left NULL (not guessed). 59 projects name no owner and stay without a company.
- 3 Austrade Prospectus joint ventures: linked to the manager / majority holder as published.
Backup: project_owners_backup_<stamp>.csv; rollback: python project_owners_20261126.py --undo <backup.csv> (deletes companies it created).
Usage: python project_owners_20261126.py [--dry | --undo backup.csv]
"""
import csv, os, re, sys, time, psycopg2

DRY = "--dry" in sys.argv
UNDO = sys.argv[sys.argv.index("--undo") + 1] if "--undo" in sys.argv else None
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "project_owners_20261126"
AUSTRADE = {719: ("GCM Corporation Ltd", "GCM (80%, with NH3 Clean Energy 20%)"),
            720: ("Quantum Graphite Ltd", "Quantum Graphite (with Sunlands Pure Investments)"),
            739: ("Wyloo Gascoyne Pty Ltd", "Wyloo (manager, 60%; Hastings Technology Metals 40%)")}

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
        c.execute("UPDATE core.projects SET company_id=NULL, modified_by=%s, modified_date=%s WHERE project_id=%s",
                  (r["modified_by"] or None, r["modified_date"] or None, int(r["project_id"])))
    c.execute("DELETE FROM core.companies WHERE created_by = %s", (TAG,))
    g.commit(); print("restored", len(rows), "projects; deleted companies", c.rowcount); sys.exit(0)

SUFFIX = r"(the|ltd|limited|inc|incorporated|corp|corporation|co|company|plc|llc|lp|nl|sa|ag|ab|asa|group|holdings|pty|nv)"
def norm(s):
    t = re.sub(r"[^\w\s&]", " ", s.lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\bs a$", "sa", re.sub(r"\bn v$", "nv", t))
    while True:
        u = re.sub(rf"\s{SUFFIX}$", "", t)
        if u == t: break
        t = u
    return t
ALIAS = {norm("Magneto Investments Limited Partnership"): norm("Dumont Nickel Limited Partnership")}  # former name (Dumont)
c.execute("SELECT company_id, name FROM core.companies")
EXIST = {norm(n): i for i, n in c.fetchall()}

c.execute("""SELECT project_id, created_by, description, modified_by, modified_date FROM core.projects
             WHERE is_active AND company_id IS NULL ORDER BY project_id""")
rows = c.fetchall()
plan, new = {}, {}  # project_id -> company key ; key -> (name, short, website)
for pid, cb, desc, mb, md in rows:
    if pid in AUSTRADE:
        name, short = AUSTRADE[pid]; key = norm(name)
        if key not in EXIST: new.setdefault(key, (name, short, None))
        plan[pid] = key; continue
    if cb != "migration_nrcan_projects_20261103": continue
    m = re.search(r"operator/owners: ([^;]*)", desc or "")
    if not m: continue
    first = m.group(1).split(" / ")[0].strip()
    b = re.match(r"^(.*?)\s*\((.*)\)\s*$", first)
    name, short = (b.group(1).strip(), b.group(2).strip()) if b else (first, None)
    name = re.sub(r"\.$", "", name) if name.endswith("Group.") else name
    key = norm(name)
    key = ALIAS.get(key, key)
    web = re.search(r"website: ((?:https?://|www\.)\S+)", desc or "")
    if key not in EXIST:
        cur = new.get(key)
        new[key] = (name, (cur[1] if cur else None) or short, (cur[2] if cur else None) or (web.group(1).rstrip(";,") if web else None))
    plan[pid] = key
linked_existing = sum(1 for k in plan.values() if k in EXIST)
print(f"{len(plan)} projects to link: {linked_existing} to existing companies, {len(plan) - linked_existing} to {len(new)} new companies; "
      f"{sum(1 for r in rows if r[0] not in plan)} left without a company")
if DRY:
    for k, v in list(new.items())[:12]: print("  new:", v)
    print("  existing matches:", sorted({k for k in plan.values() if k in EXIST}))
    g.rollback(); print("DRY - nothing changed"); sys.exit(0)

path = os.path.join(HERE, f"project_owners_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["project_id", "modified_by", "modified_date"])
    for pid, cb, desc, mb, md in rows:
        if pid in plan: w.writerow([pid, mb or "", md or ""])
ids = dict(EXIST)
for key, (name, short, web) in new.items():
    if web and not web.startswith("http"): web = "https://" + web
    c.execute("INSERT INTO core.companies (name, short_name, website, is_active, created_by, created_date) VALUES (%s,%s,%s,true,%s,now()) RETURNING company_id",
              (name, short, web, TAG))
    ids[key] = c.fetchone()[0]
for pid, key in plan.items():
    c.execute("UPDATE core.projects SET company_id=%s, modified_by=%s, modified_date=now() WHERE project_id=%s AND company_id IS NULL", (ids[key], TAG, pid))
g.commit(); print("done; backup", path)
