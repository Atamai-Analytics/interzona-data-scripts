"""Assign packages to the NSW assay keys (ASSAYCODE, FIELD1, FIELD2) that the user's hand-made mapping never covered, learning from that mapping first,
and write a review workbook for the user. No database writes.

Inputs (gold_schema/nsw_mapping/): nsw_mapping_exact.csv (the user's mapping, recovered exactly from bronze), nsw_source_keys_not_in_mapping.csv.
Rules, in order (first that applies):
  0 PORTABLE  - portable / handheld XRF or XRF error-estimate rows (Niton, Delta, Olympus, Vanta, pXRF, '_err' / 'error' codes)   -> excluded
  1 SAMECODE  - the same ASSAYCODE appears in the user's mapping and one package carries >= 80 % of its rows -> that package; when several, the
                package whose lab prefix matches the lab named in FIELD1 / FIELD2 / LAB_CODE (ALS, AMDEL, Analabs, SGS, Genalysis ...) -> that package
  2 NAMEMATCH - the code matches an existing package code ignoring case, dashes and spaces, directly or with a lab prefix (IC581 -> ALS-ICP581,
                G001 -> 'ALS -G001', MEICP41 -> ME-ICP41)
  3 FAMILY    - method family from the code + description text (as for South Australia) -> the user's generic UNK-* package for that family when one
                exists (UNK-AAS, UNK-MMI, UNK-BLEG ...), otherwise a new AUTO-<digestion>-<finish> package
  4 UNKNOWN   - nothing recognisable -> UNK-UNK-UNK
A key the user mapped to a portable-XRF package (ONSITE-XRF, UNK-pXRF, UNK-NITON, PXRF73) by rule 1 is also excluded.
Outputs: nsw_mapping/nsw_auto_mapping.csv (every unmapped key) and nsw_mapping/NSW_method_review_20261117.xlsx (top 200 lab keys by rows + summary).
"""
import csv, os, re, collections
import psycopg2
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "nsw_mapping")
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SELECT package_code, package_name FROM geochem.analytical_packages")
PKG = dict(c.fetchall())
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
PKN = collections.defaultdict(list)
for p in PKG: PKN[norm(p)].append(p)
PORT_PKG = {"ONSITE-XRF", "UNK-pXRF", "UNK-NITON", "PXRF73"}
PORT = re.compile(r"niton|\bnit\b|delta|olympus|vanta|innov|pxrf|portable|hand.?held|_err\b|\berr\b|error", re.I)
LABS = [("ALS", r"\bals\b|als global|als chemex|australian laboratory services|ali?s orange|als minerals"), ("AMD", r"amdel"),
        ("ANA", r"analabs"), ("SGS", r"\bsgs\b"), ("GEN", r"genalysis|intertek"), ("AAL", r"australian assay lab|\baal\b"),
        ("ULTRATRACE", r"ultra ?trace"), ("BV", r"bureau veritas|\bbv\b"), ("COMLABS", r"comlabs"), ("TET", r"\btet\b"),
        ("LABWEST", r"labwest"), ("ACME", r"\bacme\b"), ("NBH", r"\bnbh\b|broken hill"), ("MCPHAR", r"mcphar")]


def lab_of(txt):
    t = txt.lower()
    for pre, rx in LABS:
        if re.search(rx, t): return pre
    return None


# user's mapping by assay code
user = collections.defaultdict(collections.Counter)
for r in csv.DictReader(open(os.path.join(D, "nsw_mapping_exact.csv"), encoding="utf-8")):
    user[r["ASSAYCODE"].strip().upper()][r["package_code"]] += int(r["source_rows"])

GENERIC = {("AR", "AAS"): "UNK-AR-AAS", ("4A", "AAS"): "UNK-MA-AAS", ("3A", "AAS"): "UNK-MA-AAS", ("UNK", "AAS"): "UNK-AAS", ("4A", "ICPOES"): "UNK-MA-ICP-OES",
           ("UNK", "ICPOES"): "UNK-ICP-AES", ("UNK", "ICP"): "UNK-ICP", ("MMI", "ICPMS"): "UNK-MMI", ("MMI", "OTHER"): "UNK-MMI", ("CN", "AAS"): "UNK-BLEG",
           ("CN", "OTHER"): "UNK-BLEG", ("NONE", "INAA"): "UNK-INAA", ("FA", "AAS"): "UNK-FA", ("FA", "OTHER"): "UNK-FA", ("NONE", "XRF"): "UNK-XRF",
           ("UNK", "XRF"): "UNK-XRF", ("UNK", "COLOR"): "UNK-COLOR", ("NONE", "GRAV"): "UNK-GRAV"}
