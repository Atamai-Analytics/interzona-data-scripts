"""Shared parsing for the Critical Minerals in Ores (CMMI / Geoscience Australia) geochemistry CSV -> gold geochem structures."""
import csv, re, collections

CSV = r"D:\CriticalMineralsDB\Global\CriticalMineralDepositsGeochemistry.csv"
SOURCE = "GLOBAL_DEPOSIT_GEOCHEM_GA"
TAG = "claude_cmio_geochem_20261023"

# CSV analyte code -> gold analyte_id (geochem.analytes). Derived sums (REE, HREE, LREE, REE_Y, REST) are deliberately left out.
ANALYTE = {
 "AG": 382, "AL": 297, "AS": 288, "AU": 405, "B": 313, "BA": 333, "BE": 406, "BI": 319, "BR": 332, "C": 335, "CA": 334, "CD": 318, "CE": 314,
 "CL": 403, "CO": 374, "CR": 377, "CS": 412, "CU": 413, "DY": 339, "ER": 350, "EU": 372, "F": 404, "FE": 396, "GA": 408, "GD": 376, "GE": 324,
 "HF": 356, "HG": 317, "HO": 340, "IN": 323, "IR": 363, "K": 385, "LA": 295, "LI": 316, "LU": 343, "MG": 384, "MN": 391, "MO": 381, "NA": 386,
 "NB": 357, "ND": 329, "NI": 373, "OS": 411, "P": 399, "PB": 364, "PD": 362, "PR": 315, "PT": 361, "RB": 311, "RH": 286, "RU": 287,
 "S": 296, "SB": 378, "SC": 310, "SE": 409, "SI": 415, "SM": 330, "SN": 379, "SR": 407, "TA": 358, "TB": 338, "TE": 410, "TH": 359, "TI": 336,
 "TL": 322, "TM": 341, "U": 360, "V": 312, "W": 380, "Y": 344, "YB": 342, "ZN": 414, "ZR": 355,
 "AL2O3": 383, "CAO": 389, "CO2": 425, "FE2O3": 387, "FEO": 426, "FE2O3TOT": 427, "K2O": 299, "MGO": 298, "MNO": 306, "NA2O": 300, "P2O5": 302,
 "SIO2": 419, "SO3": 325, "TIO2": 301, "H2OPLUS": 393, "H2OMINUS": 393, "H2OTOTAL": 393, "LOITOT": 420, "MLOI": 420, "TOTAL": 285,
}
# analytes that share a gold analyte (water, loss on ignition): keep which one the source reported in method_name
VARIANT_NAME = {"H2OPLUS": "H2O+ (structural water)", "H2OMINUS": "H2O- (adsorbed water)", "H2OTOTAL": "H2O total", "LOITOT": "Loss on ignition (total)", "MLOI": "Loss on ignition (measured)", "TOTAL": "Total (sum of reported constituents)"}
UNIT = {"WT_PERCENT": 152, "PPM": 137, "PPB": 138}   # wt%, ppm, ppb
UNIT_CODE = {152: "wt%", 137: "ppm", 138: "ppb"}
# RE is excluded too: its values (median 22 ppm, up to 55,600) are far too high for rhenium, so it is a rare-earth total, not an element.
EXCLUDED = {"REE", "HREE", "LREE", "REE_Y", "REST", "RE"}

SAMPLE_TYPE = {  # CSV SAMPLE_TYPE (stripped) -> (sample_type_id, sample_context)
    "core": (7, "DRILLHOLE_POINT"), "quarter core": (36, "DRILLHOLE_POINT"), "half core": (35, "DRILLHOLE_POINT"), "drill core": (7, "DRILLHOLE_POINT"),
    "borehole specimen": (7, "DRILLHOLE_POINT"), "drill cutting/sludge": (8, "DRILLHOLE_POINT"), "drill chips/cuttings": (8, "DRILLHOLE_POINT"),
    "hand specimen": (4, "SURFACE"), "outcrop specimen": (30, "SURFACE"), "outcrop": (30, "SURFACE"), "float specimen": (29, "SURFACE"),
    "mine site specimen": (4, "SURFACE"), "mine waste specimen": (4, "SURFACE"), "mine dump": (4, "SURFACE"),
    "unconsolidated surficial specimen": (4, "SURFACE"), "mineral separate": (4, "OTHER"), "unknown": (4, "OTHER"),
}
COMPANY = re.compile(r"\b(ltd|limited|inc|corp|corporation|pty|plc|llc|minerals|resources|mining|mines|exploration|gold|copper)\b", re.I)


def load_rows():
    csv.field_size_limit(10**9)
    with open(CSV, encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


def analyte_columns(cols):
    """[(analyte_code, unit_id, value_col, dl_col, method_col)] for every reported analyte column we load."""
    out = []
    for c in cols:
        m = re.match(r"^(.*)_(WT_PERCENT|PPM|PPB)$", c)
        if not m or m.group(1) in EXCLUDED or m.group(1) not in ANALYTE:
            continue
        a, u = m.group(1), m.group(2)
        out.append((a, UNIT[u], c, f"{a}_DETECTION_LIMIT" if f"{a}_DETECTION_LIMIT" in cols else None, f"{a}_METHOD" if f"{a}_METHOD" in cols else None))
    return out


def fnum(s):
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_results(rows, acols):
    """Yields dicts of every analyte value in every row, with the classification the gold conventions call for."""
    for ri, r in enumerate(rows):
        for a, unit_id, vc, dc, mc in acols:
            v = fnum(r[vc])
            if v is None:
                continue
            dl = fnum(r[dc]) if dc else None
            meth = (r[mc].strip() if mc else "") or "unknown"
            qual = None
            status, dlv, stats = "DETECTED", None, True
            if v < 0:
                qual, val = "<", abs(v)
                dlv = dl if dl else val
                status = "BELOW_DL_CERTAIN" if (dl and abs(abs(v) - dl) <= 0.01 * dl) else "BELOW_DL_PROBABLE"
                stats = False
            elif v == 0:
                val, status, stats = 0.0, "NULL_RESULT", False
            else:
                val = v
            active = True
            if v > 0:
                limit = {152: 110.0 if a == "TOTAL" else 100.0, 137: 1e6, 138: 1e9}[unit_id]
                if val in (9999.0, 99999.0, 999999.0):
                    status, stats, active = "SENTINEL", False, False
                elif val > limit:
                    status, stats, active = "SUSPECT", False, False
            yield {"row": ri, "analyte": a, "analyte_id": ANALYTE[a], "unit_id": unit_id, "value": val, "dl": dl, "method": meth, "qual": qual, "active": active, "status": status, "dl_value": dlv, "stats": stats}
