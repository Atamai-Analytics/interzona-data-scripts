"""Shared SARIG rules (copied unchanged from load_sa_sarig_surface.py, phase 1, so the drill load classifies methods and values identically).
Method family -> package SA-<digestion>-<finish>; units; analyte codes left out; value parsing."""
import re

ANALYTE = {"Total": "Sum", "FeTO3": "FETO3"}
SKIP_CODE = {"pH", "EC", "206Pb", "207Pb", "208Pb", "HMIN", "O2", "TGC", "Fe2", "Fe3", "CO3", "CaMg(CO3)2", "H2O_plus", "H2O_minus"}
UNIT = {"ppm": ("ppm", 1.0), "ppb": ("ppb", 1.0), "%": ("%", 1.0), "g/T": ("ppm", 1.0), "g/t": ("ppm", 1.0)}
TOTAL_DIG = {"4A", "FUS", "FA", "NONE"}
PXRF = {"P-XRF", "XRFInnovX", "XRFNiton", "XRFOlympus", "pXRF", "pXRF-30", "pXRF-30NDL", "pXRF-30RT", "pXRF-34", "pXRF-NQ", "pXRF-corr", "pXRF34", "XRFDelta"}


def family(code, desc, dig, det):
    t = " ".join([code, desc, dig, det]).lower()
    c = code.lower()
    if c in ("me-ms81", "me-icp06"): d = "FUS"
    elif "microwave" in t: d = "MW"
    elif "enzyme" in t or "ezyme" in t: d = "ENZ"
    elif re.search(r"\bmmi\b|mobile metal", t): d = "MMI"
    elif "terra" in t or c.startswith("tl"): d = "TL"
    elif "bleg" in t or "bulk leach" in t or "cyanide" in t: d = "CN"
    elif "water leach" in t or re.search(r"\bwl\b", c): d = "WATER"
    elif re.search(r"partial|selective|weak|buffered|ionic|enzyme|neutral", t): d = "LEACH"
    elif "fire assay" in t or c.startswith(("fa", "pgm", "au-")) or "fa/" in c or c.startswith("au"): d = "FA"
    elif re.search(r"aqua regia|\bar\b|ar/|arm\d|b/oes|b/eoes|b/ms|bt/oes|bveg|me-icp41|me-ms41|aqua", t): d = "AR"
    elif re.search(r"four acid|4 acid|4a|four-acid|hf|multi.?acid|mixed acid|near total|me-icp61|me-ms61|ic3|ic4r", t): d = "4A"
    elif re.search(r"three.?acid|3 acid|two.?acid|2 acid|perchloric|hclo4|m/aas", t): d = "3A"
    elif "nitric" in t: d = "HNO3"
    elif re.search(r"fusion|fused|borate|peroxide|sinter|xf\d|xrf4b|fs/", t): d = "FUS"
    elif re.search(r"xrf|neutron|inaa|pressed|leco|combust|gravimet|loi", t): d = "NONE"
    else: d = "UNK"
    if re.search(r"mass spec|icp-?ms|/ms\b|-ms\d|\bms\b|elan|ims\d", t) or c.startswith("arm") or d in ("MW", "ENZ"): e = "ICPMS"
    elif re.search(r"oes|aes|optical|emission|icp\b|icp-|ic2e|ic3e", t): e = "ICPOES"
    elif re.search(r"atomic absorption|\baas\b|/aas|\baa\b|gfaas|graphite furnace|carbon rod", t) or d == "CN": e = "AAS"
    elif "xrf" in t or "x-ray fl" in t: e = "XRF"
    elif "neutron" in t or "inaa" in t: e = "INAA"
    elif "leco" in t or "combust" in t: e = "LECO"
    elif "gravimet" in t or "loi" in t or "loss on ignition" in t: e = "GRAV"
    elif "electrode" in t or "ise" in t: e = "ISE"
    elif "colori" in t: e = "COLOR"
    else: e = "OTHER"
    if e in ("XRF", "INAA", "LECO", "GRAV") and d == "UNK": d = "NONE"
    return d, e