AUTO_METHOD = {("AR", "ICPMS"): "AR-ICPMS", ("AR", "ICPOES"): "AR-ICPOES", ("4A", "ICPMS"): "4A-ICPMS", ("3A", "ICPMS"): "MX-ICPMS", ("3A", "ICPOES"): "MX-ICPOES",
               ("FUS", "ICPMS"): "LIBOR-ICPMS", ("FUS", "ICPOES"): "LIBOR-ICPOES", ("FUS", "XRF"): "LIBOR-XRF", ("FA", "ICPMS"): "FA-ICPMS",
               ("FA", "ICPOES"): "FA-ICPOES", ("UNK", "ICPMS"): "UNK-ICPMS", ("LEACH", "ICPMS"): "WEAKACID-ICPMS", ("ENZ", "ICPMS"): "ENZYME-ICPMS",
               ("TL", "ICPMS"): "WEAKALK-ICPMS", ("CN", "ICPMS"): "CN-ICPMS", ("NONE", "LECO"): "NONE-LECO", ("HNO3", "AAS"): "HNO3-AAS"}


KNOWN = {"1DX": ("AUTO-AR-ICPMS", "Acme / Bureau Veritas group 1DX = aqua regia digestion, ICP-MS"),
         "1DX1": ("AUTO-AR-ICPMS", "Acme / Bureau Veritas group 1DX = aqua regia digestion, ICP-MS"),
         "1DX2": ("AUTO-AR-ICPMS", "Acme / Bureau Veritas group 1DX = aqua regia digestion, ICP-MS"),
         "1DX3": ("AUTO-AR-ICPMS", "Acme / Bureau Veritas group 1DX = aqua regia digestion, ICP-MS"),
         "1F": ("AUTO-AR-ICPMS", "Acme group 1F = aqua regia digestion, ICP-MS (ultratrace)"),
         "1EX": ("AUTO-4A-ICPMS", "Acme group 1EX = four-acid digestion, ICP-MS"),
         "AQ200": ("AUTO-AR-ICPMS", "Bureau Veritas AQ200 = aqua regia, ICP-MS"), "AQ250": ("AUTO-AR-ICPMS", "Bureau Veritas AQ250 = aqua regia, ICP-MS (ultratrace)"),
         "MA200": ("AUTO-4A-ICPMS", "Bureau Veritas MA200 = four-acid digestion, ICP-MS")}


def family(t):
    t = t.lower()
    if re.search(r"\bmmi\b|mobile metal", t): d = "MMI"
    elif "regoleach" in t or "terra" in t: d = "TL"
    elif "enzyme" in t: d = "ENZ"
    elif re.search(r"bleg|bulk leach|cyanide|\bcn\b|bcl", t): d = "CN"
    elif re.search(r"partial|selective|weak|ionic|\bchcl\b", t): d = "LEACH"
    elif re.search(r"fire assay|\bfa\d*\b|fa/|pgm|\bpm2\d\d|\bau-?aa|fa25|fa50", t): d = "FA"
    elif re.search(r"aqua.?regia|\bar\b|ar_|ar/|arm\d|\bmeicp4[1-4]|me-?ms4[1-4]|me-?icp4[1-4]|ultratrace aqua", t): d = "AR"
    elif re.search(r"four acid|4.?acid|multi.?acid|mixed acid|\bhf\b|near total|me-?ms6\d|me-?icp6\d|4a|ic3|ic4", t): d = "4A"
    elif re.search(r"three.?acid|two.?acid|perchloric|hclo4", t): d = "3A"
    elif "nitric" in t: d = "HNO3"
    elif re.search(r"fusion|fused|borate|peroxide|sinter|ms81|icp06", t): d = "FUS"
    elif re.search(r"xrf|neutron|inaa|leco|combust|gravimet|\bloi\b", t): d = "NONE"
    else: d = "UNK"
    if re.search(r"mass spec|icp.?ms|/ms\b|-ms\d|\bms\b|_ms\b|elan", t): e = "ICPMS"
    elif re.search(r"oes|aes|optical|emission|\bicp\b|icp-|\bic\d", t): e = "ICPOES"
    elif re.search(r"atomic absorption|\baas?\d*\b|/aas|gfaas|graphite furnace|carbon rod", t): e = "AAS"
    elif "xrf" in t or "x-ray fl" in t: e = "XRF"
    elif "neutron" in t or "inaa" in t: e = "INAA"
    elif "leco" in t or "combust" in t: e = "LECO"
    elif "gravimet" in t or "loi" in t: e = "GRAV"
    elif "colori" in t: e = "COLOR"
    else: e = "OTHER"
    return d, e


