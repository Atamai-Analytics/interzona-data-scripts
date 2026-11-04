"""Saskatchewan Geological Survey open layers (Saskatchewan Mining and Petroleum GeoAtlas; Government of Saskatchewan Standard Unrestricted Use Data
Licence v2.0) -> interzona_cm gold, source CANADA_SK_SGS: drill-hole collars, till geochemistry, and lake-sediment geochemistry (GSC National
Geochemical Reconnaissance and the 1970s SGS/GSC uranium-era surveys).

Input: CSVs written by fetch_sask_layers.py (pulled 2026-11-03) in D:/CriticalMineralsDB/Canada/Saskatchewan_geochem_drillholes.
Left out: lake water (566 samples, 1970s, zeros stand for missing values), the government rock-sample layer (locations only, no chemistry).
What is loaded
  - every drill-hole collar (no assays or logs are published): drill type, depth, dip/azimuth, company, project, core storage; the depths to
    the base of the Quaternary / Phanerozoic / Athabasca Group and to crystalline basement are kept in comments
  - till: one row per sample x analysis set; each size fraction ('-0.063 mm', '-0.002 mm', ...) is its own sample ('<id> (<fraction>)')
    so different fractions are never mixed; package per digestion + method; lab and certificate on each result
  - lake sediment: GSC NGR (AAS / INAA columns as separate packages) and SGS uranium-era survey (technique text per row)
Values: 0 or blank = not analysed (left out); negative = below detection at |value| (qualifier '<'); '*' = not analysed.
Usage: python load_sask_sgs.py [--dry]
"""
import os, sys, io, csv, time, re, collections, datetime
import psycopg2