METHOD = {("AR", "ICPMS"): "AR-ICPMS", ("AR", "ICPOES"): "AR-ICPOES", ("AR", "AAS"): "AR-AAS", ("4A", "ICPMS"): "4A-ICPMS", ("4A", "ICPOES"): "4A-ICPOES",
          ("4A", "AAS"): "4A-AAS", ("3A", "ICPMS"): "MX-ICPMS", ("3A", "ICPOES"): "MX-ICPOES", ("FUS", "ICPMS"): "LIBOR-ICPMS", ("FUS", "ICPOES"): "LIBOR-ICPOES",
          ("FUS", "XRF"): "LIBOR-XRF", ("FUS", "AAS"): "LIBOR-AAS", ("FA", "AAS"): "FA-AAS", ("FA", "ICPMS"): "FA-ICPMS", ("FA", "ICPOES"): "FA-ICPOES",
          ("FA", "OTHER"): "FA-AAS", ("MMI", "ICPMS"): "MMI-ICPMS", ("CN", "AAS"): "CN-AAS", ("CN", "ICPMS"): "CN-ICPMS", ("WATER", "ICPMS"): "WATER-ICPMS",
          ("LEACH", "ICPMS"): "WEAKACID-ICPMS", ("NONE", "XRF"): "NONE-XRF", ("NONE", "INAA"): "NONE-INAA", ("NONE", "LECO"): "NONE-LECO",
          ("NONE", "GRAV"): "NONE-GRAV", ("UNK", "ICPMS"): "UNK-ICPMS", ("MW", "ICPMS"): "MW-ICPMS", ("ENZ", "ICPMS"): "ENZYME-ICPMS",
          ("HNO3", "AAS"): "HNO3-AAS", ("HNO3", "ICPMS"): "HNO3-ICPMS", ("TL", "ICPMS"): "WEAKALK-ICPMS"}
PRIO = {"ICPMS": 1, "ICPOES": 2, "XRF": 3, "INAA": 2, "AAS": 4, "LECO": 1, "GRAV": 3, "ISE": 4, "COLOR": 5, "OTHER": 6}
DIGN = {"AR": "aqua regia", "4A": "four-acid (near total)", "3A": "three-acid / perchloric", "FUS": "fusion", "FA": "fire assay", "MMI": "MMI partial leach",
        "TL": "TerraLeach partial digest", "CN": "cyanide / BLEG leach", "WATER": "water leach", "LEACH": "other partial / selective leach",
        "NONE": "no digestion", "UNK": "digestion not recorded", "MW": "microwave acid digestion", "ENZ": "enzyme leach", "HNO3": "nitric acid leach"}


def pkg_rule(d, e):
    basis = "T" if d in TOTAL_DIG else "P"
    prio = PRIO[e] + (6 if d in ("MMI", "TL", "CN", "WATER", "LEACH", "ENZ") else 0) + (3 if d in ("UNK", "HNO3") else 0)
    return METHOD.get((d, e), "UNKNOWN-UNKNOWN"), basis, prio


VAL = re.compile(r"^([<>])\s*(-?[0-9.]+(?:[eE][-+]?\d+)?)$")


def parse_value(v, code, mult):
    """-> (qualifier, value, lower dl, upper dl, status 'D'/'B'/'A') or a reason string to leave the row out"""
    v = v.strip()
    m = VAL.match(v)
    try:
        if m:
            x = float(m.group(2)) * mult
            if x <= 0: return "bad limit"
            return ("<", x, x, None, "B") if m.group(1) == "<" else (">", x, None, x, "A")
        x = float(v) * mult
    except ValueError:
        return "unparsed value"
    if x < 0 and code != "LOI": return "negative value left out"
    if x == 0: return "zero left out"
    return (None, x, None, None, "D")
