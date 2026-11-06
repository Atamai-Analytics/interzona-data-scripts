"""Canada phase 3: turn each downloaded technical report / release into summary.txt (the summary unit that gets embedded).

PDF reports: Item 1 (Summary / Executive Summary) up to Item 2 (Introduction), plus Item 25-26 (Interpretation and conclusions,
Recommendations) when present; '[page N]' markers are kept. HTML releases: main text of the page. *.txt files (browser-saved SEC / ASX
sections) are used as they are. Output: <project folder>/summary.txt and a line per project in extract_log.tsv.
Usage: python -E -P canada_report_extract.py D:/CriticalMineralsDB/Documents/RAG/Ingest/report_summaries_canada_20261105
"""
import os, re, sys, html
import fitz   # pymupdf

ROOT = sys.argv[1]
MAXC = 120_000


def pdf_sections(path):
    doc = fitz.open(path)
    pages = [doc[i].get_text() for i in range(doc.page_count)]
    head = re.compile(r"^\s*(1(\.0)?\.?\s+(EXECUTIVE\s+)?SUMMARY|SECTION\s+1\b|1\s*[-–]\s*SUMMARY)\b", re.I | re.M)
    intro = re.compile(r"^\s*(2(\.0)?\.?\s+INTRODUCTION|SECTION\s+2\b)", re.I | re.M)
    interp = re.compile(r"^\s*25(\.0)?\.?\s+(INTERPRETATION|CONCLUSIONS)", re.I | re.M)
    refs = re.compile(r"^\s*27(\.0)?\.?\s+REFERENCES", re.I | re.M)

    def first_page(rx, start=0, skip_toc=True):
        for i in range(start, len(pages)):
            if rx.search(pages[i]) and not (skip_toc and re.search(r"TABLE OF CONTENTS|\.{6,}", pages[i], re.I)):
                return i
        return None
    s0 = first_page(head, 1)
    s1 = first_page(intro, (s0 or 0) + 1) if s0 is not None else None
    # Item 25 sits near the end: take the LAST page whose heading matches (an early match is a cross-reference)
    i0 = next((i for i in range(len(pages) - 1, (s1 or 0), -1) if interp.search(pages[i]) and not re.search(r"TABLE OF CONTENTS|\.{6,}", pages[i], re.I)), None)
    r1 = first_page(refs, (i0 or 0) + 1) if i0 is not None else None
    out = []
    if s0 is not None:
        for i in range(s0, (s1 if s1 else min(s0 + 40, len(pages)))):
            out.append(f"[page {i + 1}]\n{pages[i]}")
    if i0 is not None:
        out.append("\n[...]\n")
        for i in range(i0, (r1 if r1 else min(i0 + 15, len(pages)))):
            out.append(f"[page {i + 1}]\n{pages[i]}")
    return "\n".join(out), dict(pages=len(pages), summary=(s0, s1), interp=(i0, r1))


def html_text(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    raw = re.sub(r"(?is)<(script|style|noscript|nav|header|footer|svg)\b.*?</\1>", " ", raw)
    m = re.search(r"(?is)<article\b.*?</article>", raw) or re.search(r"(?is)<main\b.*?</main>", raw)
    body = m.group(0) if m else raw
    body = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>|</li>|</div>", "\n", body)
    body = re.sub(r"(?i)</t[dh]>", " | ", body)
    t = html.unescape(re.sub(r"<[^>]+>", " ", body))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


log = []
for d in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, d)
    if not os.path.isdir(p): continue
    parts, info = [], {}
    for f in sorted(os.listdir(p)):
        fp = os.path.join(p, f)
        if f == "summary.txt": continue
        if f.endswith(".pdf"):
            if os.path.getsize(fp) > 2_000_000:
                t, info = pdf_sections(fp)
            else:   # small PDF = a company release
                doc = fitz.open(fp); t = "\n".join(f"[page {i + 1}]\n{doc[i].get_text()}" for i in range(doc.page_count))
        elif f.endswith(".html"):
            t = html_text(fp)
        elif f.endswith(".txt"):
            t = open(fp, encoding="utf-8", errors="ignore").read()
        else:
            continue
        parts.append(f"===== {f} =====\n{t}")
    s = "\n\n".join(parts)[:MAXC]
    open(os.path.join(p, "summary.txt"), "w", encoding="utf-8").write(s)
    log.append(f"{d}\t{len(s)}\t{info}")
    print(d, len(s), info, flush=True)
open(os.path.join(ROOT, "extract_log.tsv"), "w", encoding="utf-8").write("\n".join(log))
