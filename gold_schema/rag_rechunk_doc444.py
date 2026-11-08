"""Re-chunk + re-embed doc 444 in place from the updated page cache (same document_id)."""
import sys, json, time
sys.path.insert(0, r"C:\Users\dean\claude_lithosurfer\lithosurfer-work\gold_schema")
import psycopg2, rag_ingest_manifest as R

m = json.load(open(r"D:/CriticalMineralsDB/Documents/RAG/Ingest/rag_manifest_20261108.json", encoding="utf-8"))[0]
chunks = R.build_chunks(None, m)
vecs = []
for i in range(0, len(chunks), 16):
    vecs += R.embed([c[2] for c in chunks[i:i + 16]]); time.sleep(0.2)
E = R.ENV
conn = psycopg2.connect(host=E["PGHOST"], port=E["PGPORT"], dbname=E["PGDATABASE"], user=E["PGUSER_WRITE"], password=E["PGPASSWORD_WRITE"])
cur = conn.cursor()
cur.execute("SELECT count(*) FROM docs.document_chunks WHERE document_id = 444")
old = cur.fetchone()[0]
cur.execute("DELETE FROM docs.document_chunks WHERE document_id = 444")
for idx, ((pg, typ, txt), v) in enumerate(zip(chunks, vecs)):
    cur.execute("""INSERT INTO docs.document_chunks (document_id, domain, chunk_index, page_number, section_heading, content,
                   token_count, embedding, embedding_model, embedding_version, section_type, company_id)
                   VALUES (444,%s,%s,%s,NULL,%s,%s,%s::vector,'voyage-3-large',%s,%s,NULL)""",
                (m["domain"], idx, pg, txt, len(txt.split()), "[" + ",".join(f"{x:.6f}" for x in v) + "]", R.VERSION, typ))
conn.commit()
print(f"doc 444: replaced {old} chunks with {len(chunks)}; notes in chunks:",
      [i for i, c in enumerate(chunks) if "Atamai note" in c[2] or "ABOUT THIS DOCUMENT" in c[2]])
