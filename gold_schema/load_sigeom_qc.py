"""Québec SIGÉOM (Ministère des Ressources naturelles et des Forêts, CC BY 4.0) -> interzona_cm gold, source CANADA_QC_SIGEOM:
drill holes (Sondages GPKG) with lithology logs and reported mineralised intercepts, and rock geochemistry (Géochimie GPKG, rock samples only;
sediment samples are left for later).

Inputs (downloaded 2026-11-03 from gq.mines.gouv.qc.ca/documents/SIGEOM/TOUTQC/FRA/GPKG/, files dated 31 Oct 2026)
  D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_sondages/sigeom.gpkg   F5E02_FORAGE_DIAMANT, F5E05_UNITE_LITHOLOGIQUE, F5E06_SEQUENCE_MINERALISATION
  D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_geochem/sigeom.gpkg    R1E01_ECHANTILLON_ROCHE, R1E03_RESULTAT_ANALYSE_ER, R1R16_ECHN_ROCHE_DOCUMENT
  Code lists: Domain_values_all_utf8.csv + gq.mines.gouv.qc.ca/documentation_en/additional_information/geochemistry
What is loaded
  - every diamond drill hole; collar from UTM NAD83 (FUS = zone); start and end azimuth/dip as two survey rows (collar, end of hole);
    year drilled -> date_drilled = 1 January of that year (comments say year only)
  - lithology log units: to-depth given, from-depth = the previous unit's to-depth in the hole's sequence; SIGÉOM string kept verbatim;
    lithology mapped with lith_map_sigeom (bare 'M' / 'm' in a drill log is overburden, 'CAROTTE PERDUE' is lost core)
  - mineralised intercepts -> drilling.intercepts: element, grade, length, mineral; depth bounds = the lithology unit holding them
  - rock samples with their analyses. Diamond-drill samples (provenance FD) are sample_context DRILLHOLE_INTERVAL and linked to their hole by the
    hole name in the sample comment + shared assessment report (else the same name within 2 km); SIGÉOM's depth for them is a single projected
    vertical depth, kept in comments (no interval)
Values
  - '<' flag: value = detection limit (qualifier '<'); negative value = below detection at |value| (SIGÉOM convention); '>' = above upper limit
  - zero values are left out (23 rows); sums (ETR, EGP), calculated values, XRD and a few non-geochemical codes are left out
  - Nb2O5, Ta2O5, Y2O3 (%) are converted to Nb, Ta, Y (ppm)
Packages: one SIGEOM-* package per SIGÉOM method code; basis (total/partial) and priority set in geochem.source_package_rules.
Usage: python load_sigeom_qc.py [--dry]    (--dry = load + verify, then ROLLBACK)
"""
import os, sys, io, csv, time, re, collections, sqlite3
import psycopg2
from lith_map_sigeom import load_names, map_sigeom

DRY = "--dry" in sys.argv
TAG = "migration_sigeom_qc_20261103"
SRC = "CANADA_QC_SIGEOM"
XID = "SIGEOM"
GEO = "D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_geochem/sigeom.gpkg"
DDH = "D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_sondages/sigeom.gpkg"
HERE = os.path.dirname(os.path.abspath(__file__))

ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


N = "\\N"


def out(v):
    return N if v is None or v == "" else v


