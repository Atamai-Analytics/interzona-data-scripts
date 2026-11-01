"""Read-only dry run for part 2 of the Austrade Prospectus load: the company behind each of the 94 projects.
Midstream: the Prospectus' own company table (reliable). Upstream: the PDF's company boxes do not line up with the projects, so a model reads the project's
investment summary and description and returns the owner/operator, ownership and listing as the text states them (nothing from memory); the PDF boxes on the same
page are given only as hints. Each company is then matched to core.companies by a normalised name. Output: a review CSV; nothing is written to the database.
Usage: python austrade_companies_dryrun.py"""
import sys, re, json, csv, os, time
sys.stdout.reconfigure(encoding="utf8")
sys.path.append(r"C:\Users\dean\AppData\Roaming\Python\Python314\site-packages")
import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rag_ingest import load_env, get_conn
SP = r"C:\Users\dean\AppData\Local\Temp\claude\C--Users-dean-claude-lithosurfer\6dd1d599-0779-4b85-9cf3-c62682d212bd\scratchpad"
pj = json.load(open(SP + r"\prospectus_projects_all.json", encoding="utf8"))
key_env = {}
for l in open(r"C:\Users\dean\critical-minerals-ai\.env.local", encoding="utf8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.rstrip("\r\n").split("=", 1); key_env[k] = v.strip('"')
client = anthropic.Anthropic(api_key=key_env["ANTHROPIC_API_KEY"])
con = get_conn(load_env()); con.set_session(readonly=True, autocommit=True); cur = con.cursor()
cur.execute("SELECT company_id, name FROM core.companies WHERE is_active")
companies = cur.fetchall()

def nkey(n):
    n = n.lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"\b(limited|ltd|pty|inc|corp|corporation|nl|plc|group|holdings|company|co|the|resources|metals|minerals|mining|energy)\b", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)

ckeys = [(i, n, nkey(n)) for i, n in companies]
TOOL = {"name": "record", "description": "Record who owns or operates the project, as the text states it.",
        "input_schema": {"type": "object", "properties": {
            "company": {"type": "string", "description": "The company that owns or operates the project, exactly as named in the text (e.g. 'Element 25 Ltd'). Empty if the text does not say."},
            "ownership": {"type": "string", "description": "Listing or ownership as stated (e.g. 'ASX-listed (E25)', 'private', 'joint venture of A (60%) and B (40%)'). Empty if not stated."},
            "partners": {"type": "string", "description": "Other named owners, partners or offtakers' stakes in the project as stated; empty if none."},
            "evidence": {"type": "string", "description": "A short quote (under 25 words) from the text that names the company."}},
            "required": ["company", "ownership", "partners", "evidence"]}}
SYS = ("You read one project entry from the Austrade Australian Critical Minerals Prospectus and report who owns or operates the project, using ONLY the text given. "
       "Do not use outside knowledge. If the text does not name the company, return an empty company. Copy names as written. Call the record tool once.")
rows = []
for p in pj:
    if p["stage"] == "midstream":
        t = next((t for t in p["tables"] if t and t[0] and t[0][0].lower().startswith("company name")), None)
        d = {r[0].rstrip(":").lower(): r[1] for r in (t or []) if len(r) >= 2}
        co, own, part, ev, src = d.get("company name", ""), d.get("company ownership", ""), "", "Prospectus company table", "table"
    else:
        text = (p["sections"].get("Investment summary", "") + "\n" + p["sections"].get("Project description", ""))[:3500]
        co = own = part = ev = ""
        for _ in range(3):
            try:
                r = client.messages.create(model="claude-sonnet-5-5", max_tokens=700, system=SYS, tools=[TOOL],
                                           messages=[{"role": "user", "content": f"PROJECT: {p['name']} ({p['state']})\n\nTEXT:\n{text}"}])
                j = next((b.input for b in r.content if b.type == "tool_use"), None)
                if j:
                    co, own, part, ev = j["company"], j["ownership"], j["partners"], j["evidence"]
                    break
            except Exception as e:
                time.sleep(2)
        src = "model from text"
    k = nkey(co) if co else ""
    m = [(i, n) for i, n, kk in ckeys if k and len(k) >= 4 and (kk == k or (len(kk) >= 5 and (kk in k or k in kk)))]
    rows.append(dict(stage=p["stage"], project=p["name"], state=p["state"], commodities=p["commodities"], company=co, ownership=own, partners=part, evidence=ev, source=src,
                     existing_company="; ".join(f"{i}:{n}" for i, n in m[:3])))
    print(f"{p['stage'][:3]} {p['name'][:40]:40s} | {co[:34]:34s} | {own[:28]:28s} | {'EXISTS ' + rows[-1]['existing_company'][:30] if m else ''}", flush=True)
out = SP + r"\austrade_companies_dryrun.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
cos = {nkey(r["company"]) for r in rows if r["company"]}
ex = {nkey(r["company"]) for r in rows if r["company"] and r["existing_company"]}
print(f"\n{len(rows)} projects; {sum(1 for r in rows if r['company'])} with a named company; {len(cos)} distinct companies; {len(ex)} already in core.companies; {len(cos) - len(ex)} would be new")
print("no company named:", [r["project"] for r in rows if not r["company"]])
print("csv:", out)
