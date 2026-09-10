# Propose Spanish->English translations for unlinked SEGEMAR deposit_mineralogy.mineral_name_local.
import csv, re, unicodedata, difflib, os

O = os.path.dirname(os.path.abspath(__file__))
def rd(n): return list(csv.DictReader(open(os.path.join(O, n), encoding="utf-8")))

minerals = rd("wip_minerals.csv")
MIN_BY_NORM = {}
def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    s = re.sub(r"[^a-z0-9 +/-]", "", s)
    return re.sub(r"\s+", " ", s)
for m in minerals:
    MIN_BY_NORM[norm(m["mineral_name"])] = (int(m["mineral_id"]), m["mineral_name"])

existing = {norm(t["source_text"]) for t in rd("wip_translations.csv")}
unlinked = rd("wip_unlinked_minerals_ar.csv")

# irregular / non-morphological Spanish mineral names
IRREG = {
    "cuarzo": "quartz", "oro": "gold", "plata": "silver", "cobre": "copper", "hierro": "iron",
    "azufre": "sulfur", "yeso": "gypsum", "sal": "halite", "grafito": "graphite",
    "electrum": "gold", "jaspe": "quartz", "chert": "quartz", "silice": "quartz",
    "calcedonia": "quartz", "opalo": "opal", "agata": "quartz", "onice": "quartz",
    "psilomelano": "romanechite", "wad": None, "limonita": "goethite", "limonitas": "goethite",
    "fahlore": "tetrahedrite", "cobres grises": "tetrahedrite",
    "granate": "garnet", "turmalina": "tourmaline", "mica": "muscovite",
    "arcilla": None, "arcillas": None, "bitumen": None, "carbonatos": None, "sulfuros": None,
    "oxidos": None, "hidroxidos": None, "sulfosales": None, "anfibol": "hornblende",
    "anfiboles": "hornblende", "piroxeno": "augite", "piroxenos": "augite",
    "olivino": "olivine", "feldespato": "orthoclase", "feldespato potasico": "orthoclase",
    "feldespato potasico": "orthoclase", "fedespato potasico": "orthoclase",
    "plagioclasa": "albite", "serpentina": "serpentine", "cloritas": "chlorite",
    "escapolitas": "scapolite", "romanechita": "romanechite", "criptomelano": "cryptomelane",
    "martita": "hematite", "maghemita": "maghemite", "potasio": None, "litio": None,
    "antimonio nativo": "antimony", "antimonio": "antimony", "bismuto nativo": "bismuth",
    "hubnerita": "hubnerite", "huebnerita": "hubnerite", "minerales de bi": None,
    "minerales de bismuto": None, "sanmartinita": "sanmartinite",
    "calcosina": "chalcocite", "crisocola": "chrysocolla", "crisotilo": "chrysotile",
    "cromoespinelo": "chromite", "baritina": "baryte", "barita": "baryte",
    "acantita": "acanthite", "grosularia": "grossular", "diatomita": "opal",
    "bitumen": None, "alofano": "allophane", "broncita": "enstatite", "ortosa": "orthoclase",
    "antimonita": "stibnite", "estibina": "stibnite", "argentum": "silver", "argentita": "argentite",
    "au": "gold", "ca": None, "cobres grises": "tetrahedrite", "garnierita": "garnierite",
    "wad": None, "onofrita": "onofrite", "zoicita": "zoisite", "hallosita": "halloysite",
    "vesubianita": "vesuvianite", "meta-autunita": "metaautunite", "betafita": "betafite",
    "britholita": "britholite-ce", "eritrina": "erythrite",
    "malaquita": "malachite", "molibdenita": "molybdenite", "pirolusita": "pyrolusite",
    "piromorfita": "pyromorphite", "estefanita": "stephanite", "alabandina": "alabandite",
    "alabandino": "alabandite", "covellina": "covellite", "serpetina": "serpentine",
    "manganocalcita": "calcite", "piirta": "pyrite", "caolinita": "kaolinite",
    "arsenopirita": "arsenopyrite", "piromorfita": "pyromorphite", "bismuto": "bismuth",
    "bismutina": "bismuthinite", "argentitta": "argentite", "argirodita": "argyrodite",
    "axinita": "axinite-fe", "bixbyita": "bixbyite", "calcofanita": "chalcophanite",
    "bindheimita": "bindheimite", "calcopirtia": "chalcopyrite", "calcoestibita": "chalcostibite",
}
# regular morphology: Spanish -> English mineral spelling swaps
PREFIX = [("esf", "sph"), ("cr", "chr"), ("calco", "chalco"), ("f", "ph"),
          ("qu", "qu"), ("hidr", "hydr"), ("j", "y"), ("cl", "cl")]