DRY = "--dry" in sys.argv
TAG = "migration_sask_sgs_20261103"
SRC = "CANADA_SK_SGS"
XID = "SASK_SGS"
DIR = "D:/CriticalMineralsDB/Canada/Saskatchewan_geochem_drillholes"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rows(name):
    with open(os.path.join(DIR, name + ".csv"), encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


def num(s):
    s = (s or "").strip()
    try: return float(s)
    except ValueError: return None


def epoch(s):
    x = num(s)
    return datetime.datetime.fromtimestamp(x / 1000, datetime.timezone.utc).date().isoformat() if x else None


SYMBOL = {"AS_": "As", "C0": "Co"}


def analyte(raw):
    """'AL2O3_PCT' -> ('Al2O3', '%'); 'HG_PPB' -> ('Hg', 'ppb'); oxides / elements written in capitals are re-cased."""
    m = re.fullmatch(r"([A-Z0-9]+)_(PPM|PCT|PPB)", raw)
    if not m: return None, None
    base, unit = m.group(1), {"PPM": "ppm", "PCT": "%", "PPB": "ppb"}[m.group(2)]
    code = re.sub(r"([A-Z][A-Z]?)(\d*)", lambda x: x.group(1)[0] + x.group(1)[1:].lower() + x.group(2), base)
    code = {"Fe2o3": "Fe2O3", "Al2o3": "Al2O3"}.get(code, code)
    code = re.sub(r"O(\d*)$", lambda x: "O" + x.group(1), code)
    return code, unit


OXIDE_FIX = {"Al2o3": "Al2O3", "Cao": "CaO", "Fe2o3": "Fe2O3", "K2o": "K2O", "Mgo": "MgO", "Mno": "MnO", "Na2o": "Na2O", "P2o5": "P2O5", "Tio2": "TiO2",
             "Sio2": "SiO2", "LoI": "LOI"}
TILL_SKIP = {"CALCITE_WTPCT", "DOLOMITE_WTPCT", "CO3_TOTAL_WTPCT", "PB204_PPM", "PB206_PPM", "PB207_PPM", "PB208_PPM", "PBSUM_PPM"}


def till_package(dig, dmeth, meth):
    d, dm, m = dig.lower(), dmeth.lower(), meth.lower()
    if "fire assay" in m: return "SKGS-FA-ICP"
    if "na2o2" in m or "na2o2" in dm or "peroxide" in m: return "SKGS-NAPEROX"
    if "loss on ignition" in m: return "SKGS-LOI"
    if "cv-aas" in m or "cold vapour" in m: return "SKGS-AR-CVAAS"
    four = "hf" in dm or d == "near-total"
    ar = "hcl" in dm or "aqua regia" in dm
    if "fluorim" in m: return "SKGS-4A-FLUOR" if four else "SKGS-AR-FLUOR" if ar else "SKGS-UNK"
    if "icp-ms" in m: return "SKGS-4A-ICPMS" if four else "SKGS-AR-ICPMS" if ar else "SKGS-UNK"
    if "icp" in m: return "SKGS-4A-ICPOES" if four else "SKGS-AR-ICPOES" if ar else "SKGS-UNK"
    if m == "aas" or "atomic absorption" in m: return "SKGS-HCL-AAS" if "hydrochloric" in dm else "SKGS-UNK"
    return "SKGS-UNK"


PACKAGES = {
    "SKGS-4A-ICPOES": ("SGS Saskatchewan - near-total (HF-HNO3-HClO4) digestion with ICP-AES/OES", "4A-ICPOES", "P", 1),
    "SKGS-4A-ICPMS": ("SGS Saskatchewan - near-total (HF-HNO3-HClO4) digestion with ICP-MS", "4A-ICPMS", "P", 1),
    "SKGS-4A-FLUOR": ("SGS Saskatchewan - near-total digestion with fluorimetry (U)", "UNKNOWN-UNKNOWN", "P", 2),
    "SKGS-AR-ICPOES": ("SGS Saskatchewan - partial (HNO3-HCl / aqua regia) digestion with ICP-AES/OES", "AR-ICPOES", "P", 2),
    "SKGS-AR-ICPMS": ("SGS Saskatchewan - partial (HNO3-HCl / aqua regia) digestion with ICP-MS", "AR-ICPMS", "P", 2),
    "SKGS-AR-FLUOR": ("SGS Saskatchewan - partial digestion with fluorimetry (U)", "UNKNOWN-UNKNOWN", "P", 3),
    "SKGS-AR-CVAAS": ("SGS Saskatchewan - nitric-aqua regia with cold-vapour AAS (Hg)", "UNKNOWN-UNKNOWN", "P", 2),
    "SKGS-HCL-AAS": ("SGS Saskatchewan - 1:1 HCl with AAS", "UNKNOWN-UNKNOWN", "P", 4),
    "SKGS-FA-ICP": ("SGS Saskatchewan - fire assay with ICP finish (Au, Pt, Pd)", "FA-ICPMS", "T", 1),
    "SKGS-NAPEROX": ("SGS Saskatchewan - sodium peroxide fusion", "NAPEROX-ICPOES", "T", 1),
    "SKGS-LOI": ("SGS Saskatchewan - loss on ignition", "NONE-GRAV", "T", 1),
    "SKGS-UNK": ("SGS Saskatchewan - other or unstated method", "UNKNOWN-UNKNOWN", "P", 9),
    "SKGS-NGR-AAS": ("GSC National Geochemical Reconnaissance lake sediment - standard NGR methods (mostly aqua regia AAS; U by DNC, F by ISE, Hg cold vapour)", "UNKNOWN-UNKNOWN", "P", 3),
    "SKGS-NGR-INAA": ("GSC National Geochemical Reconnaissance lake sediment - neutron activation (INAA)", "NONE-INAA", "T", 2),
    "SKGS-LAKE-1970S": ("SGS / GSC 1970s lake-sediment survey - technique as recorded per sample (mostly aqua regia AAS; U by neutron activation)", "UNKNOWN-UNKNOWN", "P", 5),
}
# GSC NGR columns: (analyte, unit, package)
NGR = {"AG": ("Ag", "ppm", "SKGS-NGR-AAS"), "AS_": ("As", "ppm", "SKGS-NGR-AAS"), "AU": ("Au", "ppb", "SKGS-NGR-AAS"), "BA": ("Ba", "ppm", "SKGS-NGR-AAS"),
       "CD": ("Cd", "ppm", "SKGS-NGR-AAS"), "CO": ("Co", "ppm", "SKGS-NGR-AAS"), "CU": ("Cu", "ppm", "SKGS-NGR-AAS"), "F": ("F", "ppm", "SKGS-NGR-AAS"),
       "FE": ("Fe", "%", "SKGS-NGR-AAS"), "HG": ("Hg", "ppb", "SKGS-NGR-AAS"), "LOI": ("LOI", "%", "SKGS-NGR-AAS"), "MN": ("Mn", "ppm", "SKGS-NGR-AAS"),
       "MO": ("Mo", "ppm", "SKGS-NGR-AAS"), "NI": ("Ni", "ppm", "SKGS-NGR-AAS"), "PB": ("Pb", "ppm", "SKGS-NGR-AAS"), "SB": ("Sb", "ppm", "SKGS-NGR-AAS"),
       "SN": ("Sn", "ppm", "SKGS-NGR-AAS"), "U": ("U", "ppm", "SKGS-NGR-AAS"), "V": ("V", "ppm", "SKGS-NGR-AAS"), "W": ("W", "ppm", "SKGS-NGR-AAS"),
       "ZN": ("Zn", "ppm", "SKGS-NGR-AAS")}
for col, el, unit in [("AS_INA", "As", "ppm"), ("AU_INA", "Au", "ppb"), ("BA_INA", "Ba", "ppm"), ("BR_INA", "Br", "ppm"), ("CE_INA", "Ce", "ppm"),
                      ("C0_INA", "Co", "ppm"), ("CR_INA", "Cr", "ppm"), ("CS_INA", "Cs", "ppm"), ("EU_INA", "Eu", "ppm"), ("FE_INA", "Fe", "%"),
                      ("HF_INA", "Hf", "ppm"), ("LA_INA", "La", "ppm"), ("LU_INA", "Lu", "ppm"), ("MO_INA", "Mo", "ppm"), ("NA_INA", "Na", "%"),
                      ("NI_INA", "Ni", "ppm"), ("RB_INA", "Rb", "ppm"), ("SB_INA", "Sb", "ppm"), ("SC_INA", "Sc", "ppm"), ("SM_INA", "Sm", "ppm"),
                      ("TA_INA", "Ta", "ppm"), ("TB_INA", "Tb", "ppm"), ("TH_INA", "Th", "ppm"), ("U_INA", "U", "ppm"), ("W_INA", "W", "ppm"),
                      ("YB_INA", "Yb", "ppm")]:
    NGR[col] = (el, unit, "SKGS-NGR-INAA")
LAKE70_SKIP = {"PH", "COND_MICROSEIMENS", "LAKE_DEPTH", "PH1", "COND_MICROSIEMENS_CM", "EH_MV", "O2_PPM", "CO3_PPM", "HCO3_PPM", "SO4_PPM", "PO4_PPM",
               "NO3_PPM", "ORG_C_PPM", "AS_HYD_PPM", "SB_HYD_PPM", "SE_HYD_PPM"}


def fix(code):
    return OXIDE_FIX.get(code, code)


samples, results = [], []   # samples: key, stype, stype_local, lat, lon, date, field, number, comments, fraction
stats = collections.Counter()


def add(key, pkg, code, unit, raw, lab=None, cert=None, meth=None, digest=None, fraction=None, comment=None):
    x = num(raw)
    if x is None or x == 0: stats["not analysed (0 / blank / *)"] += 1; return
    if x < 0: q, val, ldl = "<", -x, -x; stats["below detection"] += 1
    else: q, val, ldl = None, x, None
    results.append([key, pkg, code, unit, q, val, ldl, lab, cert, meth, digest, fraction, comment]); stats["values"] += 1


# till
seen = set()
for r in rows("till"):
    frac = re.sub(r"\s*till geochemistry\s*", "", r["TYPE_OF_ANALYSIS"]).replace("\ufffd", "µ").strip() or None
    sid = r["SAMPLE_NUMBER_ID"].strip()
    key = f"TILL:{sid}|{frac or ''}"
    if key not in seen:
        seen.add(key)
        note = "; ".join(x for x in [r["SAMPLE_DESCRIPTION"].strip(), f"location {r['LOCATION'].strip()}" if r["LOCATION"].strip() else "",
                                     f"collected by {r['COLLECTED_BY'].strip()}" if r["COLLECTED_BY"].strip() else "",
                                     f"{r['COMPANY_NAME'].strip()}: {r['PROJECT_NAME'].strip()}".strip(": "), r["REFERENCE"].strip() or r["REPORT"].strip()] if x)
        samples.append([key, "TILL_SAMPLE", f"SGS: till ({r['SAMPLE_TYPE'].strip()}) | {frac or 'fraction not stated'}", num(r["lat_wgs84"]),
                        num(r["lon_wgs84"]), epoch(r["DATE_SAMPLE_COLLECTED"]), sid, f"{sid} ({frac})" if frac else sid, note])
    pkg = till_package(r["DIGESTION"], r["DIGESTION_METHOD"], r["ANALYTICAL_METHOD"])
    meth = r["ANALYTICAL_METHOD"].strip() or None
    digest = "; ".join(x for x in [r["DIGESTION"].strip(), r["DIGESTION_METHOD"].strip()] if x) or None
    for k, v in r.items():
        if k == "FE2O3_TOT_PCT": code, unit = "FETO3", "%"
        elif k in TILL_SKIP or not re.fullmatch(r"[A-Z0-9]+_(PPM|PCT|PPB)", k): continue
        else: code, unit = analyte(k)
        add(key, pkg, fix(code), unit, v, r["ANALYSIS_LAB"].strip() or None, r["ANALYSIS_LAB_CERTIFICATE_NUM"].strip() or None, meth, digest, frac,
            f"lab code {r['ANALYSIS_LAB_CODE'].strip()}" if r["ANALYSIS_LAB_CODE"].strip() else None)
log("till samples", sum(1 for s in samples if s[0].startswith("TILL:")))

# GSC NGR lake sediment
for r in rows("lake_sediment_gsc"):
    key = f"NGR:{r['UNIQ_ID'].strip()}"
    note = "; ".join(x for x in [f"GSC Open File {r['GSC_OF'].strip()}", f"NTS {r['NTS_SHT'].strip()}", f"lake area {r['LK_AREA'].strip()}" if r["LK_AREA"].strip() else "",
                                 f"lake depth {r['LK_DEPTH'].strip()} m" if r["LK_DEPTH"].strip() else "", f"contamination {r['CONTAM'].strip()}" if r["CONTAM"].strip() else "",
                                 f"sediment colour {r['SED_COLO'].strip()}" if r["SED_COLO"].strip() else "", "field duplicate" if r["REP_STA"].strip() not in ("", "0") else ""] if x)
    samples.append([key, "SED_LAKE", "GSC NGR: lake sediment", num(r["lat_wgs84"]), num(r["lon_wgs84"]), None, r["SMPL_NU"].strip(), r["UNIQ_ID"].strip(), note])
    for col, (el, unit, pkg) in NGR.items():
        add(key, pkg, el, unit, r[col], comment="Au reanalysed" if col == "AU" and r["AU_R"].strip() not in ("", "*") else None)
log("NGR samples", sum(1 for s in samples if s[0].startswith("NGR:")))

# 1970s SGS / GSC lake sediment
for r in rows("lake_sediment_sgs"):
    sno = (r["SAMPLE_NO"] or "").replace(".0", "").strip() or r["OBJECTID"]
    key = f"LAKE70:{r['OBJECTID']}"
    yr = num(r["YR"])
    samples.append([key, "SED_LAKE", "SGS/GSC 1970s uranium-era survey: lake sediment", num(r["lat_wgs84"]), num(r["lon_wgs84"]),
                    f"{1900 + int(yr)}-01-01" if yr and yr < 100 else None, sno, sno,
                    "; ".join(x for x in [f"NTS {r['NTS'].strip()}", f"underlying rock {r['ROCK'].strip()}" if r["ROCK"].strip() else "",
                                          f"table {r['TABLE_'].strip()}", "year only" if yr else ""] if x)])
    tech = r["TECHNIQUE"].strip() or None
    for k, v in r.items():
        if k in LAKE70_SKIP or not k.endswith("_PPM"): continue
        code, unit = analyte(k)
        add(key, "SKGS-LAKE-1970S", fix(code), unit, v, meth=tech)
    add(key, "SKGS-LAKE-1970S", "LOI", "%", r["LOI_PERC"], meth=tech)
log("1970s lake samples", sum(1 for s in samples if s[0].startswith("LAKE70:")), "| results", dict(stats))

DRILL = {'"diamond" (hydraulic rotary)': "DIAMOND", "reverse circulation (RC)": "RC", '"diamond" (hydraulic rotary), reverse circulation (RC)': "DIAMOND",
         "sonic (vibratory)": "SONIC", "power auger": "AUGER", "rotary air blast (RAB)": "RAB", "air rotary (e.g. Bazooka)": "ROTARY",
         "direct push technology (DPT)": "PUSH_TUBE"}
collars, gos_n = [], collections.Counter()
for r in rows("drillholes"):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", r["DATE_DRILLED"] or "")
    depths = "; ".join(f"{lab} {r[col]} m" for lab, col in [("base of Quaternary at", "BASE_OF_QUATERNARY_DEPTH_M"), ("base of Phanerozoic at", "BASE_OF_PHANEROZOIC_DEPTH_M"),
                                                            ("base of Athabasca Group at", "BASE_OF_ATHABASCA_SG_DEPTH_M"), ("top of crystalline basement at", "TOP_CRYSTALLINE_BSMT_DEPTH_M")] if r[col].strip())
    note = "; ".join(x for x in [f"commodity of interest {r['COMMODITY_OF_INTEREST'].strip()}" if r["COMMODITY_OF_INTEREST"].strip() else "", depths,
                                 f"source {r['SOURCE'].strip()}" if r["SOURCE"].strip() else "", f"disposition {r['DISPOSITION'].strip()}" if r["DISPOSITION"].strip() else "",
                                 f"core size {r['DH_CORE_SIZE'].strip()}" if r["DH_CORE_SIZE"].strip() else "",
                                 f"core library interval {r['CORE_LIBRARY_M'].strip()} m" if r["CORE_LIBRARY_M"].strip() else "",
                                 "wedge hole" if r["WEDGE_HOLE"].strip() == "Yes" else ""] if x)
    dt = r["DRILL_TYPE"].strip()
    gos = r["GOS_UNIQUE_DRILLHOLE_ID"].strip()
    gos_n[gos] += 1
    if gos_n[gos] > 1:   # 41 GOS ids are shared by 2-4 holes fanned from one collar (same position, different dip/azimuth)
        note = "; ".join(x for x in [note, f"shares GOS id {gos} with other holes from the same collar"] if x)
        gos = f"{gos}#{gos_n[gos]}"
    collars.append([gos, r["DRILLHOLE_NAME"].strip() or r["GOS_UNIQUE_DRILLHOLE_ID"].strip(), r["PROJECT_OR_PROPERTY_NAME"].strip() or None,
                    r["COMPANY"].strip() or None, DRILL.get(dt, "UNKNOWN"), dt or None, m.group(1) if m else None, num(r["TOTAL_DH_LENGTH_M"]),
                    num(r["DH_AZIMUTH"]), num(r["DH_INCLINATION"]), num(r["ORIGINAL_COLLAR_ELEVATION_M"]) or num(r["ELEV_CORRECTED_1ARCSEC_DEM_M"]),
                    num(r["lat_wgs84"]), num(r["lon_wgs84"]), num(r["EASTING_UTM"]), num(r["NORTHING_UTM"]),
                    {"Yes": True, "No": False}.get(r["UNDERGROUND_HOLE"].strip()), r["COREAVAILABILITY"].strip() or None,
                    "; ".join(x for x in [r["STORAGE_LOCATIONS"].strip(), r["CORESTORAGEDETAILS"].strip()] if x) or None, note or None])
log("collars", len(collars))

# ---------------------------------------------------------------- gold load
# partitions are created first in their own short transaction: CREATE ... PARTITION OF takes an exclusive lock on the parent table, which would
# otherwise block the live app's reads for the whole load. Empty partitions are harmless (a dry run leaves them in place).
p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
p0.autocommit = True
p0.cursor().execute("SET lock_timeout = '20s'")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_canada_sk_sgs PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_canada_sk_sgs PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
p0.close()
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); w = csv.writer(buf)
    for r in data:
        w.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_collar", """gid text, name text, project text, company text, dtype text, dtype_local text, ddate date, eoh numeric, az numeric, dip numeric, z numeric,
  lat double precision, lon double precision, x numeric, y numeric, ug boolean, core_status text, core_store text, note text""", collars)
copy("st_sample", "k text, stype text, stype_local text, lat double precision, lon double precision, sdate date, field_no text, sample_no text, comments text", samples)
copy("st_result", """k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, lab text, cert text, meth text, digest text, fraction text,
  comment text""", results)
log("staged: collars", len(collars), "samples", len(samples), "results", len(results))

c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for code, (name, mcode, basis, prio) in PACKAGES.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "Saskatchewan Geological Survey GeoAtlas geochemistry (labs vary; the lab is on each result where recorded)", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'P', 5, 'placeholder; see source_package_rules' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (code,))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "SGS method mapping " + TAG, code))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL"),
                   ("drill type", "SELECT DISTINCT s.dtype FROM st_collar s LEFT JOIN geochem.drill_types t ON t.drill_type_code = s.dtype WHERE t.drill_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)

c.execute(f"""
INSERT INTO drilling.drillholes (source_system, source_hole_id, hole_name, prospect, company, drill_type_id, drill_type_local, date_drilled, total_depth_m,
  azimuth_deg, dip_deg, collar_elevation_m, lat, lon, geom, geog, original_x, original_y, original_crs, collared_underground, core_status, core_store_location,
  comments, is_active, created_by, created_date)
