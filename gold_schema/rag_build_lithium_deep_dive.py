"""Cleaned page texts for LithiumDeepDive.pdf (+ references appended as pages 11+) in rag_ocr cache format."""
import json, re, sys, unicodedata, pymupdf

D = "D:/CriticalMineralsDB/Documents/RAG/Ingest/"
OUT = sys.argv[1]

NOTE = (
    "ABOUT THIS DOCUMENT (added by Atamai Analytics when loading, 8 Nov 2026): internal synthesis compiled with an AI "
    "research assistant from GeoScienceWorld literature (Economic Geology special issues on lithium 2023-2025, "
    "Goodenough et al. 2025 on African pegmatites, Wells et al. 2025 on Western Australian pegmatite ores, Mykhailov "
    "et al. 2023 on Ukraine, and others; reference list at the end). Not a primary source: the citation markers were "
    "lost in export, so individual claims cannot be traced to a specific paper; cite the underlying papers, and prefer "
    "company resource statements in the library for current resources. Known problems: (1) the Salar de Uyuni line "
    "repeats the Zhabuye figure (1.53 Mt Li) - it is NOT an estimate for Uyuni; (2) the sentence that granites and "
    "pegmatites gave ~50% of world lithium supply in 2015 is a general statement, not about the Central Vietnam granite; "
    "(3) the Salton Sea '60-70 kt lithium carbonate' does not state a period; (4) Tonopah Flats and TLC tonnages are "
    "given as Mt Li and were not checked against the company reports; (5) the grade-tonnage summary table was cut off "
    "at the right margin in the source export.\n\n"
)


def clean(t):
    t = t.replace("\u01af", "ff")                         # 'cutoƯ', 'tuƯs' = ff ligature mis-mapped
    t = unicodedata.normalize("NFKC", t)                   # ﬁ -> fi, Li₂O -> Li2O
    t = re.sub(r"[\u3000-\u9fff\uac00-\ud7af\ue000-\uf8ff\U0001F000-\U0001FFFF]", "", t)  # garbled emoji headings
    t = t.replace("\u2039", "").replace("\u203a", "")
    t = re.sub(r"[ \t]+\.(?=\s|$)", ".", t)                  # dangling ' .' left by stripped citations
    t = re.sub(r"[ \t]+,", ",", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


pages = {}
d = pymupdf.open(D + "LithiumDeepDive.pdf")
for i, p in enumerate(d):
    pages[str(i + 1)] = clean(p.get_text())
pages["1"] = NOTE + pages["1"]
INLINE = [
    ("Academic Li estimate: 1.53 Mt (Zhabuye equivalent).",
     "Academic Li estimate: 1.53 Mt (Zhabuye equivalent). [Atamai note: ERROR in this synthesis - 1.53 Mt is the Zhabuye figure, not an estimate for Uyuni; do not use it for Uyuni.]"),
    ("~50% of world Li supply in 2015.",
     "~50% of world Li supply in 2015. [Atamai note: this share is a general statement about granites and pegmatites, not about the Central Vietnam granite.]"),
    ("power station brines.",
     "power station brines. [Atamai note: period not stated in the synthesis (likely per year); check before using.]"),
]
for old, new in INLINE:
    hits = [k for k, v in pages.items() if old in v]
    if len(hits) != 1:
        sys.exit(f"inline target not found exactly once: {old!r} -> {hits}")
    pages[hits[0]] = pages[hits[0]].replace(old, new)
r = pymupdf.open(D + "LithiumDeepDiveReferences.pdf")
for i, p in enumerate(r):
    t = clean(p.get_text())
    t = re.sub(r"\n?View full article\n?", "\n", t)
    pages[str(len(d) + 1 + i)] = ("REFERENCES (GeoScienceWorld article list behind the synthesis)\n" if i == 0 else "") + t
json.dump(pages, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print({k: len(v.split()) for k, v in pages.items()})
bad = sorted({c for v in pages.values() for c in v if ord(c) > 0x2FFF})
print("remaining high chars:", bad)