def morph(n):
    bases = {n}
    # i<->y anywhere (pirita->pyrite, molibdenita->molybdenite)
    bases.add(n.replace("i", "y"))
    bases.add(re.sub(r"([bcdfglmnprstv])i([bcdfglmnprstv])", r"\1y\2", n))
    for a, b in PREFIX:
        if n.startswith(a):
            bases.add(b + n[len(a):])
    for pre in list(bases):
        bases.add(pre.replace("t", "th", 1))
        bases.add(pre.replace("c", "ch", 1))
        bases.add(pre.replace("qu", "k"))
        bases.add(pre.replace("s", "ss"))
    out = set()
    for b in bases:
        out.add(b)
        for pat, rep in [(r"itas?$", "ite"), (r"inas?$", "ine"), (r"osa$", "ase"),
                         (r"asa$", "ase"), (r"ita$", "yte"), (r"o$", "e"), (r"a$", "e"),
                         (r"io$", "ium"), (r"argir", "argyr"), (r"argyr", "argyr")]:
            if re.search(pat, b):
                out.add(re.sub(pat, rep, b))
    return out

DESCR = re.compile(r"oxid|hidroxid|carbonat|sulfat|sulfur|sulfosal|silicat|arcill|"
                   r"minerales|especular|nativ|de (cu|fe|mn|bi|cobre|hierro|plata|cobalto|u|uranio|manganeso)")

out = []
for r in unlinked:
    src = r["nm"]; n = norm(src); cnt = int(r["n"])
    if n in existing:
        continue
    # pairs / series -> take first member
    is_pair = bool(re.search(r"\w-\w|\w \+ \w|/", src)) and "-" in src.rstrip("-")
    first = re.split(r"[-/+]| y ", src)[0].strip() if is_pair else src
    fn = norm(first)

    mid = mname = None; method = ""; cat = "species"
    if fn in IRREG:
        tgt = IRREG[fn]
        if tgt is None:
            cat = "descriptor"; method = "irregular(non-mineral)"
        elif norm(tgt) in MIN_BY_NORM:
            mid, mname = MIN_BY_NORM[norm(tgt)]; method = "irregular"
    if mid is None and cat == "species":
        for c in morph(fn):
            if norm(c) in MIN_BY_NORM:
                mid, mname = MIN_BY_NORM[norm(c)]; method = "morphology"; break
    if mid is None and cat == "species":
        cand = difflib.get_close_matches(fn, list(MIN_BY_NORM), n=1, cutoff=0.86)
        if cand:
            mid, mname = MIN_BY_NORM[cand[0]]; method = f"fuzzy({difflib.SequenceMatcher(None,fn,cand[0]).ratio():.2f})"
    if mid is None:
        if DESCR.search(n):
            cat = "descriptor" if not method else cat
            method = method or "descriptor/compound"
        elif is_pair:
            cat = "series"; method = "unresolved pair"
        else:
            cat = "unknown"; method = method or "no match"

    conf = {"irregular": "HIGH", "morphology": "HIGH"}.get(method, "")
    if method.startswith("fuzzy"):
        conf = "MED" if float(method[6:10]) >= 0.90 else "LOW"
    if cat in ("descriptor",): conf = "n/a"
    out.append({
        "source_text": src, "n_rows": cnt,
        "proposed_english": mname or "", "mineral_id": mid or "",
        "category": cat, "method": method, "confidence": conf,
    })

out.sort(key=lambda x: (-x["n_rows"], x["source_text"]))
with open(os.path.join(O, "mineral_translation_candidates_ar.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader(); w.writerows(out)

import collections
by = collections.Counter()
rows_by = collections.Counter()
for o in out:
    k = o["confidence"] if o["mineral_id"] else ("descriptor" if o["category"] == "descriptor" else "no match")
    by[k] += 1; rows_by[k] += o["n_rows"]
print(f"{len(out)} distinct names not yet in mineral_name_translations")
print(f"{'bucket':12} {'names':>7} {'rows':>7}")
for k in ("HIGH", "MED", "LOW", "descriptor", "no match"):
    print(f"{k:12} {by[k]:>7} {rows_by[k]:>7}")
print("\nsample HIGH-confidence:")
for o in out:
    if o["confidence"] == "HIGH":
        print(f"  {o['source_text']:28} -> {o['proposed_english']:22} ({o['method']}, {o['n_rows']} rows)")
