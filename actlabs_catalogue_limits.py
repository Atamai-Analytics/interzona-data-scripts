#!/usr/bin/env python3
"""Extract Actlabs lower reporting limits from the 2026 Geochemistry Schedule of Services and attach them to the GEUS ND table.

Tables parsed (by word position, the PDF is a graphical multi-column layout):
  INAA (p.12): packages 1D, 1D Enhanced, 5B, 5S                -> lower limit per element
  Lithium borate fusion (p.14): 4B (ICP-OES), 4B2-Std, 4B2-Research, 4 Litho, 4 Litho-Research
A number in parentheses, e.g. "(0.5++)", means the element is only an optional add-on in that package: it is NOT taken as a limit.
All limits are converted to ppm (% x 10,000; ppb / 1,000).

Output:  actlabs_catalogue_limits.csv (long: element, catalogue_code, lower_limit_ppm, raw)
         geus_nd_by_element_method_with_catalogue.csv / .xlsx  (the ND table + catalogue limit + note for Actlabs groups)
"""
import re
import pandas as pd
import pdfplumber

PDF = "D:/Documents/Laboratory Catalogues/Actlabs_Geochemistry_Schedule_of_Services_2026-02-24_EUR.pdf"
ELEM = re.compile(r"^(Ag|Al|As|Au|B|Ba|Be|Bi|Br|C|Ca|Cd|Ce|Cl|Co|Cr|Cs|Cu|Dy|Er|Eu|F|Fe|Ga|Gd|Ge|Hf|Hg|Ho|I|In|Ir|K|La|Li|Lu|Mg|Mn|Mo|Na|Nb|Nd|Ni|P|Pb|Pd|Pr|Pt|Rb|Re|Rh|Ru|S|Sb|Sc|Se|Si|Sm|Sn|Sr|Ta|Tb|Te|Th|Ti|Tl|Tm|U|V|W|Y|Yb|Zn|Zr)$")
NUM = re.compile(r"^(\d[\d,]*\.?\d*)(%|ppb|ppm)?$")


def to_ppm(val, unit):
    v = float(val.replace(",", ""))
    return v * 10000 if unit == "%" else v / 1000 if unit == "ppb" else v


def find_page(pdf, *needles):
    for i, p in enumerate(pdf.pages):
        t = p.extract_text() or ""
        if all(n in t for n in needles):
            return p
    raise SystemExit(f"page not found: {needles}")


def element_rows(page, xmax):
    """[(element, top)] for words that look like an element symbol in the leftmost label column."""
    out = []
    for w in page.extract_words():
        if w["x0"] < xmax and w["x0"] > 225 and ELEM.match(w["text"]):
            out.append((w["text"], w["top"]))
    out.sort(key=lambda t: t[1])
    return out


def parse(page, cols, xmax, row_pad_before=5, row_pad_after=None):
    """cols = {code: (x_from, x_to)}.  Return rows (element, code, lower_ppm or None, raw)."""
    words = page.extract_words()
    els = element_rows(page, xmax)
    res = []
    for k, (el, top) in enumerate(els):
        lo = top - row_pad_before
        hi = (els[k + 1][1] - row_pad_before) if k + 1 < len(els) else top + 30
        cell = [w for w in words if lo <= w["top"] < hi and w["x0"] > xmax]
        for code, (x0, x1) in cols.items():
            toks = sorted([w for w in cell if x0 <= w["x0"] < x1], key=lambda w: (round(w["top"]), w["x0"]))
            raw = " ".join(w["text"] for w in toks)
            lim = None
            unit_tok = next((w["text"] for w in toks if w["text"] in ("%", "ppb")), None)   # "0.05 - 10 %" / "5 - 5,000 ppb": unit stands after the range
            for w in toks:                                    # first bare number = the standard lower limit
                m = NUM.match(w["text"])
                if m and not w["text"].startswith("("):
                    lim = to_ppm(m.group(1), m.group(2) or unit_tok)
                    break
            res.append((el, code, lim, raw))
    return res


