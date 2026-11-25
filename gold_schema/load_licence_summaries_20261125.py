"""Load the own-words summaries written on 25 Nov 2026 for library documents whose full text was moved to licence_hold
(library_hold_20261125*.sql). Each summary becomes a NEW document (created_by claude_licence_summaries_20261125, type Summary,
same domain / publication date / URL as the original), chunked at ~350 words and embedded by load_text_summary.py.
The summary files are copied to D:/CriticalMineralsDB/Documents/RAG/Ingest/summaries_20261125_licence/summary_lic20261125_<id>.txt.
A mapping original id -> summary id is written to summaries_20261125_licence/mapping.tsv.

Usage: python load_licence_summaries_20261125.py <dir with <id>.txt summaries> [--dry] [--only id,id]
"""
import os, re, shutil, subprocess, sys, psycopg2
from rag_ingest_manifest import ENV

SRC = sys.argv[1]
DEST = r"D:\CriticalMineralsDB\Documents\RAG\Ingest\summaries_20261125_licence"
BY = "claude_licence_summaries_20261125"
os.makedirs(DEST, exist_ok=True)
only = None
if "--only" in sys.argv:
    only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}

conn = psycopg2.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"], user=ENV["PGUSER"], password=ENV["PGPASSWORD"])
cur = conn.cursor()
mapping = []
for fn in sorted(os.listdir(SRC), key=lambda f: int(f.split(".")[0]) if f.split(".")[0].isdigit() else 10**9):
    m = re.fullmatch(r"(\d+)\.txt", fn)
    if not m: continue
    oid = int(m.group(1))
    if only and oid not in only: continue
    cur.execute("SELECT title, domain, to_char(publication_date,'YYYY-MM-DD'), source_url FROM docs.documents WHERE document_id = %s", (oid,))
    title, domain, pdate, url = cur.fetchone()
    text = open(os.path.join(SRC, fn), encoding="utf-8").read().strip()
    if not text.startswith("ABOUT THIS DOCUMENT"):
        print(f"SKIP {oid}: summary does not start with ABOUT THIS DOCUMENT"); continue
    dest = os.path.join(DEST, f"summary_lic20261125_{oid}.txt")
    shutil.copyfile(os.path.join(SRC, fn), dest)
    short = re.sub(r"\s*\(.*$", "", title)[:90]
    args = [sys.executable, "load_text_summary.py", dest,
            "--title", f"Interzona summary (own words): {title}"[:500],
            "--label", f"Interzona summary of: {short}",
            "--by", BY, "--domain", domain or "POLICY", "--dtype", "Summary", "--target", "350"]
    if pdate: args += ["--pdate", pdate]
    if url: args += ["--url", url]
    if "--dry" in sys.argv: args.append("--dry")
    out = subprocess.run(args, capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    msg = (out.stdout + out.stderr).strip().splitlines()
    print(oid, "|", msg[-1] if msg else "(no output)")
    nm = re.search(r"OK doc (\d+)", out.stdout)
    if nm: mapping.append((oid, int(nm.group(1)), title))
if mapping:
    with open(os.path.join(DEST, "mapping.tsv"), "a", encoding="utf-8") as f:
        for r in mapping: f.write(f"{r[0]}\t{r[1]}\t{r[2]}\n")
print("loaded", len(mapping))