def key(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def sdate(s):
    s = (s or "").strip()
    if re.fullmatch(r"(1[89]|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


# ---------------------------------------------------------------- dictionaries
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
PROVENANCE = {"FD": ("CORE_SAMPLE", "diamond drilling"), "FM": ("DRILL_SAMPLE", "overburden drilling (rock beneath Quaternary cover)"),
              "ER": ("ROCK_OUTCROP", "rock sample (outcrop)"), "AC": ("ROCK_OUTCROP", "compilation outcrop"), "AG": ("ROCK_OUTCROP", "Géofiche outcrop"),
              "BE": ("ROCK_FLOAT", "erratic boulder"), "CM": ("ROCK_SELECT", "ore body"), "GNM": ("ROCK_SELECT", "non-metallic deposit"),
              "PI": ("ROCK_SAMPLE", "construction materials / industrial stone"), "": ("ROCK_SAMPLE", "provenance not recorded")}
SOURCE_TYPE = {"G": "government data", "C": "manual compilation", "I": "AI compilation from reports", "S": "numeric assessment data", "N": "source not specified"}
PREC = {"0": "location precision indeterminate", "1": "location precision low", "2": "location precision medium", "3": "location precision high"}
HOLE_RE = re.compile(r"(?:NO\.? ?FORAGE ORGN|NO\.? ?FOR ORGN|NO_TROU|NO_FORAGE|FORAGE|TROU|DDH)\s*:?\s*\[([^\]]+)\]", re.I)

geo = sqlite3.connect(f"file:{GEO}?mode=ro", uri=True)
ddh = sqlite3.connect(f"file:{DDH}?mode=ro", uri=True)

# ---------------------------------------------------------------- drill holes
collars, surveys, hole_by_name = [], [], collections.defaultdict(list)
for (n, azd, azf, pld, plf, e, nn, fus, alt, somr, orig, an, prec, rap, url, canton, comn, ltot) in ddh.execute(
        """SELECT NUMR_FORG_DIAMN, AZMT_DEPR, AZMT_FIN, PLON_DEPR, PLON_FIN, ESTN, NORD, FUS, ALTT, SOMR_LITH, NUMR_ORGN_FORG, AN_FORG, CODE_PREC_LOCL,
                  NUMR_RAPR, URL_NUMR_RAPR, NOM_CANT_SEIGN, COMN_FORG_DIAMN, LONG_TOTAL FROM F5E02_FORAGE_DIAMANT"""):
    hid = str(int(n))
    yr = int(an) if an and 1880 <= int(an) <= 2026 else None
    dip = pld if pld is not None and -90 <= pld <= 90 else None
    az = azd if azd is not None and 0 <= azd <= 360 else None
    note = "; ".join(x for x in [f"drilled {yr} (year only)" if yr else "", f"assessment report {rap}" if rap else "", url or "",
                                 f"township/seigneury {canton}" if canton else "", f"log summary: {somr}" if somr else "", comn or ""] if x)
    collars.append([hid, (orig or "").strip() or hid, f"{yr}-01-01" if yr else None, ltot if ltot and ltot > 0 else None, az, dip, alt,
                    e, nn, int(fus), PREC.get(str(prec), None), note])
    surveys.append([hid, 0, az, dip])
    if ltot and ltot > 0 and (azf is not None or plf is not None):
        surveys.append([hid, ltot, azf if azf is not None and 0 <= azf <= 360 else None, plf if plf is not None and -90 <= plf <= 90 else None])
    if orig: hole_by_name[key(orig)].append((hid, rap, e, nn, int(fus)))
log("collars", len(collars), "surveys", len(surveys))

names = load_names()
lith_rows = []          # [hid, seq, from, to, code, text, how]
units = {}
prev = {}
for n, seq, to, lith in ddh.execute("SELECT NUMR_FORG_DIAMN, NUMR_SEQN_LITH, PROF_FIN_UNITE_LITH, LITH FROM F5E05_UNITE_LITHOLOGIQUE ORDER BY NUMR_FORG_DIAMN, NUMR_SEQN_LITH"):
    hid = str(int(n))
    frm = prev.get(hid, 0.0)
    prev[hid] = to
    lith_rows.append([hid, int(seq), frm, to, lith])
    units[(hid, int(seq))] = (frm, to)
log("lithology units", len(lith_rows))

ints = []
for n, sm, sl, unit, longr, tenr, el, minr in ddh.execute("""SELECT NUMR_FORG_DIAMN, NUMR_SEQN_MINR, NUMR_SEQN_LITH, CODE_UNITE_TENR, LONGR, TENR,
                                                                  CODE_ELMN_CHIM, CODE_MINR FROM F5E06_SEQUENCE_MINERALISATION"""):
    hid = str(int(n))
    fr, to = units.get((hid, int(sl)) if sl is not None else None, (None, None))
    unit = {"Tr": None, "g/t": "ppm"}.get(unit, unit)
    ints.append([hid, f"{hid}:{int(sl) if sl is not None else ''}:{int(sm)}", int(sl) if sl is not None else None, fr, to, longr, ANALYTE.get(el, el) or None,
                 el or None, tenr if unit else None, unit, minr or None, "grade recorded as trace" if unit is None else None])
log("intercepts", len(ints))

# ---------------------------------------------------------------- rock samples
docs = collections.defaultdict(list)
for s, rap in geo.execute("SELECT NUMR_ECHN_UNIQ, NUMR_RAPR FROM R1R16_ECHN_ROCHE_DOCUMENT"):
    if rap: docs[int(s)].append(rap)
srows, link = [], collections.Counter()
for (s, e, nn, fus, dt, proj, prof, comn, troch, entt, prec, fno, styp) in geo.execute(
        """SELECT NUMR_ECHN_UNIQ, ESTN, NORD, FUS, DATE_ECHN, NUMR_PROJ, PROF, COMN_ECHN_ROCH, CODE_TYPE_ROCH, CODE_ENTT_GEOMT, CODE_PREC_LOCL,
                  NUMR_ECHN_ROCH_GEOLG, CODE_TYPE_ECHN_ROCH FROM R1E01_ECHANTILLON_ROCHE"""):
    sid = int(s)
    stype, prov = PROVENANCE.get(entt or "", ("ROCK_SAMPLE", f"provenance {entt}"))
    hid = None
    if entt in ("FD", "FM"):
        m = HOLE_RE.search(comn or "")
        if m:
            cands = hole_by_name.get(key(m.group(1)), [])
            byrep = [h for h in cands if h[1] in docs.get(sid, ())]
            near = [h for h in cands if h[4] == int(fus) and e and nn and h[2] and abs(h[2] - e) < 2000 and abs(h[3] - nn) < 2000]
            best = byrep or near
            if len(best) == 1: hid = best[0][0]; link["linked by report" if byrep else "linked within 2 km"] += 1
            else: link["ambiguous" if best else "hole name not matched"] += 1
        else: link["no hole name"] += 1
    reps = sorted(set(docs.get(sid, ())))
    note = "; ".join(x for x in [(comn or "").strip(), f"SIGÉOM projected vertical depth {prof} m" if prof else "",
                                 f"reports {', '.join(reps[:5])}" + (" ..." if len(reps) > 5 else "") if reps else "",
                                 PREC.get(str(prec), ""), f"project {proj}" if proj else ""] if x)
    srows.append([sid, stype, f"SIGÉOM: {prov} | {SOURCE_TYPE.get(styp or '', 'source ' + (styp or 'not recorded'))}",
                  "DRILLHOLE_INTERVAL" if entt in ("FD", "FM") else "SURFACE", e, nn, int(fus), sdate(dt), (fno or "").strip() or None,
                  str(sid), hid, note, troch or ""])
log("rock samples", len(srows), "| hole links", dict(link))

stats = collections.Counter()
res_path = os.path.join(HERE, "_sigeom_results.csv")
with open(res_path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    for (s, nres, el, unit, tenr, mult, adate, flag, meth) in geo.execute(
            """SELECT NUMR_ECHN_UNIQ, NUMR_RESL_ANLS, CODE_ELMN_CHIM, CODE_UNITE_TENR, TENR, CODE_ANLS_MULT, DATE_RESL_ANLS, CODE_INDC_PLUS_PETT_QUE,
                      CODE_METH_ANLS FROM R1E03_RESULTAT_ANALYSE_ER"""):
        meth = meth or ""
        if meth in SKIP_METHODS: stats["method left out: " + meth] += 1; continue
        if el in SKIP_ANALYTES: stats["analyte left out: " + el] += 1; continue
        if tenr is None or tenr == 0: stats["zero or empty value"] += 1; continue
        pkg, mdesc = METHOD[meth]
        fac = 1.0
        if el in CONVERT:
            code, fac = CONVERT[el]
            if unit != "%": stats["oxide not in %"] += 1; continue
            unit = "ppm"
        else:
            code = ANALYTE.get(el, el)
        flag = (flag or "").strip()
        if flag == ">": q, val, ldl, udl = ">", tenr * fac, None, tenr * fac; stats["above upper limit"] += 1
        elif flag == "<" or (tenr < 0 and code not in NEG_OK): q, val, ldl, udl = "<", abs(tenr) * fac, abs(tenr) * fac, None; stats["below detection"] += 1
        else: q, val, ldl, udl = None, tenr * fac, None, None
        comment = "; ".join(x for x in [MULT.get(mult or "A", "code " + str(mult)), f"SIGÉOM element {el}" if el != code else ""] if x) or None
        w.writerow([int(s), int(nres), pkg, code, unit, out(q), val, out(ldl), out(udl), out(sdate(adate)), f"{meth or 'not recorded'}: {mdesc}", out(comment)])
        stats["values"] += 1
log("results staged", dict(stats))

# ---------------------------------------------------------------- gold load
# partitions are created first in their own short transaction: CREATE ... PARTITION OF takes an exclusive lock on the parent table, which would
# otherwise block the live app's reads for the whole load. Empty partitions are harmless (a dry run leaves them in place).
p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
p0.autocommit = True
p0.cursor().execute("SET lock_timeout = '20s'")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_canada_qc_sigeom PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_canada_qc_sigeom PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
p0.close()
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                     user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '512MB'")


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); w = csv.writer(buf)
    for r in data:
        w.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


def utm(x, y, z):   # NAD83 UTM zone z -> WGS84 point (NULL outside zones 17-22)
    return f"CASE WHEN {z} BETWEEN 17 AND 22 AND {x} IS NOT NULL AND {y} IS NOT NULL THEN ST_Transform(ST_SetSRID(ST_MakePoint({x}, {y}), 26900 + {z}), 4326) END"


copy("st_collar", "hid text, name text, ddate date, eoh numeric, az numeric, dip numeric, z numeric, x numeric, y numeric, zone int, prec text, note text", collars)
copy("st_survey", "hid text, depth numeric, az numeric, dip numeric", surveys)
copy("st_sample", """sid bigint, stype text, stype_local text, ctx text, x numeric, y numeric, zone int, sdate date, field_no text, sample_no text,
  hid text, comments text, lith text""", srows)
c.execute("""CREATE TEMP TABLE st_result (sid bigint, nres int, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric,
  adate date, meth_name text, comment text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); nres = c.fetchone()[0]
assert nres == stats["values"], (nres, stats["values"])
log("staged: collars", len(collars), "samples", len(srows), "results", nres)

c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for code, (name, mcode, basis, prio) in PACKAGES.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "Québec SIGÉOM rock geochemistry, grouped by SIGÉOM method code (labs vary and are not recorded)", TAG))
c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
             SELECT package_id, 'P', 5, 'placeholder; see source_package_rules' FROM geochem.analytical_packages WHERE package_code LIKE 'SIGEOM-%' ON CONFLICT DO NOTHING""")
for code, (name, mcode, basis, prio) in PACKAGES.items():
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "SIGÉOM method mapping " + TAG, code))

