"""Read the company box on each upstream page of the Austrade Prospectus PDF by looking at the page image (the PDF text does not line up with projects).
For each page 10-68 the model sees the page and the list of 58 upstream project names and returns, for every project whose entry or footer box is on that page,
the company box as printed (company, listing/ownership, website, state, commodities). Results are merged by project and checked against the DOCX state.
Read-only; writes austrade_company_boxes_vision.json / .csv to the scratchpad. Usage: python austrade_company_boxes_vision.py"""
import sys, re, json, csv, os, base64, time
sys.stdout.reconfigure(encoding="utf8")
sys.path.append(r"C:\Users\dean\AppData\Roaming\Python\Python314\site-packages")
import pymupdf, anthropic

SP = r"C:\Users\dean\AppData\Local\Temp\claude\C--Users-dean-claude-lithosurfer\6dd1d599-0779-4b85-9cf3-c62682d212bd\scratchpad"
pj = json.load(open(SP + r"\prospectus_projects_all.json", encoding="utf8"))
up = [p for p in pj if p["stage"] == "upstream"]
env = {}
for l in open(r"C:\Users\dean\critical-minerals-ai\.env.local", encoding="utf8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.rstrip("\r\n").split("=", 1); env[k] = v.strip('"')
client = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
doc = pymupdf.open(SP + r"\austrade_prospectus\prospectus.pdf")
names = [p["name"] for p in up]
TOOL = {"name": "record", "description": "Record the company box(es) printed on this page.",
        "input_schema": {"type": "object", "properties": {"entries": {"type": "array", "items": {"type": "object", "properties": {
            "project": {"type": "string", "description": "Exactly one name from the project list that this page belongs to (its title or its content), or 'UNKNOWN'."},
            "company": {"type": "string", "description": "Company name exactly as printed in the company box at the foot of the page; empty if there is no box."},
            "listing_ownership": {"type": "string", "description": "The listing / ownership line(s) printed in the box, as printed."},
            "website": {"type": "string"}, "state": {"type": "string", "description": "State or territory printed in the box."},
            "commodities": {"type": "string", "description": "Commodity(ies) line printed in the box."},
            "title_visible": {"type": "boolean", "description": "True if the project's title is printed on this page."}},
            "required": ["project", "company", "listing_ownership", "state", "title_visible"]}}},
            "required": ["entries"]}}
SYS = ("You read one page of the Australian Critical Minerals Prospectus. A page may carry the entry of one project (title at the top, then text and tables, and a company box at the foot "
       "with the company, listing or ownership, website, 'Commodity(ies):' and the state) or the second page of a project (usually without the title, but with the company box at the foot). "
       "Report what is printed in the company box and which project from the given list the page belongs to (use the title, the text and the project names to decide). "
       "Do not guess a company that is not printed. If a box is not on the page, return an empty company. Call the record tool once.")
rows = []
for pg in range(9, 68):
    pix = doc[pg].get_pixmap(dpi=100)
    img = base64.b64encode(pix.tobytes("png")).decode()
    for _ in range(3):
        try:
            r = client.messages.create(model="claude-sonnet-5-5", max_tokens=1500, system=SYS, tools=[TOOL],
                                       messages=[{"role": "user", "content": [
                                           {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
                                           {"type": "text", "text": "Upstream project list:\n" + "\n".join(f"- {n}" for n in names) + f"\n\nThis is PDF page {pg + 1}."}]}])
            j = next((b.input for b in r.content if b.type == "tool_use"), None)
            if j:
                for e in j["entries"]:
                    e["page"] = pg + 1; rows.append(e)
                print(f"p{pg + 1}: " + " | ".join(f"{e['project'][:30]} -> {e['company'][:30]} ({e['state']})" for e in j["entries"]), flush=True)
                break
        except Exception as ex:
            time.sleep(3)
by = {}
for e in rows:
    if e["project"] in names and e["company"]:
        by.setdefault(e["project"], []).append(e)
final = []
for p in up:
    es = by.get(p["name"], [])
    best = es[-1] if es else None
    mism = bool(best and best["state"] and p["state"] and best["state"].split()[0].strip(",") not in p["state"] and p["state"] not in best["state"])
    final.append(dict(project=p["name"], state_docx=p["state"], company=best["company"] if best else "", listing_ownership=best["listing_ownership"] if best else "", website=best.get("website", "") if best else "",
                      state_box=best["state"] if best else "", commodities_box=best.get("commodities", "") if best else "", page=best["page"] if best else "", n_boxes=len(es), state_mismatch=mism))
json.dump(dict(pages=rows, projects=final), open(SP + r"\austrade_company_boxes_vision.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
with open(SP + r"\austrade_company_boxes_vision.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(final[0])); w.writeheader(); w.writerows(final)
print(f"\nprojects with a company box: {sum(1 for f in final if f['company'])} of {len(final)}; state mismatches vs DOCX: {[f['project'] for f in final if f['state_mismatch']]}")
print("no box:", [f["project"] for f in final if not f["company"]])
