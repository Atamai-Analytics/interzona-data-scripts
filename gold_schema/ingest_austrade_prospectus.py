"""Ingest the Australian Critical Minerals Prospectus (Austrade, October 2026) into docs.documents / docs.document_chunks.

Source files (downloaded 2026-10-29 from international.austrade.gov.au, CC BY 4.0 unless noted): the 108-page PDF (text, in page order) and the DOCX (clean data tables).
One chunk per project (94 projects: 58 upstream, 36 midstream):
  * upstream: built from the DOCX - investment summary, project description and the status / resource / reserve tables written out as text (exact, no page-boundary guessing);
  * midstream: built from the PDF page that holds the project (one page each, in the order of the contents list) plus a header.
The front matter (introduction, why Australia, contents) becomes general chunks. A chunk longer than 7,000 characters is split at a paragraph.
Page numbers: midstream projects and the upstream projects whose title is extractable carry their PDF page; a few upstream titles are graphics, so those chunks have no page number.
Embeddings: Voyage voyage-3-large via rag_ingest.embed_batch, like the rest of docs.document_chunks. Chunks carry jurisdiction_id (Australia).
project_id / company_id / occurrence_id / commodity_id are left empty here and filled in by the structured project load that follows.
Usage: python ingest_austrade_prospectus.py --dry | --run
"""
import sys, re, json, hashlib, shutil, os
sys.stdout.reconfigure(encoding="utf8")
sys.path.append(r"C:\Users\dean\AppData\Roaming\Python\Python314\site-packages")
import pymupdf

SP = r"C:\Users\dean\AppData\Local\Temp\claude\C--Users-dean-claude-lithosurfer\6dd1d599-0779-4b85-9cf3-c62682d212bd\scratchpad"
SRC_PDF = SP + r"\austrade_prospectus\prospectus.pdf"
PROJECTS = SP + r"\prospectus_projects_all.json"
DEST_DIR = r"D:\CriticalMineralsDB\Documents\RAG\Ingested"
DEST_PDF = DEST_DIR + r"\australian-critical-minerals-prospectus-october-2026.pdf"
SOURCE_URL = "https://international.austrade.gov.au/en/do-business-with-australia/sectors/energy-and-resources/critical-minerals/prospectus"
TITLE = "Austrade - Australian Critical Minerals Prospectus (October 2026; 94 investment-ready projects; company-supplied data, not verified by Austrade; CC BY 4.0)"
TAG = "claude_austrade_prospectus_20261029"
EMBED_VERSION = "2026-10-29"
DOMAIN = "POLICY"
MAXC = 7000
DRY = "--dry" in sys.argv
if not DRY and "--run" not in sys.argv:
    sys.exit(__doc__)

norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
pj = json.load(open(PROJECTS, encoding="utf8"))
doc = pymupdf.open(SRC_PDF)
pages = [p.get_text("text") for p in doc]
npages = len(pages)


def short(name):  # drop a trailing state list left in by the heading split
    return re.sub(r"\s+(NT|WA|QLD|NSW|VIC|SA|TAS)(,\s*(NT|WA|QLD|NSW|VIC|SA|TAS))*$", "", name).strip()


def n_names_in(text):
    t = norm(text)
    return sum(1 for p in pj if norm(short(p["name"]))[:35] in t)


contents_pages = {i for i, t in enumerate(pages) if n_names_in(t) >= 5}
# 1) by name: the project's name appears in the first 450 characters of one of its pages (some titles are graphics and are missed)
by_name = {}
for pi, p in enumerate(pj):
    key = norm(short(p["name"]))[:35]
    for i, t in enumerate(pages):
        if i in contents_pages or i < 4:
            continue
        if key in norm(t[:450]) and i not in by_name.values():
            by_name[pi] = i
            break
# 2) midstream: one page each, in the order of the contents list
mid_idx = [pi for pi, p in enumerate(pj) if p["stage"] == "midstream"]
mid_pages = [i for i, t in enumerate(pages) if 70 <= i < 106 and re.search(r"midstream summary|company name", t[:900], re.I)]
assert len(mid_pages) == len(mid_idx), (len(mid_pages), len(mid_idx))
mid_page = dict(zip(mid_idx, mid_pages))
for pi, pg in mid_page.items():
    if pi in by_name:
        assert by_name[pi] == pg, ("midstream order mismatch", pj[pi]["name"], by_name[pi], pg)
up_page = {pi: by_name[pi] for pi, p in enumerate(pj) if p["stage"] == "upstream" and pi in by_name}
print(f"PDF pages {npages}; contents pages {sorted(x + 1 for x in contents_pages)}; midstream pages by sequence {len(mid_page)}; upstream pages by name {len(up_page)} of {sum(1 for p in pj if p['stage'] == 'upstream')}")
print("  upstream with no page number:", [p["name"] for pi, p in enumerate(pj) if p["stage"] == "upstream" and pi not in up_page])


def clean(t):
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def table_text(p):
    out = []
    for t in p["tables"]:
        rows = [" | ".join(c for c in r if c) for r in t if any(r)]
        if rows and not (len(t[0]) == 2 and t[0][0].lower().startswith("company name")):
            out.append("\n".join(rows))
    return "\n\n".join(out)


def split_long(text):
    if len(text) <= MAXC:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) > MAXC:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