for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)

# drill holes + surveys
c.execute(f"""
INSERT INTO drilling.drillholes (source_system, source_hole_id, hole_name, drill_type_id, drill_type_local, date_drilled, total_depth_m, azimuth_deg, dip_deg,
  collar_elevation_m, lat, lon, geom, geog, original_x, original_y, original_crs, position_method, comments, is_active, created_by, created_date)
SELECT '{SRC}', s.hid, s.name, (SELECT drill_type_id FROM geochem.drill_types WHERE drill_type_code = 'DIAMOND'), 'diamond drilling (SIGÉOM forage au diamant)',
  s.ddate, s.eoh, s.az, s.dip, s.z, ST_Y(p.pt), ST_X(p.pt), p.pt, p.pt::geography, s.x, s.y, 'NAD83 / UTM zone ' || s.zone || 'N (EPSG:' || (26900 + s.zone) || ')',
  s.prec, nullif(s.note, ''), true, '{TAG}', now()
FROM st_collar s LEFT JOIN LATERAL (SELECT {utm('s.x', 's.y', 's.zone')} AS pt) p ON true""")
log("drillholes", c.rowcount)
c.execute(f"""INSERT INTO drilling.surveys (drillhole_id, depth_m, azimuth_deg, dip_deg, survey_method, created_by, created_date)
              SELECT h.drillhole_id, s.depth, s.az, s.dip, CASE WHEN s.depth = 0 THEN 'collar (SIGÉOM start azimuth/dip)' ELSE 'end of hole (SIGÉOM end azimuth/dip)' END,
                     '{TAG}', now()
              FROM st_survey s JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.hid
              WHERE s.az IS NOT NULL OR s.dip IS NOT NULL""")
