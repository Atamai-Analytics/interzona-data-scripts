"""Cleaned page texts (rag_ocr cache format) for the two AI-assisted regional syntheses dropped in RAG/Ingest on 10 Nov 2026:
EuropeanMineralDeposits.pdf and ChinaMineralDeposits.pdf, each with its GeoScienceWorld reference list appended as the last pages.
Same treatment as doc 444 (rag_build_lithium_deep_dive.py): an ABOUT THIS DOCUMENT note on page 1 and inline [Atamai note: ...] flags.

Usage: python rag_build_region_deep_dives.py <cache folder>   -> writes ocr_europe_deposits_20261111.json and ocr_china_deposits_20261111.json
"""
import json, os, re, sys, unicodedata, pymupdf

D = "D:/CriticalMineralsDB/Documents/RAG/Ingest/"
OUT = sys.argv[1]

DOCS = {
    "europe_deposits_20261111": {
        "main": "EuropeanMineralDeposits.pdf", "refs": "EuropeanMineralDepositReferences.pdf",
        "note": (
            "ABOUT THIS DOCUMENT (added by Atamai Analytics when loading, 11 Nov 2026): internal synthesis compiled with an AI research "
            "assistant from a small set of GeoScienceWorld papers (Boni 2003 on European nonsulfide zinc; Tagliacollo et al. 2026 on VMS in "
            "Modena; Jorgensen et al. 2023 on MIN4EU; Gonzalez et al. 2023 on GeoERA-MINDeSEA seabed deposits; Herrington et al. 2005 on the "
            "Urals; Dill et al. 2008; Pietrzela 2023 on the Polish Northern Copper Belt; reference list at the end). Not a primary source and "
            "NOT a complete inventory: it covers only what those papers discuss, so it omits most of Europe's major deposits and districts - "
            "for example Poland's KGHM Lubin-Glogow copper district, the Iberian Pyrite Belt (Neves-Corvo, Riotinto, Aguas Tenidas), and the "
            "Nordic deposits (Kiruna, Aitik, Kevitsa, Garpenberg). It gives no coordinates (it says so) and few grades. Citation markers were "
            "lost in export, so claims cannot be traced to a single paper. For European deposits prefer the database (CRMA strategic projects, "
            "national survey occurrences) and the primary papers. Flags: Bor (Serbia) is a major porphyry/high-sulfidation copper-gold district, "
            "not only a gold deposit; Vares (Bosnia) is today known for the Rupice silver-zinc-lead-barite deposit, not just iron.\n\n"),
        "inline": [
            ("44 t Au total; 0.4 g/t Au",
             "44 t Au total; 0.4 g/t Au [Atamai note: incomplete - Bor is one of Europe's largest copper districts (porphyry and high-sulfidation Cu-Au); these figures describe gold only.]"),
            ("Type: Iron deposit",
             "Type: Iron deposit [Atamai note: historically iron; today Vares is known for the Rupice silver-zinc-lead-barite deposit.]"),
        ],
    },
    "china_deposits_20261111": {
        "main": "ChinaMineralDeposits.pdf", "refs": "ChinaMineralDepositsReferences.pdf",
        "note": (
            "ABOUT THIS DOCUMENT (added by Atamai Analytics when loading, 11 Nov 2026): internal synthesis compiled with an AI research "
            "assistant from GeoScienceWorld literature, mainly Chang & Goldfarb (2019, SEG Special Publication 22, Mineral Deposits of China) "
            "plus papers on the Gangdese, Yulong and Sanjiang belts, Bayan Obo, Longmen and others (reference list at the end). Not a primary "
            "source: citation markers were lost in export, so claims cannot be traced to a single paper - cite the underlying papers. "
            "Coordinates and grades in the tables are as reported in the literature and were NOT checked; resource figures are from different "
            "dates and standards (e.g. Jiama appears with two different figures). Production rankings are for 2018. Taiwan is included because "
            "the SEG volume's scope includes it. Known problems: (1) Xiongcun (Xietongmen) is in the Gangdese belt of southern Tibet, NOT the "
            "Middle-Lower Yangtze belt as one sentence says; (2) the deposit-count column of the deposit-type table was lost in export, only the "
            "type names remain; (3) the Bangpu copper and molybdenum figures have unclear units; (4) '56 million tons proven copper resources' mixes resources "
            "and proven reserves - read it as a contained-copper resource figure; (5) 'massive pyrite with 7-16% Fe' is implausible for massive "
            "pyrite (about 46% Fe) - check the source before use.\n\n"),
        "inline": [
            ("Neo-Tethys subduction. Additionally",
             "Neo-Tethys subduction. [Atamai note: ERROR in this synthesis - Xiongcun (Xietongmen) is in the Gangdese belt, southern Tibet, not the Middle-Lower Yangtze belt.] Additionally"),
            ("The breakdown by type is as follows",
             "The breakdown by type is as follows [Atamai note: the number of deposits per type was lost in export; only the type names remain]"),
            ("43-101 compliant)",
             "43-101 compliant) [Atamai note: differs from the 1,055 Mt at 0.44% Cu in the table above - different resource dates; check the latest China Gold International Resources report.]"),
            ("Cu: 321; Mo: 570",
             "Cu: 321; Mo: 570 [Atamai note: units unclear - probably separate Cu and Mo ore tonnages in Mt]"),
            ("exploration base in China.",
             "exploration base in China. [Atamai note: '56 million tons' is best read as contained copper in resources, not proven reserves.]"),
            ("7–16% Fe content",
             "7–16% Fe content [Atamai note: implausible for massive pyrite (about 46% Fe) - possibly S or a different measure; check the source]"),
            ("Sources: *",
             "Sources: (citation markers were lost in export - see the REFERENCES section below)"),
        ],
    },
}


def clean(t):
    t = t.replace("\u01af", "ff")
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"[\u3000-\u9fff\uac00-\ud7af\ue000-\uf8ff\U0001F000-\U0001FFFF\u2600-\u27bf\ufe0f]", "", t)
    t = t.replace("\u2039", "").replace("\u203a", "")
    t = re.sub(r"[ \t]+\.(?=\s|$)", ".", t)
    t = re.sub(r"[ \t]+,", ",", t)
    t = re.sub(r"[ \t]+:(?=\s|$)", ":", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


for name, spec in DOCS.items():
    pages = {}
    d = pymupdf.open(D + spec["main"])
    for i, p in enumerate(d):
        pages[str(i + 1)] = clean(p.get_text())
    pages["1"] = spec["note"] + pages["1"]
    for old, new in spec["inline"]:
        hits = [k for k, v in pages.items() if old in v]
        if len(hits) != 1 or pages[hits[0]].count(old) != 1:
            sys.exit(f"{name}: inline target not found exactly once: {old!r} -> {hits}")
        pages[hits[0]] = pages[hits[0]].replace(old, new)
    r = pymupdf.open(D + spec["refs"])
    for i, p in enumerate(r):
        t = re.sub(r"\n?View full article\n?", "\n", clean(p.get_text()))
        pages[str(len(d) + 1 + i)] = ("REFERENCES (GeoScienceWorld article list behind the synthesis)\n" if i == 0 else "") + t
    json.dump(pages, open(os.path.join(OUT, f"ocr_{name}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    bad = sorted({c for v in pages.values() for c in v if ord(c) > 0x2FFF})
    print(name, "pages", len(pages), "main", len(d), "words", sum(len(v.split()) for v in pages.values()), "remaining high chars:", bad)