def main():
    with pdfplumber.open(PDF) as pdf:
        pi = find_page(pdf, "INAA (ppm)", "1D Enhanced")
        # INAA: element labels at x~233; value columns 270-300 (1D), 340-370 (1D Enhanced), 410-440 (5B), 500-530 (5S)
        inaa = parse(pi, {"INAA 1D": (265, 335), "INAA 1D Enhanced": (338, 405), "INAA 5B": (408, 495), "INAA 5S": (498, 600)}, 245, 4)
        pf = find_page(pdf, "4B2-Std", "Lithogeochemistry")
        fus = parse(pf, {"4B (ICP-OES)": (285, 345), "4B2-Std (ICP-MS)": (346, 398), "4B2-Research": (399, 460), "4 Litho": (461, 514), "4 Litho-Research": (515, 600)}, 262, 6)
    cat = pd.DataFrame(inaa + fus, columns=["element", "catalogue_code", "lower_limit_ppm", "raw"])
    cat.to_csv("actlabs_catalogue_limits.csv", index=False)
    got = cat.dropna(subset=["lower_limit_ppm"])
    print("catalogue values extracted:", len(got), "| by code:", got.catalogue_code.value_counts().to_dict())
    pivot = got.pivot_table(index="element", columns="catalogue_code", values="lower_limit_ppm", aggfunc="first")
    pd.set_option("display.width", 250)
    print(pivot.reindex(["Ag", "As", "Au", "Ba", "Be", "Bi", "Cd", "Co", "Cr", "Cs", "Cu", "Hf", "Hg", "Mo", "Ni", "Rb", "Sb", "Sc", "Se", "Sn", "Ta", "Th", "U", "W", "Zn"]).to_string())

    nd = pd.read_csv("geus_nd_by_element_method.csv")
    # Only mappings that I could justify: INAA (validated against the limits in the data: median ratio 1.0) and fusion ICP-MS (4B2-Std; no data limits to validate against).
    # The fusion ICP-OES / "4B" mappings were tried and dropped: only 7 elements have a standard 4B limit and where checked the catalogue was ~5x the data limit.
    MAP = {"ACTLABS-NON-INAA": ("INAA 1D", "INAA 1D Enhanced"),
           "ACTLABS-FUS-ICP-MS": ("4B2-Std (ICP-MS)", "4B2-Research")}
    lk = got.set_index(["element", "catalogue_code"]).lower_limit_ppm.to_dict()
    rows = []
    for r in nd.itertuples():
        cc, c2, lim, lim2, note = None, None, None, None, ""
        if r.method_code in MAP:
            cc, c2 = MAP[r.method_code]
            lim = lk.get((r.element, cc))
            lim2 = lk.get((r.element, c2)) if c2 else None
        rows.append((cc, lim, lim2))
    nd["catalogue_code_used"] = [x[0] for x in rows]
    nd["catalogue_lower_limit_ppm"] = [x[1] for x in rows]
    nd["catalogue_alt_limit_ppm"] = [x[2] for x in rows]
    has_data = nd.min_limit_excl_10000_placeholder.notna()
    has_cat = nd.catalogue_lower_limit_ppm.notna()

    def basis(r):
        if pd.notna(r.min_limit_excl_10000_placeholder):
            return "Lower limit taken from the source data (lowest '<' limit reported for this element and method)."
        if pd.notna(r.catalogue_lower_limit_ppm):
            return (f"No lower limit in the source data: INFERRED from the Actlabs 2026 Geochemistry Schedule of Services, code {r.catalogue_code_used}. "
                    "Modern catalogue value; the limit at the time of analysis may have differed.")
        if r.method_code.startswith("ACTLABS"):
            return "No lower limit in the source data and none found in the Actlabs catalogue for the mapped code (element optional, not listed, or method not mapped)."
        return "No lower limit in the source data; method not from Actlabs (catalogue not applicable)."
    nd["limit_basis_note"] = nd.apply(basis, axis=1)
    nd.to_csv("geus_nd_by_element_method_with_catalogue.csv", index=False)
    with pd.ExcelWriter("geus_nd_by_element_method_with_catalogue.xlsx") as xw:
        nd.to_excel(xw, index=False, sheet_name="ND by element and method")
        got.to_excel(xw, index=False, sheet_name="Actlabs catalogue limits")

    ac = nd[nd.method_code.str.startswith("ACTLABS")]
    print("\nActlabs groups:", len(ac), "| ND rows", int(ac.nd_rows_blank.sum()))
    print(" limit from data      :", int((ac.min_limit_excl_10000_placeholder.notna()).sum()), "groups,", int(ac[ac.min_limit_excl_10000_placeholder.notna()].nd_rows_blank.sum()), "ND rows")
    inf = ac[ac.min_limit_excl_10000_placeholder.isna() & ac.catalogue_lower_limit_ppm.notna()]
    print(" inferred (catalogue) :", len(inf), "groups,", int(inf.nd_rows_blank.sum()), "ND rows")
    no = ac[ac.min_limit_excl_10000_placeholder.isna() & ac.catalogue_lower_limit_ppm.isna()]
    print(" still nothing        :", len(no), "groups,", int(no.nd_rows_blank.sum()), "ND rows;", no.method_code.value_counts().to_dict())
    # validation: where both exist, compare data-derived and catalogue limits
    b = ac[ac.min_limit_excl_10000_placeholder.notna() & ac.catalogue_lower_limit_ppm.notna()].copy()
    b["ratio"] = b.catalogue_lower_limit_ppm / b.min_limit_excl_10000_placeholder
    print("\nvalidation (groups with both):", len(b), "| catalogue within +-10% of data limit:", int(b.ratio.between(0.9, 1.1).sum()),
          "| within a factor 2:", int(b.ratio.between(0.5, 2).sum()), "| catalogue higher:", int((b.ratio > 1.1).sum()), "| lower:", int((b.ratio < 0.9).sum()))
    print(b.groupby("method_code").ratio.agg(["size", "median"]).to_string())


if __name__ == "__main__":
    main()