log("surveys", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'DRILLHOLE', drillhole_id, '{XID}', 'FORAGE:' || source_hole_id, '{TAG}', now() FROM drilling.drillholes WHERE source_system = '{SRC}'""")

# lithology log units + intercepts
c.execute("SELECT lower(lithology_name), lithology_code FROM geochem.lithology WHERE is_active ORDER BY lithology_id DESC")
by_name = dict(c.fetchall()); valid = set(by_name.values())
how_n = collections.Counter()
lrows = []
for hid, seq, frm, to, lith in lith_rows:
    t = (lith or "").strip()
    if t in ("M", "m", "MT"): code, how = "OVERBURDEN", "drill-log overburden code"
    elif t.upper().startswith("CAROTTE PERDUE"): code, how = "UNKNOWN", "lost core"
    else: code, how = map_sigeom(t, names, by_name, valid)
    how_n[how] += 1
    lrows.append([hid, seq, frm, to, code or "UNKNOWN", t, f"SIGÉOM log unit {seq}; lithology matched by {how}"])
assert all(r[4] in valid for r in lrows), "lithology code not in dictionary"
copy("st_lith", "hid text, seq int, dfrom numeric, dto numeric, code text, lith text, note text", lrows)
# ids drawn from the table's identity sequence (no temporary column on the live table)
c.execute("ALTER TABLE st_lith ADD COLUMN lid bigint")
c.execute("UPDATE st_lith SET lid = nextval('geochem.lithology_observations_lithology_observation_id_seq')")
c.execute("CREATE INDEX ON st_lith (hid, seq)")
c.execute("ANALYZE st_lith")
c.execute(f"""
INSERT INTO geochem.lithology_observations (lithology_observation_id, lithology_id, lithology_local, observation_context, drillhole_id, depth_from_m,
  depth_to_m, comments, is_active, created_by, created_date)
OVERRIDING SYSTEM VALUE
SELECT s.lid, l.lithology_id, nullif(s.lith, ''), 'DRILLHOLE_INTERVAL', h.drillhole_id, s.dfrom, s.dto, s.note, true, '{TAG}', now()
FROM st_lith s JOIN geochem.lithology l ON l.lithology_code = s.code
JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.hid""")
log("lithology obs", c.rowcount, "of", len(lrows), "| match:", dict(how_n))
copy("st_int", """hid text, iid text, seq int, dfrom numeric, dto numeric, len numeric, analyte text, el text, grade numeric, unit text, minr text, note text""", ints)
c.execute(f"""
INSERT INTO drilling.intercepts (drillhole_id, source_system, source_intercept_id, lithology_observation_id, depth_from_m, depth_to_m, position_basis,
  length_m, analyte_id, analyte_local, grade, unit_code, mineral_local, comments, is_active, created_by, created_date)
SELECT h.drillhole_id, '{SRC}', s.iid, o.lid, s.dfrom, s.dto, CASE WHEN o.lid IS NOT NULL THEN 'LITHOLOGY_UNIT' END,
  s.len, a.analyte_id, s.el, s.grade, s.unit, s.minr, s.note, true, '{TAG}', now()
FROM st_int s JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.hid
LEFT JOIN st_lith o ON o.hid = s.hid AND o.seq = s.seq
LEFT JOIN geochem.analytes a ON a.analyte_code = s.analyte""")
log("intercepts", c.rowcount, "of", len(ints))
c.execute(f"SELECT count(*) FILTER (WHERE analyte_id IS NULL), count(*) FILTER (WHERE lithology_observation_id IS NULL) FROM drilling.intercepts WHERE created_by = '{TAG}'")
log("intercepts without analyte / without a lithology unit", c.fetchone())


# samples
c.execute(f"""
INSERT INTO geochem.samples (geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, sample_date, comments, is_active,
  created_by, created_date, source_system, drillhole_id)
SELECT coalesce(p.pt, h.geom), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.sdate, nullif(s.comments, ''), true, '{TAG}', now(), '{SRC}', h.drillhole_id
FROM st_sample s JOIN geochem.sample_types t ON t.sample_type_code = s.stype
LEFT JOIN LATERAL (SELECT {utm('s.x', 's.y', 's.zone')} AS pt) p ON true
LEFT JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.hid
WHERE coalesce(p.pt, h.geom) IS NOT NULL AND EXISTS (SELECT 1 FROM st_result r WHERE r.sid = s.sid)
ORDER BY s.sid""")
log("samples", c.rowcount)
c.execute(f"CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT sample_number::bigint AS sid, sample_id FROM geochem.samples WHERE source_system = '{SRC}'")
c.execute("CREATE UNIQUE INDEX ON st_map (sid)")
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', sid::text, '{TAG}', now() FROM st_map""")
c.execute("DELETE FROM st_result r WHERE NOT EXISTS (SELECT 1 FROM st_map m WHERE m.sid = r.sid)")
n_nogeo = c.rowcount; nres -= n_nogeo
log("results left out (sample without location)", n_nogeo)