chunks = []   # dict(page, heading, text, project)
front = clean("\n\n".join(pages[3:9]))
for k, part in enumerate(split_long(front)):
    chunks.append(dict(page=4, heading="Introduction, why Australia and contents" + (f" (part {k + 1})" if k else ""), text=part, project=None))
back = clean("\n\n".join(pages[106:npages]))
if len(back) > 200:
    chunks.append(dict(page=107, heading="Contact and further information", text=back, project=None))
for pi, p in enumerate(pj):
    head = [f"Australian Critical Minerals Prospectus (Austrade, October 2026): {p['name']}",
            f"Stage: {p['stage']} project" + (f"; State or Territory: {p['state']}" if p["state"] else ""),
            (f"Critical minerals: {p['commodities']}" if p["commodities"] else "")]
    h = "\n".join(x for x in head if x)
    if p["stage"] == "upstream":
        sec = p["sections"]
        body = ""
        for key in ("Investment summary", "Project description"):
            if sec.get(key):
                body += key + "\n" + clean(sec[key]) + "\n\n"
        for key, val in sec.items():
            if key not in ("Investment summary", "Project description", "_") and val.strip():
                body += key + "\n" + clean(val) + "\n\n"
        tt = table_text(p)
        text = h + "\n\n" + body.strip() + ("\n\nTables from the Prospectus (resources, reserves and project status as published):\n" + tt if tt else "")
        pg = up_page[pi] + 1 if pi in up_page else None
    else:
        pg0 = mid_page[pi]
        nxt = [v for v in mid_page.values() if v > pg0]
        end = min(nxt) if nxt else min(pg0 + 2, npages)
        text = h + "\n\n" + clean("\n\n".join(pages[pg0:end]))
        pg = pg0 + 1
    for k, part in enumerate(split_long(text)):
        chunks.append(dict(page=pg, heading=p["name"] + (f" (part {k + 1})" if k else ""), text=part, project=p["name"]))
print(f"chunks {len(chunks)}; project chunks {sum(1 for c in chunks if c['project'])}; general chunks {sum(1 for c in chunks if not c['project'])}; projects covered {len({c['project'] for c in chunks if c['project']})} of {len(pj)}")
L = sorted(len(c["text"]) for c in chunks)
print(f"chars: min {L[0]}, median {L[len(L) // 2]}, max {L[-1]}, total {sum(L)}")
short_ones = [(c["heading"], len(c["text"])) for c in chunks if len(c["text"]) < 900]
print("short chunks (<900 chars):", short_ones)
for want in ("Butcherbird High Purity Manganese Project", "Nolans Rare Earths Project", "Hillgrove"):
    c = next((c for c in chunks if c["project"] and want.lower() in c["project"].lower()), None)
    if c:
        print(f"\n--- sample chunk: {c['heading']} (page {c['page']}, {len(c['text'])} chars) ---\n" + c["text"][:1500])
if DRY:
    sys.exit("\nDRY - nothing copied, embedded or written")

# ---- write -------------------------------------------------------------------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag_ingest import load_env, get_conn, embed_batch, VOYAGE_MODEL
env = load_env()
g = get_conn(env)
g.autocommit = False
c = g.cursor()
c.execute("SELECT document_id FROM docs.documents WHERE created_by = %s", (TAG,))
if c.fetchone():
    sys.exit("already ingested (a document with this tag exists)")
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE name = 'Australia' AND level = 'COUNTRY' ORDER BY jurisdiction_id LIMIT 1")
r = c.fetchone()
jur = r[0] if r else None
print("Australia jurisdiction_id:", jur)
os.makedirs(DEST_DIR, exist_ok=True)
if not os.path.exists(DEST_PDF):
    shutil.copy2(SRC_PDF, DEST_PDF)
assert hashlib.sha256(open(DEST_PDF, "rb").read()).hexdigest() == hashlib.sha256(open(SRC_PDF, "rb").read()).hexdigest()
c.execute("""INSERT INTO docs.documents (title, domain, document_type, jurisdiction_id, publication_date, source_url, file_path, page_count, language, is_active, created_by, created_date)
             VALUES (%s,%s,'Prospectus',%s,'2026-10-19',%s,%s,%s,'en',true,%s,now()) RETURNING document_id""",
          (TITLE, DOMAIN, jur, SOURCE_URL, DEST_PDF, npages, TAG))
doc_id = c.fetchone()[0]
embs = embed_batch([ch["text"] for ch in chunks], env["VOYAGE_API_KEY"])
assert len(embs) == len(chunks)
for i, (ch, emb) in enumerate(zip(chunks, embs)):
    c.execute("""INSERT INTO docs.document_chunks (document_id, domain, chunk_index, page_number, section_heading, content, token_count, embedding, embedding_model, embedding_version,
                 section_type, jurisdiction_id, created_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,'BODY',%s,now())""",
              (doc_id, DOMAIN, i, ch["page"], ch["heading"][:250], ch["text"], max(1, round(len(ch["text"]) / 4.1)),
               "[" + ",".join(f"{x:.8f}" for x in emb) + "]", VOYAGE_MODEL, EMBED_VERSION, jur))
c.execute("SELECT count(*), count(embedding) FROM docs.document_chunks WHERE document_id = %s", (doc_id,))
n, ne = c.fetchone()
if n == ne == len(chunks):
    g.commit()
    print(f"COMMITTED: document_id {doc_id}, {n} chunks")
else:
    g.rollback()
    print("CHECK FAILED - rolled back")