SELECT '{SRC}', s.gid, s.name, s.project, s.company, t.drill_type_id, s.dtype_local, s.ddate, CASE WHEN s.eoh > 0 THEN s.eoh END,
  CASE WHEN s.az BETWEEN 0 AND 360 THEN s.az END, CASE WHEN s.dip BETWEEN -90 AND 90 THEN s.dip END, s.z, s.lat, s.lon,
  ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography, s.x, s.y, 'NAD83 / UTM zone 13N (as published)',
  s.ug, s.core_status, s.core_store, s.note, true, '{TAG}', now()
FROM st_collar s JOIN geochem.drill_types t ON t.drill_type_code = s.dtype WHERE s.lat IS NOT NULL AND s.lon IS NOT NULL""")
log("drillholes", c.rowcount)
c.execute(f"""INSERT INTO drilling.surveys (drillhole_id, depth_m, azimuth_deg, dip_deg, survey_method, created_by, created_date)
              SELECT drillhole_id, 0, azimuth_deg, dip_deg, 'collar (published inclination/azimuth)', '{TAG}', now() FROM drilling.drillholes
              WHERE source_system = '{SRC}' AND (azimuth_deg IS NOT NULL OR dip_deg IS NOT NULL)""")
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'DRILLHOLE', drillhole_id, '{XID}', 'GOS:' || source_hole_id, '{TAG}', now() FROM drilling.drillholes WHERE source_system = '{SRC}'""")

