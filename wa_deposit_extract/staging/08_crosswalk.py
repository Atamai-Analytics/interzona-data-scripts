"""WA deposit extract - Step 4b: build the WA-token -> commodities crosswalk.

Inputs  (staging/):  _commodities_ref.csv, _commodity_tokens.csv
Output  (staging/):  crosswalk_commodity_wa.csv
    columns: token, n_deposits, n_primary, commodity_id, commodity_name, method
    method: ELEMENT | CURATED | SPLIT:<t> | DROP | UNMAPPED
Multi-element tokens ("copper gold") emit one row per element with method SPLIT.
"""
import csv, io

HERE = "wa_deposit_extract/staging/"

ref_by_name, ref_by_sym = {}, {}
with io.open(HERE + "_commodities_ref.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rid = int(r["commodity_id"])
        ref_by_name[r["commodity_name"].strip().lower()] = (rid, r["commodity_name"])
        if r["commodity_symbol"].strip():
            ref_by_sym[r["commodity_symbol"].strip().lower()] = (rid, r["commodity_name"])

def by_sym(s):  return ref_by_sym[s.lower()]
def by_name(n): return ref_by_name[n.lower()]

# element word -> chemical symbol (symbol is how commodities stores elements)
ELEM = {
 "gold":"Au","silver":"Ag","copper":"Cu","cooper":"Cu","lead":"Pb","zinc":"Zn","iron":"Fe",
 "manganese":"Mn","chromium":"Cr","nickel":"Ni","tungsten":"W","uranium":"U","antimony":"Sb",
 "molybdenum":"Mo","mercury":"Hg","arsenic":"As","tin":"Sn","cobalt":"Co","vanadium":"V",
 "titanium":"Ti","bismuth":"Bi","cadmium":"Cd","thallium":"Tl","thorium":"Th","tellurium":"Te",
 "selenium":"Se","cerium":"Ce","strontium":"Sr","gallium":"Ga","germanium":"Ge","phosphorus":"P",
 "sulfur":"S","sulfer":"S","beryllium":"Be","scandium":"Sc","yttrium":"Y","osmium":"Os",
 "tantalum":"Ta","aluminium":"Al","aluminum":"Al","iridium":"Ir","niobium":"Nb","zirconium":"Zr",
 "platinum":"Pt","magnesium":"Mg",
}
# industrial minerals / rocks / materials -> commodities.commodity_name
CURATED = {
 "limestone and marble":"Limestone","travertine":"Limestone","marl":"Limestone","dolomite":"Limestone",
 "coal":"Coal","peat":"Peat","pumice":"Pumice","pumicite":"Pumice",
 "common clays and shales":"Clay","refractory clays and shales":"Clay","special clays - nontronite":"Clay",
 "special clays - expanding clays and shales":"Clay","special clays - expanding":"Clay",
 "special clays - fuller's earth":"Fullers Earth","special clays - bentonite":"Bentonite",
 "sandstone":"Sandstone","diatomite":"Diatomite","silica sand":"Silica Sand","barite":"Baryte",
 "serpentine":"Serpentine","massive quartz":"Quartz","quartz crystal":"Quartz","quartzite":"Quartz",
 "graphite":"Graphite","talc and soapstone":"Talc","magnesite":"MgCO3","mica":"Mica",
 "fluorite":"Fluorite","andalusite":"Andalusite","sillimanite":"Sillimanite","and kyanite":"Kyanite",
 "garnet":"Garnet","perlite":"Perlite","feldspar":"Feldspar","gypsum":"Gypsum","olivine":"Olivine",
 "beryl":"Be","corundum":"Corundum","sodium carbonate":"Soda Ash","ferruginous bauxite":"Bauxite",
 "nephelite":"Nepheline Syenite","alunite":"Alunite","alum":"Alunite","sodium sulfate":"Thenardite",
 "magnesium sulfate":"Epsomite","asbestiform materials":"Asbestos",
 "granite and allied plutonic rocks":"Granite","slate and other platy rocks":"Slate",
 "gem and ornamental stones":"Miscellaneous Dimension Stones","mineral pigments":"Ochre",
}
# multi-element phrases -> list of element words
SPLIT = {
 "copper gold":["copper","gold"],"zinc gold":["zinc","gold"],"lead zinc":["lead","zinc"],
 "lead copper":["lead","copper"],"lead silver":["lead","silver"],"zinc silver":["zinc","silver"],
 "zinc antimony":["zinc","antimony"],"silver arsenic":["silver","arsenic"],
 "native copper":["copper"],"manganese float":["manganese"],"also gold":["gold"],
 "with some silver":["silver"],"graphite with some gold":["graphite","gold"],
 "gold amd silver gold":["gold","silver"],"magnesium sulfate and gypsite":["magnesium"],
 "platinum group elements":["platinum"],"chalcopyrite":["copper"],
}
DROP = {"plutonium","unknown","pyrite","flour","niobium?","manganese?"}

rows_out = []
with io.open(HERE + "_commodity_tokens.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        tok = r["token"]; nd = r["n_deposits"]; npr = r["n_primary"]
        def emit(cid, cname, method):
            rows_out.append([tok, nd, npr, cid, cname, method])
        if tok in DROP:
            emit("", "", "DROP")
        elif tok in ELEM:
            cid, cn = by_sym(ELEM[tok]); emit(cid, cn, "ELEMENT")
        elif tok in CURATED:
            tgt = CURATED[tok]
            cid, cn = (by_sym(tgt) if len(tgt) <= 2 else by_name(tgt))
            emit(cid, cn, "CURATED")
        elif tok in SPLIT:
            for e in SPLIT[tok]:
                if e in ELEM:
                    cid, cn = by_sym(ELEM[e])
                else:
                    tgt = CURATED[e]
                    cid, cn = (by_sym(tgt) if len(tgt) <= 2 else by_name(tgt))
                emit(cid, cn, "SPLIT:" + e)
        else:
            emit("", "", "UNMAPPED")

with io.open(HERE + "crosswalk_commodity_wa.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["token", "n_deposits", "n_primary", "commodity_id", "commodity_name", "method"])
    w.writerows(rows_out)

# summary
tot = mapped = dropped = unmapped = 0
unmapped_dep = 0
seen = set()
for tok, nd, npr, cid, cn, method in rows_out:
    if tok in seen: continue
    seen.add(tok); tot += 1
    if method == "DROP": dropped += 1
    elif method == "UNMAPPED": unmapped += 1; unmapped_dep += int(nd)
    else: mapped += 1
print("tokens: %d  (mapped %d, dropped %d, unmapped %d)" % (tot, mapped, dropped, unmapped))
print("deposit-commodity links lost to UNMAPPED: %d" % unmapped_dep)
print("\nUNMAPPED / DROP tokens:")
for tok, nd, npr, cid, cn, method in rows_out:
    if method in ("UNMAPPED", "DROP"):
        print("  %-32s n=%-4s %s" % (tok, nd, method))
