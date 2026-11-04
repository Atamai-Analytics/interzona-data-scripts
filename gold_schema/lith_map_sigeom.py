"""Map Québec SIGÉOM rock codes (CODE_TYPE_ROCH, e.g. 'V3B', 'I4QM', and drill-log strings such as 'I1[PO]QZ', 'M8(AC', 'V3B[FO]AM') to
geochem.lithology codes.

Order: (1) curated SIGÉOM code -> lithology; (2) the code's English name from the SIGÉOM domain-value file, through lith_map_mrt.map_lithology
(exact / synonym / base / keyword); (3) the same for the parent code (I4QM -> I4Q -> I4 -> I); (4) None (the loader stores UNKNOWN).
The SIGÉOM text itself is always kept verbatim in lithology_observations.lithology_local.
Lexicon: Domain_values_all_utf8.csv (gq.mines.gouv.qc.ca/documents/SIGEOM/TOUTQC/ANG/FGDB/Model_Domain-value/), domain CODE_TYPE_ROCH.
"""
import csv
import re
from lith_map_mrt import map_lithology

LEXICON = "D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_domain_values/Domain_values_all_utf8.csv"

# curated: SIGÉOM code -> geochem.lithology code (group codes and names the name mapper misses)
CODE = {
    "I": "IGNUND", "I1": "FELINT", "I2": "INTUND", "I3": "MAFUND", "I4": "ULMFUND", "V": "VOLUND", "V1": "FELVOL", "V2": "INTUND", "V3": "MAFUND",
    "V4": "KOMATIITE", "S": "SEDUND", "M": "METUND", "T": "TECTONITE", "A": "WEATHERED", "F": "SULFIDE_ORE", "R": "UNKNOWN", "XXXX": "UNKNOWN",
    "S9": "IRON_FORM", "S9A": "IRON_FORM", "S9B": "BIF", "S9D": "IRON_FORM", "S9C": "IRON_FORM", "S9E": "IRON_FORM",
    "I4Q": "CARBONATITE", "I4QM": "CARBONATITE", "I3G": "ANOR", "I3I": "GABBRO", "I3K": "GABBRO", "I4ZN": "OXIDE_ORE", "M16": "AMPHIBOLITE",
    "M8": "SCHIST", "M1": "GNEISS", "M4": "GNEISS", "M12": "QUARTZITE_METAMORPHIC", "S6D": "MUDSTONE", "S3": "GREYWACKE",
}
LEAD = re.compile(r"^\(?\s*([A-Z]{1,2}[0-9]{0,2}[A-Z]{0,3})")


def load_names(path=LEXICON):
    with open(path, encoding="utf-8") as fh:
        return {r["VALR_CODE"]: r["ANG"] for r in csv.DictReader(fh) if r["NOM_PARM_STAN"] == "CODE_TYPE_ROCH"}


def lead_code(text):
    """The rock code at the start of a SIGÉOM string ('I1[PO]QZ' -> 'I1', '(V4' -> 'V4', 'M8(AC' -> 'M8'); None for free text."""
    m = LEAD.match((text or "").strip())
    return m.group(1) if m else None


def map_sigeom(text, names, by_name, valid):
    """-> (lithology code or None, how). valid = set of geochem.lithology codes (curated codes not in it are skipped)."""
    code = lead_code(text)
    if not code:
        return None, "none"
    c = code
    while c:
        if c in CODE and CODE[c] in valid:
            return CODE[c], "code" if c == code else "parent code"
        if c in names:
            got, how = map_lithology(names[c], by_name)
            if got and got in valid:
                return got, ("name " if c == code else "parent name ") + how
        c = c[:-1]
    return None, "none"