# lithology of the rock samples
srock = []
for r in srows:
    if not r[12]: continue
    code, how = map_sigeom(r[12], names, by_name, valid)
    srock.append([r[0], code or "UNKNOWN", r[12], r[3], f"SIGÉOM rock code; lithology matched by {how}"])
copy("st_slith", "sid bigint, code text, lith text, ctx text, note text", srock)
c.execute(f"""
INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sample_id, drillhole_id, comments, is_active, created_by, created_date)
SELECT l.lithology_id, s.lith, s.ctx, m.sample_id, sm.drillhole_id, s.note, true, '{TAG}', now()
FROM st_slith s JOIN st_map m ON m.sid = s.sid JOIN geochem.lithology l ON l.lithology_code = s.code
JOIN geochem.samples sm ON sm.sample_id = m.sample_id""")
log("sample lithology obs", c.rowcount)

# interval QC on the log units
QC = "drilling.interval_qc (drillhole_id, sample_id, lithology_observation_id, issue, detail, created_by)"
src_sql = f"""SELECT o.drillhole_id, o.lithology_observation_id AS lid, o.depth_from_m AS f, o.depth_to_m AS t, h.total_depth_m AS eoh
              FROM geochem.lithology_observations o JOIN drilling.drillholes h USING (drillhole_id) WHERE o.created_by = '{TAG}' AND o.sample_id IS NULL"""
