"""SIGÉOM (Québec) code dictionaries shared by load_sigeom_qc.py (rock samples, drill holes) and load_sigeom_qc_sed.py (sediment, soil, till).
Sources: Domain_values_all_utf8.csv and gq.mines.gouv.qc.ca/documentation_en/additional_information/geochemistry.
"""
import datetime
import re

def sdate(s):
    s = (s or "").strip()
    if re.fullmatch(r"(1[89]|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", s):
        try:   # the pattern still lets through dates such as 1971-11-31
            return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
        except ValueError:
            return None
    return None



# SIGÉOM method code -> (package, SIGÉOM description)
METHOD = {
    "FUS_SM": ("SIGEOM-LIBOR-ICPMS", "Lithium meta/tetraborate fusion + ICP-MS"), "FUS_ICP": ("SIGEOM-LIBOR-ICPOES", "Lithium meta/tetraborate fusion + ICP-AES/OES"),
    "FUS_FX": ("SIGEOM-LIBOR-XRF", "Lithium meta/tetraborate fusion + XRF"), "FX": ("SIGEOM-XRF", "X-ray fluorescence"),
    "SX": ("SIGEOM-XRF", "X-ray spectrometry"), "FUS_NA": ("SIGEOM-NAPEROX-ICPMS", "Sodium peroxide fusion + ICP-MS"),
    "FUS_NA_ICP": ("SIGEOM-NAPEROX-ICPOES", "Sodium peroxide fusion + ICP-AES/OES"), "FUS_ES": ("SIGEOM-LIBOR-ISE", "Lithium meta/tetraborate fusion + ISE"),
    "DT_SM": ("SIGEOM-4A-ICPMS", "4 acid total digestion + ICP-MS"), "DT_ICP": ("SIGEOM-4A-ICPOES", "4 acid total digestion + ICP-AES/OES"),
    "DT_OES": ("SIGEOM-4A-ICPOES", "4 acid total digestion + ICP-OES"), "DT_AA": ("SIGEOM-4A-AAS", "4 acid total digestion + atomic absorption"),
    "AR_SM": ("SIGEOM-AR-ICPMS", "Aqua regia + ICP-MS"), "AR_ICP": ("SIGEOM-AR-ICPOES", "Aqua regia + ICP-AES/OES"),
    "AR_AA": ("SIGEOM-AR-AAS", "Aqua regia + atomic absorption"), "ICP": ("SIGEOM-ICP", "Inductively coupled plasma (MS/AES/OES), dissolution not recorded"),
    "ICPt": ("SIGEOM-ICP-TOTAL", "ICP after total dissolution"), "PL": ("SIGEOM-PLASMA", "Plasma emission, dissolution not recorded"),
    "AA": ("SIGEOM-AAS", "Atomic absorption, dissolution not recorded"), "AN": ("SIGEOM-INAA", "Neutron activation analysis"),
    "PY": ("SIGEOM-FA", "Fire assay, finish not recorded"), "PY_AA": ("SIGEOM-FA-AAS", "Fire assay + atomic absorption"),
    "PY_ICP": ("SIGEOM-FA-ICPOES", "Fire assay + ICP-AES/OES"), "PY_SM": ("SIGEOM-FA-ICPMS", "Fire assay + ICP-MS"),
    "PY_NI": ("SIGEOM-FA-ICPMS", "NiS fire assay + ICP-MS"), "PY_AG": ("SIGEOM-FA-GRAV", "Fire assay + gravimetric analysis"),
    "PY_PCC": ("SIGEOM-FA-DCP", "Fire assay + direct current plasma"), "PY_AN": ("SIGEOM-FA-INAA", "Fire assay + INAA"),
    "AG": ("SIGEOM-GRAV", "Gravimetric analysis"), "CG": ("SIGEOM-WETCHEM", "Classical chemical analysis"),
    "IF": ("SIGEOM-IR", "Infrared"), "IR": ("SIGEOM-IR", "Infrared spectroscopy"), "COUL": ("SIGEOM-COUL", "Coulometry"),
    "SM": ("SIGEOM-MS", "Mass spectrometry, dissolution not recorded"), "ES": ("SIGEOM-ISE", "Ion selective electrode"),
    "KOH_ES": ("SIGEOM-KOH-ISE", "KOH fusion + ion-selective electrode"), "KOH_CI": ("SIGEOM-KOH-IC", "KOH fusion + ionic chromatography"),
    "CO": ("SIGEOM-COLOR", "Colorimetry"), "FL": ("SIGEOM-FLUOR", "Fluorometry"), "DNC": ("SIGEOM-DNC", "Delayed neutron counting"),
    "HPA_ID": ("SIGEOM-HPA-ICPMS", "High pressure asher isotope dilution + ICP-MS"), "PCC": ("SIGEOM-DCP", "Direct current plasma"),
    "CM": ("SIGEOM-CHROM", "Chromatography and mass spectrometry"), "PGNAA": ("SIGEOM-PGNAA", "Prompt gamma neutron activation analysis"),
    "YO": ("SIGEOM-UNK", "Method unknown"), "": ("SIGEOM-UNK", "Method not recorded"),
}
SKIP_METHODS = {"SOM_ETR", "SOM_EGP", "CAL", "DX"}   # sums, calculations, XRD
# package -> (name, gold method_code, basis, priority)
PACKAGES = {
    "SIGEOM-LIBOR-ICPMS": ("SIGÉOM - lithium borate fusion with ICP-MS", "LIBOR-ICPOES", "T", 1),
    "SIGEOM-LIBOR-ICPOES": ("SIGÉOM - lithium borate fusion with ICP-AES/OES", "LIBOR-ICPOES", "T", 2),
    "SIGEOM-LIBOR-XRF": ("SIGÉOM - lithium borate fusion with XRF", "LIBOR-XRF", "T", 1),
    "SIGEOM-XRF": ("SIGÉOM - X-ray fluorescence / X-ray spectrometry", "NONE-XRF", "T", 2),
    "SIGEOM-NAPEROX-ICPMS": ("SIGÉOM - sodium peroxide fusion with ICP-MS", "NAPEROX-ICPMS", "T", 1),
    "SIGEOM-NAPEROX-ICPOES": ("SIGÉOM - sodium peroxide fusion with ICP-AES/OES", "NAPEROX-ICPOES", "T", 2),
    "SIGEOM-LIBOR-ISE": ("SIGÉOM - lithium borate fusion with ion-selective electrode", "UNKNOWN-UNKNOWN", "T", 3),
    "SIGEOM-4A-ICPMS": ("SIGÉOM - four-acid digestion with ICP-MS", "4A-ICPMS", "P", 1),
    "SIGEOM-4A-ICPOES": ("SIGÉOM - four-acid digestion with ICP-AES/OES", "4A-ICPOES", "P", 2),
    "SIGEOM-4A-AAS": ("SIGÉOM - four-acid digestion with AAS", "UNKNOWN-UNKNOWN", "P", 3),
    "SIGEOM-AR-ICPMS": ("SIGÉOM - aqua regia with ICP-MS", "AR-ICPMS", "P", 1),
    "SIGEOM-AR-ICPOES": ("SIGÉOM - aqua regia with ICP-AES/OES", "AR-ICPOES", "P", 2),
    "SIGEOM-AR-AAS": ("SIGÉOM - aqua regia with AAS", "UNKNOWN-UNKNOWN", "P", 4),
    "SIGEOM-ICP": ("SIGÉOM - ICP, dissolution not recorded", "UNKNOWN-UNKNOWN", "P", 3),
    "SIGEOM-ICP-TOTAL": ("SIGÉOM - ICP after total dissolution", "UNKNOWN-UNKNOWN", "T", 3),
    "SIGEOM-PLASMA": ("SIGÉOM - plasma emission, dissolution not recorded", "UNKNOWN-UNKNOWN", "P", 4),
    "SIGEOM-AAS": ("SIGÉOM - AAS, dissolution not recorded", "UNKNOWN-UNKNOWN", "P", 4),
    "SIGEOM-INAA": ("SIGÉOM - neutron activation analysis", "NONE-INAA", "T", 2),
    "SIGEOM-FA": ("SIGÉOM - fire assay, finish not recorded", "UNKNOWN-UNKNOWN", "T", 3),
    "SIGEOM-FA-AAS": ("SIGÉOM - fire assay with AAS", "FA-AAS", "T", 2),
    "SIGEOM-FA-ICPOES": ("SIGÉOM - fire assay with ICP-AES/OES", "FA-ICPOES", "T", 2),
    "SIGEOM-FA-ICPMS": ("SIGÉOM - fire assay (Pb or NiS) with ICP-MS", "FA-ICPMS", "T", 1),
    "SIGEOM-FA-GRAV": ("SIGÉOM - fire assay with gravimetric finish", "FA-GRAV", "T", 1),
    "SIGEOM-FA-DCP": ("SIGÉOM - fire assay with direct current plasma", "FA-DCP", "T", 2),
    "SIGEOM-FA-INAA": ("SIGÉOM - fire assay with INAA", "NONE-INAA", "T", 2),
    "SIGEOM-GRAV": ("SIGÉOM - gravimetric analysis", "NONE-GRAV", "T", 4),
    "SIGEOM-WETCHEM": ("SIGÉOM - classical chemical analysis", "NONE-GRAV", "T", 4),
    "SIGEOM-IR": ("SIGÉOM - infrared (combustion C, S)", "NONE-LECO", "T", 1),
    "SIGEOM-COUL": ("SIGÉOM - coulometry", "UNKNOWN-UNKNOWN", "T", 3),
    "SIGEOM-MS": ("SIGÉOM - mass spectrometry, dissolution not recorded", "UNKNOWN-UNKNOWN", "P", 5),
    "SIGEOM-ISE": ("SIGÉOM - ion selective electrode", "UNKNOWN-UNKNOWN", "T", 5),
    "SIGEOM-KOH-ISE": ("SIGÉOM - KOH fusion with ion-selective electrode", "UNKNOWN-UNKNOWN", "T", 4),
    "SIGEOM-KOH-IC": ("SIGÉOM - KOH fusion with ion chromatography", "KOH-IC", "T", 4),
    "SIGEOM-COLOR": ("SIGÉOM - colorimetry", "NONE-COLORIMETRY", "P", 6),
    "SIGEOM-FLUOR": ("SIGÉOM - fluorometry", "UNKNOWN-UNKNOWN", "P", 6),
    "SIGEOM-DNC": ("SIGÉOM - delayed neutron counting", "NONE-DNC", "T", 2),
    "SIGEOM-HPA-ICPMS": ("SIGÉOM - high pressure asher isotope dilution ICP-MS", "UNKNOWN-UNKNOWN", "T", 1),
    "SIGEOM-DCP": ("SIGÉOM - direct current plasma", "UNKNOWN-UNKNOWN", "P", 5),
    "SIGEOM-CHROM": ("SIGÉOM - chromatography and mass spectrometry", "UNKNOWN-UNKNOWN", "P", 6),
    "SIGEOM-PGNAA": ("SIGÉOM - prompt gamma neutron activation analysis", "UNKNOWN-UNKNOWN", "T", 4),
    "SIGEOM-UNK": ("SIGÉOM - method unknown or not recorded", "UNKNOWN-UNKNOWN", "P", 9),
}
ANALYTE = {"PAF": "LOI", "Fe2O3t": "FETO3", "Fe2O3v": "Fe2O3", "TOT": "Sum", "C tot": "C", "CO2 in": "CO2", "H2O+": "H2O", "H2O-": "Moisture",
           "N": "Nitrogen", "AS_O": "As", "IN_O": "In"}
