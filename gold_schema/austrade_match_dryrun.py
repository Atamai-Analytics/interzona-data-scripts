"""Read-only: how many of the 94 Austrade Prospectus projects already match a core.project, core.occurrence or core.company? Writes a review CSV.
Usage: python austrade_match_dryrun.py"""
import sys, re, json, csv, os
sys.stdout.reconfigure(encoding="utf8")
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rag_ingest import load_env, get_conn
SP = r"C:\Users\dean\AppData\Local\Temp\claude\C--Users-dean-claude-lithosurfer\6dd1d599-0779-4b85-9cf3-c62682d212bd\scratchpad"
pj = json.load(open(SP + r"\prospectus_projects_all.json", encoding="utf8"))
con = get_conn(load_env())
con.set_session(readonly=True, autocommit=True)
c = con.cursor()
STOP = {"project", "projects", "mine", "hub", "the", "and", "of", "facility", "plant", "refinery", "processing", "critical", "minerals", "mineral", "australian", "pty", "ltd", "limited", "stage", "first", "new", "expansion"}

def key(name):
    n = re.sub(r"\(.*?\)", " ", name)
    n = re.sub(r"[^A-Za-z0-9 ]+", " ", n)
    w = [x for x in n.split() if x.lower() not in STOP and len(x) > 2]
    return w

c.execute("SELECT project_id, name FROM core.projects WHERE is_active")
projects = c.fetchall()
c.execute("SELECT company_id, name FROM core.companies WHERE is_active")
companies = c.fetchall()
rows = []
for p in pj:
    w = key(p["name"])
    k = " ".join(w[:2]) if w else p["name"]
    # core.projects: any word-pair or whole-name containment
    pm = [(i, n) for i, n in projects if k and (k.lower() in n.lower() or (w and w[0].lower() in n.lower().split()))]
    # occurrences: same words in the name, Australia
    om = []
    if k:
        c.execute("""SELECT occurrence_id, name, status, occurrence_type_name FROM core.occurrences
                     WHERE is_active AND country_name = 'Australia' AND name ILIKE %s LIMIT 6""", ("%" + k + "%",))
        om = c.fetchall()
    co = ""
    tabs = [t for t in p["tables"] if t and t[0] and t[0][0].lower().startswith("company name")]
    if tabs:
        co = tabs[0][0][1]
    cm = [(i, n) for i, n in companies if co and re.sub(r"[^a-z0-9]", "", co.lower())[:10] and re.sub(r"[^a-z0-9]", "", co.lower())[:10] in re.sub(r"[^a-z0-9]", "", n.lower())]
    rows.append(dict(stage=p["stage"], name=p["name"], state=p["state"], company_from_table=co, project_matches="; ".join(f"{i}:{n}" for i, n in pm[:3]),
                     occurrence_matches="; ".join(f"{i}:{n} [{s}]" for i, n, s, t in om[:4]), company_matches="; ".join(f"{i}:{n}" for i, n in cm[:2])))
out = os.path.join(SP, "austrade_match_dryrun.csv")
with open(out, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
n = len(rows)
print(f"{n} Prospectus projects")
print(f"  with a name match in core.projects: {sum(1 for r in rows if r['project_matches'])}")
print(f"  with a name match in Australian core.occurrences: {sum(1 for r in rows if r['occurrence_matches'])}")
mid = [r for r in rows if r["stage"] == "midstream"]
print(f"  midstream with a company named in the Prospectus table: {sum(1 for r in mid if r['company_from_table'])} of {len(mid)}; of those, company already in core.companies: {sum(1 for r in mid if r['company_matches'])}")
print("project matches:", [(r["name"], r["project_matches"]) for r in rows if r["project_matches"]][:12])
print("sample occurrence matches:", [(r["name"], r["occurrence_matches"][:80]) for r in rows if r["occurrence_matches"]][:8])
print("csv:", out)
