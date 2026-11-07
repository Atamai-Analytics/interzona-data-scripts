"""Load library documents (PDFs) into docs.documents / docs.document_chunks from an approved manifest.

The manifest is a JSON list; each entry:
  {"file": "<path relative to --root>", "title": "...", "domain": "POLICY|RESEARCH|SUPPLY_CHAIN|TECHNOLOGY|TECHNICAL_REPORT|ANNUAL_REPORT",
   "dtype": "Report", "pdate": "YYYY-MM-DD" or null, "url": "..." or null, "label": "short chunk prefix",
   "ocr": "<cache name>" (optional: use ocr_<name>.json from rag_ocr.py instead of the PDF's text layer),
   "types": {"TABLE_OF_CONTENTS": [2, [3, 4]], "REFERENCES": [[40, 52]]} (optional: pages forced to a section type)}

Chunks are ~900 words with 100 words overlap, prefixed with "[label]", embedded with voyage-3-large (same as the rest of the library).
Writes with the app's write role from critical-minerals-ai/.env.local. A file already registered (same file name) is skipped.

Usage: python rag_ingest_manifest.py <manifest.json> --root <folder> --by <created_by tag> [--dry] [file ...]
"""
import os, re, sys, json, time, collections, requests, psycopg2, pymupdf

ENV = {}
for l in open(r"C:\Users\dean\critical-minerals-ai\.env.local", encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip()

TARGET, OVERLAP = 900, 100
VERSION = "2026-10-08"
OCR_CACHE = os.environ.get("OCR_CACHE", "C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/1de38d20-e452-45b6-a85d-8f80b8fca969/scratchpad")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def classify(text, idx):
    head = text[:400].lower()
    if idx < 8:
        lines = [l for l in text.split("\n") if l.strip()]
        numbered = sum(1 for l in lines if re.search(r"(\d+\s*$)|(\.{3,})", l))
        if ("contents" in head or "table of contents" in head) and numbered >= 8:
            return "TABLE_OF_CONTENTS"
    legal_hits = len(re.findall(r"(without prejudice|terms and conditions|disclaimer|creative commons|this publication and any map|reproduction|liability)", text.lower()))
    if idx < 5 and legal_hits >= 3 and len(text.split()) < 350:
        return "LEGAL"
    return "BODY"


def embed(texts):
    for attempt in range(4):
        try:
            r = requests.post("https://api.voyageai.com/v1/embeddings",
                              headers={"Authorization": f"Bearer {ENV['VOYAGE_API_KEY']}"},
                              json={"input": texts, "model": "voyage-3-large", "input_type": "document"}, timeout=180)
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]
        except Exception as e:
            print("embed retry", attempt, e, file=sys.stderr); time.sleep(3 + 3 * attempt)
    raise RuntimeError("embedding failed")


def page_texts(path, m):
    """[(page_no, text)] from the OCR cache when the entry names one, else from the PDF's text layer."""
    if m.get("ocr"):
        data = json.load(open(os.path.join(OCR_CACHE, f"ocr_{m['ocr']}.json"), encoding="utf-8"))
        return [(int(k), data[k]) for k in sorted(data, key=int)]
    doc = pymupdf.open(path)
    return [(i + 1, doc[i].get_text()) for i in range(len(doc))]


def build_chunks(path, m):
    forced = {}
    for typ, spec in m.get("types", {}).items():
        for item in spec:
            for p in (range(item[0], item[1] + 1) if isinstance(item, list) else [item]):
                forced[p] = typ
    pages = []
    for pno, raw in page_texts(path, m):
        t = re.sub(r"[ \t]+", " ", raw).strip()
        if len(t.split()) >= 5:
            pages.append((pno, t, forced.get(pno) or classify(t, pno - 1)))
    chunks, cur_type, buf, start = [], None, [], None

    def flush():
        nonlocal buf, start
        if buf:
            chunks.append((start, cur_type, " ".join(buf)))
        buf, start = [], None

    for pno, t, typ in pages:
        if typ != cur_type:
            flush(); cur_type = typ
        if typ != "BODY":
            if start is None: start = pno
            buf.extend(t.split()); continue
        for w in t.split():
            if start is None: start = pno
            buf.append(w)
            if len(buf) >= TARGET:
                chunks.append((start, "BODY", " ".join(buf)))
                buf = buf[-OVERLAP:]; start = pno
    flush()
    return [(p, ty, f"[{m['label']}] {txt}") for p, ty, txt in chunks]


def main():
    manifest, root, by = sys.argv[1], arg("--root"), arg("--by")
    dry = "--dry" in sys.argv
    skip = {manifest, root, by}
    only = [a for a in sys.argv[2:] if not a.startswith("--") and a not in skip]
    if not root or not by:
        sys.exit("need --root and --by")
    M = json.load(open(manifest, encoding="utf-8"))
    conn = cur = None
    if not dry:
        conn = psycopg2.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"],
                                user=ENV["PGUSER_WRITE"], password=ENV["PGPASSWORD_WRITE"])
        cur = conn.cursor()
    tot = 0
    for m in M:
        if only and m["file"] not in only: continue
        path = os.path.join(root, m["file"])
        if cur:
            cur.execute("SELECT document_id FROM docs.documents WHERE file_path LIKE %s", ("%" + os.path.basename(path),))
            if cur.fetchone():
                print("SKIP (already registered):", m["file"]); continue
        npages = len(pymupdf.open(path))
        chunks = build_chunks(path, m)
        cnt = dict(collections.Counter(c[1] for c in chunks))
        if dry:
            words = sum(len(c[2].split()) for c in chunks)
            print(f"DRY {m['file'][:58]:58s} pages={npages:3d} chunks={len(chunks):3d} words={words:6d} {cnt}"); tot += len(chunks); continue
        vecs = []
        for i in range(0, len(chunks), 16):
            vecs += embed([c[2] for c in chunks[i:i + 16]]); time.sleep(0.2)
        cur.execute("""INSERT INTO docs.documents (title, domain, document_type, publication_date, source_url, file_path, page_count, language, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING document_id""",
                    (m["title"], m["domain"], m["dtype"], m.get("pdate"), m.get("url"), path, npages, m.get("language", "en"), by))
        doc_id = cur.fetchone()[0]
        for idx, ((pg, typ, txt), v) in enumerate(zip(chunks, vecs)):
            cur.execute("""INSERT INTO docs.document_chunks (document_id, domain, chunk_index, page_number, section_heading, content,
                           token_count, embedding, embedding_model, embedding_version, section_type, company_id)
                           VALUES (%s,%s,%s,%s,NULL,%s,%s,%s::vector,'voyage-3-large',%s,%s,NULL)""",
                        (doc_id, m["domain"], idx, pg, txt, len(txt.split()), "[" + ",".join(f"{x:.6f}" for x in v) + "]", VERSION, typ))
        conn.commit()
        nb = sum(1 for c in chunks if c[1] == "BODY")
        print(f"OK doc {doc_id}: {len(chunks)} chunks ({nb} body) from {npages} pages | {m['domain']} | {m['file']}", flush=True); tot += len(chunks)
    print("TOTAL chunks", tot)
    if conn: conn.close()


if __name__ == "__main__":
    main()