CONVERT = {"Nb2O5": ("Nb", 0.69904e4), "Ta2O5": ("Ta", 0.81897e4), "Y2O3": ("Y", 0.78744e4)}   # % oxide -> ppm element
SKIP_ANALYTES = {"ETR", "EGP", "TOT2", "PAF2", "Ct:CO2", "C org", "Cgraph", "Ne", "Np", "Ra", "Xe", "Ar", "Rn", "Po", "Ac", "Pm"}
NEG_OK = {"LOI", "Sum"}
MULT = {"A": "", "B": "reanalysis", "C": "rare earths", "D": "rare earth reanalysis", "E": "other", "P": "partial attack", "F": "code F", "G": "code G"}
PREC = {"0": "location precision indeterminate", "1": "location precision low", "2": "location precision medium", "3": "location precision high"}

# method codes seen only in the sediment results: three are truncated in the source table, three are older techniques
METHOD.update({
    "AR_S": ("SIGEOM-AR-ICPMS", "Aqua regia + ICP-MS (code truncated in source: AR_S)"),
    "AR_I": ("SIGEOM-AR-ICPOES", "Aqua regia + ICP-AES/OES (code truncated in source: AR_I)"),
    "FUS_": ("SIGEOM-LIBOR", "Lithium meta/tetraborate fusion, finish not recorded (code truncated in source: FUS_)"),
    "CP": ("SIGEOM-PAPERCHROM", "Paper chromatography"), "EA": ("SIGEOM-AES", "Atomic emission spectroscopy"),
    "EF": ("SIGEOM-FLAME", "Flame emission spectroscopy"),
})
PACKAGES.update({
    "SIGEOM-LIBOR": ("SIGÉOM - lithium borate fusion, finish not recorded", "LIBOR-ICPOES", "T", 2),
    "SIGEOM-PAPERCHROM": ("SIGÉOM - paper chromatography (U)", "UNKNOWN-UNKNOWN", "P", 6),
    "SIGEOM-AES": ("SIGÉOM - atomic emission spectroscopy, dissolution not recorded", "UNKNOWN-UNKNOWN", "P", 5),
    "SIGEOM-FLAME": ("SIGÉOM - flame emission spectroscopy, dissolution not recorded", "UNKNOWN-UNKNOWN", "P", 5),
})
