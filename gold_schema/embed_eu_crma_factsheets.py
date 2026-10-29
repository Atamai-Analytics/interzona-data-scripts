"""Chunk + embed the 59 EU CRMA strategic-project factsheets (docs.documents created by load_eu_crma.py) into docs.document_chunks.

Each factsheet is one page (~1,500 chars of OCR text), so it becomes ONE chunk: a structured header (project, type, materials,
promoter, country, approval/decision, start of production, UNFC, website) followed by the description and the EU-benefit text.
Chunks carry project_id / company_id / occurrence_id / commodity_id / jurisdiction_id so the app can filter on them.
Embeddings: Voyage voyage-3-large via rag_ingest.embed_batch (same model as the rest of docs.document_chunks).
Idempotent: documents that already have chunks are skipped.
Usage: python embed_eu_crma_factsheets.py --dry | --run
"""
import sys
from rag_ingest import load_env, get_conn, embed_batch, VOYAGE_MODEL

TAG = "migration_eu_crma_20261029"
EMBED_VERSION = "2026-10-29"
DRY = "--dry" in sys.argv
if not DRY and "--run" not in sys.argv:
    sys.exit(__doc__)

env = load_env()
g = get_conn(env)
g.autocommit = False
c = g.cursor()
c.execute("""
SELECT d.document_id, d.domain, p.project_id, p.company_id, p.occurrence_id, p.primary_commodity_id, p.jurisdiction_id,
       p.name, p.description, z.value_chain_stage, z.materials_as_published, z.promoter_as_published, z.countries_as_published,
       z.scope, z.approval_date, z.decision_ref, z.est_start_production, z.unfc_classification, z.website, z.eu_benefit
FROM docs.documents d
JOIN core.projects p ON p.project_id = d.project_id
JOIN core.project_designations z ON z.project_id = p.project_id
WHERE d.created_by = %s AND NOT EXISTS (SELECT 1 FROM docs.document_chunks k WHERE k.document_id = d.document_id)
ORDER BY d.document_id""", (TAG,))
rows = c.fetchall()


def chunk_text(r):
    (_, _, _, _, _, _, _, name, desc, stage, mats, promoter, ctry, scope, appr, dec, start, unfc, web, benefit) = r
    head = [f"EU Critical Raw Materials Act (CRMA) strategic project factsheet: {name}",
            f"Project type: {stage}", f"Strategic raw materials: {mats}", f"Project promoter: {promoter}",
            f"Project country: {ctry}",
            f"Selected as a strategic project ({'EU' if scope == 'EU' else 'outside the EU'} list), approved {appr:%d %B %Y}, Commission Decision {dec}"]
    if start:
        head.append(f"Estimated starting date of production: {start}")
    if unfc:
        head.append(f"UNFC classification: {unfc}")
    if web:
        head.append(f"Website: {web}")
    body = "\n".join(head)
    if desc:
        body += "\n\nDescription of project\n" + desc
    if benefit:
        body += "\n\nBenefit for the EU\n" + benefit
    return body


texts = [chunk_text(r) for r in rows]
print(f"factsheet documents without chunks: {len(rows)}")
if rows:
    lens = sorted(len(t) for t in texts)
    print(f"chunk chars: min {lens[0]}, median {lens[len(lens) // 2]}, max {lens[-1]}")
    print("--- sample chunk ---\n" + texts[0][:1200].encode("ascii", "replace").decode("ascii"))
if DRY or not rows:
    g.rollback(); print("DRY - nothing embedded or written" if DRY else "nothing to do"); sys.exit()

embeddings = embed_batch(texts, env["VOYAGE_API_KEY"])
assert len(embeddings) == len(rows)
for r, t, emb in zip(rows, texts, embeddings):
    c.execute("""INSERT INTO docs.document_chunks
                 (document_id, domain, chunk_index, page_number, section_heading, content, token_count, embedding,
                  embedding_model, embedding_version, section_type, company_id, project_id, occurrence_id, commodity_id,
                  jurisdiction_id, created_date)
                 VALUES (%s,%s,0,1,%s,%s,%s,%s::vector,%s,%s,'BODY',%s,%s,%s,%s,%s,now())""",
              (r[0], r[1], "Strategic project factsheet", t, max(1, round(len(t) / 4.1)),
               "[" + ",".join(f"{x:.8f}" for x in emb) + "]", VOYAGE_MODEL, EMBED_VERSION,
               r[3], r[2], r[4], r[5], r[6]))
c.execute("""SELECT count(*), count(DISTINCT k.document_id), count(k.embedding), count(k.project_id)
             FROM docs.document_chunks k JOIN docs.documents d ON d.document_id = k.document_id WHERE d.created_by = %s""", (TAG,))
n, ndoc, nemb, nproj = c.fetchone()
print(f"chunks {n}, documents {ndoc}, with embedding {nemb}, with project_id {nproj}")
if n == ndoc == nemb == nproj == len(rows):
    g.commit(); print("COMMITTED")
else:
    g.rollback(); print("CHECK FAILED - rolled back")
