"""Load one plain-text document we wrote ourselves (e.g. an own-words summary of a copyright policy document) into
docs.documents / docs.document_chunks, chunked and embedded exactly like rag_ingest_manifest.py (~900 words, 100 overlap,
voyage-3-large). A file already registered (same file name) is skipped.

Usage: python load_text_summary.py <file.txt> --title "..." --label "..." --by <created_by tag>
         [--domain POLICY] [--dtype Summary] [--pdate YYYY-MM-DD] [--url https://...] [--dry] [--replace]   (--replace reloads a copy this same --by tag registered)
"""
import os, sys, time, psycopg2
from rag_ingest_manifest import ENV, TARGET, OVERLAP, VERSION, embed, arg


def chunks_of(text, label):
    words, out, i = text.split(), [], 0
    while True:
        out.append(f"[{label}] " + " ".join(words[i:i + TARGET]))
        if i + TARGET >= len(words): break
        i += TARGET - OVERLAP
    return out


def main():
    path, title, label, by = sys.argv[1], arg("--title"), arg("--label"), arg("--by")
    if not (title and label and by): sys.exit("need --title, --label and --by")
    domain, dtype = arg("--domain", "POLICY"), arg("--dtype", "Summary")
    chunks = chunks_of(open(path, encoding="utf-8").read(), label)
    print(f"{len(chunks)} chunks, words per chunk {[len(c.split()) for c in chunks]}")
    if "--dry" in sys.argv: return
    conn = psycopg2.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"],
                            user=ENV["PGUSER_WRITE"], password=ENV["PGPASSWORD_WRITE"])
    cur = conn.cursor()
    cur.execute("SELECT document_id FROM docs.documents WHERE file_path LIKE %s", ("%" + os.path.basename(path),))
    old = cur.fetchone()
    if old and "--replace" not in sys.argv: sys.exit("SKIP (already registered)")
    if old:
        cur.execute("SELECT created_by FROM docs.documents WHERE document_id = %s", (old[0],))
        if cur.fetchone()[0] != by: sys.exit(f"doc {old[0]} was created by another tag - not replacing")
        cur.execute("DELETE FROM docs.document_chunks WHERE document_id = %s", (old[0],))
        cur.execute("DELETE FROM docs.documents WHERE document_id = %s", (old[0],))
        print(f"replacing doc {old[0]}")
    vecs = embed(chunks)
    cur.execute("""INSERT INTO docs.documents (title, domain, document_type, publication_date, source_url, file_path, page_count, language, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,NULL,'en',%s) RETURNING document_id""",
                (title, domain, dtype, arg("--pdate"), arg("--url"), path, by))
    doc_id = cur.fetchone()[0]
    for idx, (txt, v) in enumerate(zip(chunks, vecs)):
        cur.execute("""INSERT INTO docs.document_chunks (document_id, domain, chunk_index, page_number, section_heading, content,
                       token_count, embedding, embedding_model, embedding_version, section_type, company_id)
                       VALUES (%s,%s,%s,NULL,NULL,%s,%s,%s::vector,'voyage-3-large',%s,'BODY',NULL)""",
                    (doc_id, domain, idx, txt, len(txt.split()), "[" + ",".join(f"{x:.6f}" for x in v) + "]", VERSION))
    conn.commit(); conn.close()
    print(f"OK doc {doc_id}: {len(chunks)} chunks")


if __name__ == "__main__":
    main()
