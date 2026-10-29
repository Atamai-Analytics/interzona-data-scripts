"""
RAG document ingestion pipeline for interzona_cm (gold).

Extracts text from PDF/docx, chunks it (~1800 chars/chunk, matching bronze's
own proven chunk-size distribution), tags section_type via simple heading
heuristics, embeds via Voyage voyage-3-large, and inserts into
docs.documents + docs.document_chunks.

Credentials are read from lithosurfer-work/.env and never printed.

Usage:
    python rag_ingest.py --dry-run FILE [FILE ...]   # extract+chunk+tag only, no API/DB
    python rag_ingest.py --run FILE [FILE ...]        # full pipeline
"""
import sys
import os
import re
import json
import argparse
import unicodedata

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")

# filename (basename) -> domain
DOMAIN_MAP = {
    "AncientRootsOfTungstenInWesternNthAmerica.pdf": "RESEARCH",
    "AustralianMineralsExplorationReview.pdf": "TECHNICAL_REPORT",
    "HiPurityMineralSystemsAustralia.pdf": "TECHNICAL_REPORT",
    "MappingTheSupplyChainOfLiIonBatteryMetals.pdf": "SUPPLY_CHAIN",
    "MineralRequirementsOfDigitalTechnologies.pdf": "TECHNOLOGY",
    "NioCorp_Form_10Q_033126_AsFiled-1.pdf": "ANNUAL_REPORT",
}

CHUNK_TARGET_CHARS = 1800
CHUNK_MAX_CHARS = 3000  # hard split ceiling for a single page's text

VOYAGE_MODEL = "voyage-3-large"
CREATED_BY = "claude_rag_ingest_20260926"


def load_env():
    env = {}
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def extract_pdf_pages(path):
    import fitz
    doc = fitz.open(path)
    pages = []
    for i in range(doc.page_count):
        text = doc[i].get_text("text")
        pages.append((i + 1, clean_text(text)))
    doc.close()
    return pages


def extract_docx_text(path):
    from docx import Document
    d = Document(path)
    paras = [p.text for p in d.paragraphs]
    text = "\n".join(paras)
    return [(None, clean_text(text))]


def clean_text(text):
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("", "-").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


HEADING_PATTERNS = [
    (re.compile(r"^\s*(table of contents|contents)\b", re.I), "TABLE_OF_CONTENTS"),
    (re.compile(r"^\s*appendix\b", re.I), "APPENDIX"),
    (re.compile(r"^\s*glossary\b", re.I), "GLOSSARY"),
    (re.compile(r"^\s*(references|bibliography|works cited)\b", re.I), "REFERENCES"),
]

DISCLAIMER_RE = re.compile(
    r"forward-looking statements|no representation or warranty|this (presentation|document) contains",
    re.I,
)


def tag_section_type(chunk_text, chunk_index):
    head = chunk_text[:120]
    for pat, label in HEADING_PATTERNS:
        if pat.match(head):
            return label
    first_300 = chunk_text[:300]
    if DISCLAIMER_RE.search(first_300):
        return "DISCLAIMER"
    return "BODY"


def split_long_text(text, target=CHUNK_TARGET_CHARS, hard_max=CHUNK_MAX_CHARS):
    """Split text on paragraph boundaries into ~target-char pieces."""
    if len(text) <= hard_max:
        return [text]
    paras = re.split(r"\n\s*\n", text)
    pieces = []
    cur = ""
    for p in paras:
        if not p.strip():
            continue
        if cur and len(cur) + len(p) + 2 > target:
            pieces.append(cur.strip())
            cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
        while len(cur) > hard_max:
            pieces.append(cur[:hard_max].strip())
            cur = cur[hard_max:]
    if cur.strip():
        pieces.append(cur.strip())
    return pieces if pieces else [text[:hard_max]]