out, new_pkgs = [], {}
for r in csv.DictReader(open(os.path.join(D, "nsw_source_keys_not_in_mapping.csv"), encoding="utf-8")):
    ac, f1, f2, lab, unit, els, n = r["ASSAYCODE"], r["FIELD1"], r["FIELD2"], r["LAB_CODE"], r["UNITS"], r["elements"], int(r["source_rows"])
    txt = " ".join([ac, f1, f2, lab])
    labpre = lab_of(" ".join([f1, f2, lab]))
    pk, rule, conf, why = None, None, None, ""
    if PORT.search(" ".join([ac, f1, f2])):
        pk, rule, conf, why = "(excluded)", "PORTABLE", "high", "portable / handheld XRF or XRF error-estimate code"
    kc = KNOWN.get(ac.strip().upper())
    if pk is None and kc:
        pk, rule, conf, why = kc[0], "KNOWNCODE", "medium", kc[1]
        if pk.startswith("AUTO-"): new_pkgs[pk] = AUTO_METHOD.get(tuple(pk.split("-")[1:3]), "UNKNOWN-UNKNOWN")
    if pk is None and re.search(r"regoleach", " ".join([f1, f2]), re.I) and "ALS-REGOLEACH" in PKG:
        pk, rule, conf, why = "ALS-REGOLEACH", "FAMILY", "high", "description names ALS Regoleach partial leach"
    if pk is None and ac.strip().upper() in user:
        cnt = user[ac.strip().upper()]; tot = sum(cnt.values()); top, tn = cnt.most_common(1)[0]
        cands = [p for p in cnt if labpre and (p.upper().startswith(labpre) or (labpre == "ALS" and re.match(r"^(ME-|AU-|ALS)", p, re.I)))]
        if tn >= 0.8 * tot:
            pk, rule, conf, why = top, "SAMECODE", "high", f"your mapping sends code '{ac}' to {top} ({tn / tot:.0%} of its rows)"
        elif cands:
            best = max(cands, key=lambda p: cnt[p])
            pk, rule, conf, why = best, "SAMECODE", "medium", f"your mapping sends code '{ac}' to several packages; lab '{labpre}' named here -> {best}"
        else:
            generic = [p for p in cnt if p.upper().startswith(("UNK", "ONSITE"))]
            best = max(generic, key=lambda p: cnt[p]) if generic else top
            pk, rule, conf, why = best, "SAMECODE", "low", f"code '{ac}' maps to several packages in your mapping ({', '.join(p for p, _ in cnt.most_common(3))}); no lab named -> {best}"
        if pk in PORT_PKG:
            why += " (a portable-XRF package: excluded)"
    if pk is None and ac.strip():
        nk = norm(ac)
        hits = PKN.get(nk, []) or [p for pre in ([labpre] if labpre else []) + ["ALS", "AMD", "ANA", "SGS", "UNK", "AAL", "GEN"]
                                     for p in PKN.get(norm(pre + nk), []) + PKN.get(norm(pre + nk.replace("ic", "icp", 1)), [])]
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1 or (hits and labpre and any(h.upper().startswith(labpre) for h in hits)):
            best = next((h for h in hits if labpre and h.upper().startswith(labpre)), hits[0])
            pk, rule, conf, why = best, "NAMEMATCH", "high" if len(hits) == 1 else "medium", f"code '{ac}' matches existing package {best}"
    if pk is None:
        d, e = family(txt)
        if (d, e) == ("UNK", "OTHER") or not txt.strip() or ac.strip().lower() in ("unk", "0", "unknown", ""):
            pk, rule, conf, why = "UNK-UNK-UNK", "UNKNOWN", "low", "no method information"
        elif (d, e) in GENERIC and GENERIC[(d, e)] in PKG:
            pk, rule, conf, why = GENERIC[(d, e)], "FAMILY", "medium", f"description reads as {d}/{e}; your generic package {GENERIC[(d, e)]}"
        else:
            pk = f"AUTO-{d}-{e}"; new_pkgs[pk] = AUTO_METHOD.get((d, e), "UNKNOWN-UNKNOWN")
            rule, conf, why = "FAMILY", "medium" if d != "UNK" and e != "OTHER" else "low", f"description reads as {d}/{e}; new auto package"
    out.append([ac, f1, f2, lab, unit, els, n, pk, rule, conf, why])

