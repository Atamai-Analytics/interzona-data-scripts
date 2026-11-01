import sys, re, json, csv, os
sys.stdout.reconfigure(encoding="utf8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag_ingest import load_env, get_conn
SP = r"C:\Users\dean\AppData\Local\Temp\claude\C--Users-dean-claude-lithosurfer\6dd1d599-0779-4b85-9cf3-c62682d212bd\scratchpad"
pj = json.load(open(SP + r"\prospectus_projects_all.json", encoding="utf8"))
vis = {r["project"]: r for r in json.load(open(SP + r"\austrade_company_boxes_vision.json", encoding="utf8"))["projects"]}
con = get_conn(load_env()); con.set_session(readonly=True, autocommit=True); cur = con.cursor()
cur.execute("SELECT company_id, name FROM core.companies WHERE is_active"); comps = cur.fetchall()
def clean_name(n):
    n = re.sub(r"\s*\((?:Core|Atlantic|Wyloo|UltraHPQ|[A-Z]{2,5}|[^)]*%[^)]*)\)\s*", " ", n).strip()
    return re.sub(r"\s+", " ", n)
def nkey(n):
    n = clean_name(n).lower()
    n = re.sub(r"\b(limited|ltd|pty|inc|corp|corporation|nl|plc|the)\b", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)
ck = [(i, n, nkey(n)) for i, n in comps]
names = {}
for p in pj:
    if p["stage"] == "midstream":
        t = next((t for t in p["tables"] if t and t[0] and t[0][0].lower().startswith("company name")), None)
        d = {r[0].rstrip(":").lower(): r[1] for r in (t or []) if len(r) >= 2}
        co = d.get("company name", "")
    else:
        co = vis.get(p["name"], {}).get("company", "")
    if co: names.setdefault(nkey(co), set()).add(clean_name(co))
rows = []
for k, vs in sorted(names.items(), key=lambda kv: sorted(kv[1])[0]):
    label = sorted(vs, key=len)[0]
    ex = [(i, n) for i, n, kk in ck if kk == k]
    near = [(i, n) for i, n, kk in ck if not ex and len(k) >= 5 and len(kk) >= 5 and (k in kk or kk in k)]
    rows.append((label, ex, near))
print("distinct companies:", len(rows), "| exact existing:", sum(1 for r in rows if r[1]), "| near (review):", sum(1 for r in rows if r[2]), "| new:", sum(1 for r in rows if not r[1]))
for label, ex, near in rows:
    if ex or near: print(f"  {label[:40]:40s} -> {'EXACT ' + str(ex[0]) if ex else 'NEAR ' + str(near[:2])}")
print("new:", [r[0] for r in rows if not r[1]][:80])