c.execute(f"""INSERT INTO {QC}
  SELECT drillhole_id, NULL, lid, issue, detail, '{TAG}' FROM (
    SELECT x.*, 'MISSING_DEPTH' AS issue, 'to depth not recorded' AS detail FROM ({src_sql}) x WHERE t IS NULL
    UNION ALL SELECT x.*, 'FROM_GT_TO', format('from %s m > to %s m (log sequence out of depth order)', f, t) FROM ({src_sql}) x WHERE f > t
    UNION ALL SELECT x.*, 'ZERO_LENGTH', format('unit ends where the previous one ends (%s m)', t) FROM ({src_sql}) x WHERE f = t
    UNION ALL SELECT x.*, 'BEYOND_EOH', format('to %s m is past the end of hole %s m', t, eoh) FROM ({src_sql}) x WHERE eoh IS NOT NULL AND t > eoh + 0.5
  ) q""")
c.execute(f"SELECT issue, count(*), count(DISTINCT drillhole_id) FROM drilling.interval_qc WHERE created_by = '{TAG}' GROUP BY 1 ORDER BY 2 DESC")
log("interval QC (issue, flags, holes)", c.fetchall())

# results
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, r.meth_name, NULL, r.val, r.ldl, r.udl, NULL, r.adate, false, true, '{TAG}', now(),
  'SIGEOM:' || r.sid || ':' || r.nres, NULL, r.comment
FROM st_result r
JOIN st_map m ON m.sid = r.sid
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results WHERE source_system = '{SRC}'"); ngr = c.fetchone()[0]
log("gold results", ngr, "in", round(time.time() - t0), "s")
assert ngr == nres, (ngr, nres)

c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UDL' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END,
  CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results r WHERE r.source_system = '{SRC}'""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_sigeom_20261103', now(), now(), count(*), 'rule-based classification at load (SIGÉOM < / > flag, negative = below detection)'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute(f"SELECT result_status, use_in_statistics, count(*) FROM geochem.result_classifications WHERE source_system = '{SRC}' GROUP BY 1,2 ORDER BY 3 DESC")
log("classification", c.fetchall())

# verification
c.execute(f"""SELECT p.package_code, count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p ON p.package_id = r.package_id
 WHERE r.source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC"""); log("per package", c.fetchall())
c.execute(f"""SELECT t.sample_type_code, s.sample_context, count(*), count(s.drillhole_id) FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id)
 WHERE s.source_system = '{SRC}' GROUP BY 1,2 ORDER BY 3 DESC"""); log("sample types (type, context, n, on a hole)", c.fetchall())
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.source_system = '{SRC}' AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id)""")
log("samples without results (must be 0)", c.fetchone()[0])
c.execute(f"""SELECT count(*), count(*) FILTER (WHERE lat NOT BETWEEN 44.5 AND 63 OR lon NOT BETWEEN -80 AND -57), count(*) FILTER (WHERE geom IS NULL)
 FROM drilling.drillholes WHERE source_system = '{SRC}'"""); log("collars (total, outside Québec box, no position)", c.fetchone())
c.execute(f"""SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}' AND (lat NOT BETWEEN 44.5 AND 63 OR lon NOT BETWEEN -80 AND -57)""")
log("samples outside Québec box", c.fetchone()[0])

if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
os.remove(res_path)