out.sort(key=lambda x: -x[6])
with open(os.path.join(D, "nsw_auto_mapping.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "LAB_CODE", "UNITS", "elements", "source_rows", "package_code", "rule", "confidence", "reason"])
    w.writerows(out)

summ = collections.Counter(); summ_k = collections.Counter()
for x in out:
    cat = "excluded (portable XRF)" if x[7] == "(excluded)" or x[7] in PORT_PKG else f"{x[8]} / {x[9]}"
    summ[cat] += x[6]; summ_k[cat] += 1
for k, v in sorted(summ.items(), key=lambda x: -x[1]): print(f"{k:32s} {v:>12,} rows  {summ_k[k]:>5} keys")
print("new AUTO packages:", new_pkgs)

lab = [x for x in out if x[7] != "(excluded)" and x[7] not in PORT_PKG]
wb = Workbook(); ws = wb.active; ws.title = "Review top 200"
hdr = ["Rank", "Source rows", "ASSAYCODE", "FIELD1 (description)", "FIELD2 (lab / note)", "LAB_CODE", "Units", "Elements (top)",
       "Assigned package", "Package name", "Rule", "Confidence", "Why", "YOUR package (fill only to change)", "Notes"]
ws.append(hdr)
for i, x in enumerate(lab[:200], 1):
    ws.append([i, x[6], x[0], x[1], x[2], x[3], x[4], x[5], x[7], PKG.get(x[7], "new - " + new_pkgs.get(x[7], "")), x[8], x[9], x[10], "", ""])
fill = PatternFill("solid", fgColor="DDEBF7"); yel = PatternFill("solid", fgColor="FFF2CC")
for cell in ws[1]: cell.font = Font(bold=True); cell.fill = fill; cell.alignment = Alignment(wrap_text=True, vertical="top")
for row in ws.iter_rows(min_row=2):
    row[13].fill = yel
    if row[11].value == "low": row[11].font = Font(color="C00000", bold=True)
widths = [6, 12, 14, 40, 30, 10, 7, 30, 18, 34, 11, 11, 60, 24, 24]
for col, wdt in zip("ABCDEFGHIJKLMNO", widths): ws.column_dimensions[col].width = wdt
ws.freeze_panes = "C2"
s = wb.create_sheet("Summary")
s.append(["NSW rebuild - method mapping for the assay codes your mapping did not cover", ""]); s["A1"].font = Font(bold=True, size=12)
s.append(["Your mapping (recovered exactly from bronze): 2,882 keys, 0 conflicts - used unchanged.", ""])
s.append(["This workbook lists the TOP 200 uncovered lab keys by row count (about 80 % of the uncovered lab rows).", ""])
s.append(["To change an assignment, type the package code you want in the yellow column; leave it blank to accept.", ""])
s.append(["", ""]); s.append(["Category (all uncovered keys)", "Source rows", "Keys"])
for k, v in sorted(summ.items(), key=lambda x: -x[1]): s.append([k, v, summ_k[k]])
s.append(["", ""]); s.append(["Rules: KNOWNCODE = well-known lab code (e.g. Acme 1DX); SAMECODE = your mapping's package for the same assay code; NAMEMATCH = code equals one of your package codes; "
                               "FAMILY = method read from the description; UNKNOWN = no method information (lowest priority); PORTABLE = excluded.", ""])
s.column_dimensions["A"].width = 60; s.column_dimensions["B"].width = 14
ex = wb.create_sheet("Excluded - check")
ex.append(["Source rows", "ASSAYCODE", "FIELD1", "FIELD2", "LAB_CODE", "Elements", "Excluded because", "INCLUDE? (type Y to keep and give a package)", "Package if kept"])
for x in sorted((x for x in out if x[7] in PORT_PKG or x[7] == "(excluded)"), key=lambda x: -x[6])[:60]:
    ex.append([x[6], x[0], x[1], x[2], x[3], x[5], x[10] if x[8] != "PORTABLE" else "portable / handheld XRF or XRF error-estimate code", "", ""])
for cell in ex[1]: cell.font = Font(bold=True); cell.fill = fill
for row in ex.iter_rows(min_row=2): row[7].fill = yel; row[8].fill = yel
for col, wdt in zip("ABCDEFGHI", [12, 14, 34, 26, 10, 30, 60, 18, 18]): ex.column_dimensions[col].width = wdt
x2 = wb.create_sheet("New AUTO packages"); x2.append(["package_code", "gold method"])
for k, v in new_pkgs.items(): x2.append([k, v])
wb.save(os.path.join(D, "NSW_method_review_20261117.xlsx"))
print("review rows", min(200, len(lab)), "covering", f"{sum(x[6] for x in lab[:200]) / sum(x[6] for x in lab):.0%}", "of uncovered lab rows")