# sample ids drawn from the table's identity sequence (no temporary column on the live table)
c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE s.lat IS NOT NULL AND s.lon IS NOT NULL AND EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
c.execute("CREATE UNIQUE INDEX ON st_map (k)")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, sample_date, comments, is_active,
  created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, 'SURFACE', s.sdate, s.comments,
  true, '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m ON m.k = s.k JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol, unit_id, unit_code,
  qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name, value, lower_detection_limit, upper_detection_limit, report_number,
  date_analysed, reviewed, is_active, created_by, created_date, source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  r.lab, meth.method_code, coalesce(r.meth, p.package_name), r.digest, r.val, r.ldl, NULL, r.cert, NULL, false, true, '{TAG}', now(),
  'SGS:' || m.sample_id || ':' || r.pkg || ':' || r.analyte, r.fraction, r.comment
FROM st_result r JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
log("results", c.rowcount, "of", len(results))
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system, CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END, r.qualifier_code IS NULL
FROM geochem.analytical_results r WHERE r.source_system = '{SRC}'""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_sask_sgs_20261103', now(), now(), count(*), 'rule-based classification at load (negative = below detection)'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))

c.execute(f"""SELECT p.package_code, count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id)
              WHERE r.source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC"""); log("per package", c.fetchall())
c.execute(f"""SELECT result_status, count(*) FROM geochem.result_classifications WHERE source_system = '{SRC}' GROUP BY 1"""); log("classification", c.fetchall())
c.execute(f"""SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}' AND (lat NOT BETWEEN 48.9 AND 60.1 OR lon NOT BETWEEN -110.1 AND -101.3)""")
log("samples outside Saskatchewan box", c.fetchone()[0])
c.execute(f"""SELECT count(*) FROM drilling.drillholes WHERE source_system = '{SRC}' AND (lat NOT BETWEEN 48.9 AND 60.1 OR lon NOT BETWEEN -110.1 AND -101.3)""")
log("collars outside Saskatchewan box", c.fetchone()[0])
c.execute(f"SELECT analyte_name, count(*) FROM geochem.analytical_results WHERE source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC LIMIT 12"); log("top analytes", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