def build_chunks(pages):
    """pages: list of (page_number_or_None, text). Returns list of dicts."""
    chunks = []
    idx = 0
    for page_number, text in pages:
        if not text or len(text) < 20:
            continue
        for piece in split_long_text(text):
            if len(piece) < 20:
                continue
            chunks.append({
                "chunk_index": idx,
                "page_number": page_number,
                "content": piece,
                "char_count": len(piece),
                "approx_tokens": max(1, round(len(piece) / 4.1)),
            })
            idx += 1
    for c in chunks:
        c["section_type"] = tag_section_type(c["content"], c["chunk_index"])
    return chunks


def process_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        pages = extract_pdf_pages(path)
    elif ext == ".docx":
        pages = extract_docx_text(path)
    else:
        raise ValueError(f"unsupported extension: {ext}")
    return build_chunks(pages)


def dry_run(files):
    for path in files:
        name = os.path.basename(path)
        chunks = process_file(path)
        total_chars = sum(c["char_count"] for c in chunks)
        sections = {}
        for c in chunks:
            sections[c["section_type"]] = sections.get(c["section_type"], 0) + 1
        print(f"\n=== {name} ===")
        print(f"  chunks: {len(chunks)}  total_chars: {total_chars}  avg_chars: {total_chars // max(1,len(chunks))}")
        print(f"  section_type breakdown: {sections}")
        preview = chunks[0]['content'][:150].encode("ascii", "replace").decode("ascii")
        print(f"  first chunk preview: {preview!r}")
        print(f"  domain: {DOMAIN_MAP.get(name, 'UNMAPPED')}")


def embed_batch(texts, api_key, batch_size=20):
    import requests
    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = requests.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"input": batch, "model": VOYAGE_MODEL, "input_type": "document"},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in sorted(data["data"], key=lambda x: x["index"]):
            embeddings.append(item["embedding"])
    return embeddings


def get_conn(env):
    import psycopg2
    return psycopg2.connect(
        host=env["LITHODAT_DB_HOST"],
        port=env["LITHODAT_DB_PORT"],
        dbname="interzona_cm",
        user=env["LITHODAT_DB_USER"],
        password=env["LITHODAT_DB_PASSWORD"],
    )


def real_run(files, env):
    api_key = env["VOYAGE_API_KEY"]
    conn = get_conn(env)
    cur = conn.cursor()
    total_chunks_inserted = 0
    for path in files:
        name = os.path.basename(path)
        domain = DOMAIN_MAP.get(name)
        if not domain:
            print(f"SKIP (no domain mapping): {name}")
            continue
        chunks = process_file(path)
        if not chunks:
            print(f"SKIP (no extractable text): {name}")
            continue

        title = os.path.splitext(name)[0]
        cur.execute(
            """INSERT INTO docs.documents (title, domain, document_type, page_count, is_active, created_by, created_date)
               VALUES (%s, %s, %s, %s, true, %s, now())
               RETURNING document_id""",
            (title, domain, "report", max((c["page_number"] or 0) for c in chunks) or None, CREATED_BY),
        )
        document_id = cur.fetchone()[0]

        texts = [c["content"] for c in chunks]
        embeddings = embed_batch(texts, api_key)
        assert len(embeddings) == len(chunks)

        for c, emb in zip(chunks, embeddings):
            vec_literal = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
            cur.execute(
                """INSERT INTO docs.document_chunks
                   (document_id, domain, chunk_index, page_number, content, token_count,
                    embedding, embedding_model, embedding_version, section_type, created_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, now())""",
                (document_id, domain, c["chunk_index"], c["page_number"], c["content"],
                 c["approx_tokens"], vec_literal, VOYAGE_MODEL, "2026-09-26", c["section_type"]),
            )
        conn.commit()
        total_chunks_inserted += len(chunks)
        print(f"OK: {name} -> document_id={document_id}, domain={domain}, chunks={len(chunks)}")

    cur.close()
    conn.close()
    print(f"\nTotal chunks inserted: {total_chunks_inserted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    if args.dry_run:
        dry_run(args.files)
    else:
        env = load_env()
        real_run(args.files, env)
