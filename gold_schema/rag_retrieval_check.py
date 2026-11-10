"""Quick retrieval check for the document library: embed each question (voyage-3-large, input_type query) and print the top-k
nearest chunks across docs.document_chunks, marking the documents we expect to see.

Usage: python rag_retrieval_check.py <checks.json> [--k 5]
checks.json: [{"q": "question", "expect": [445, 447]}, ...]   -> prints HIT if any expected doc is in the top k.
"""
import sys, json, requests, psycopg2
from rag_ingest_manifest import ENV, arg

K = int(arg("--k", "5"))
checks = json.load(open(sys.argv[1], encoding="utf-8"))
r = requests.post("https://api.voyageai.com/v1/embeddings", headers={"Authorization": f"Bearer {ENV['VOYAGE_API_KEY']}"},
                  json={"input": [c["q"] for c in checks], "model": "voyage-3-large", "input_type": "query"}, timeout=120)
r.raise_for_status()
vecs = [d["embedding"] for d in r.json()["data"]]
conn = psycopg2.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"], user=ENV["PGUSER_WRITE"], password=ENV["PGPASSWORD_WRITE"])
cur = conn.cursor()
hits = 0
for c, v in zip(checks, vecs):
    cur.execute("""SELECT ch.document_id, ch.chunk_index, round((1 - (ch.embedding <=> %s::vector))::numeric, 3), left(d.title, 70)
                   FROM docs.document_chunks ch JOIN docs.documents d USING (document_id) WHERE d.is_active
                   ORDER BY ch.embedding <=> %s::vector LIMIT %s""", ("[" + ",".join(map(str, v)) + "]",) * 2 + (K,))
    rows = cur.fetchall()
    ok = any(r[0] in c["expect"] for r in rows)
    hits += ok
    print(("HIT " if ok else "MISS") + " | " + c["q"])
    for d, ci, s, t in rows:
        print(f"     {'*' if d in c['expect'] else ' '} doc {d} #{ci} {s} {t}")
print(f"\n{hits}/{len(checks)} questions retrieved an expected document in the top {K}")
