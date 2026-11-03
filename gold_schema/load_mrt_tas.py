"""Mineral Resources Tasmania bulk data package BDR2023_01 (open-file TIGER Drilling + Samples & Observations, to 15 Feb 2023; CC BY 3.0 AU)
-> interzona_cm gold: drilling.drillholes / drilling.surveys + geochem samples, results and classifications (source AUSTRALIA_TAS_MRT).

Input: the package workbooks converted to CSV (one file per sheet) in <package>/csv.
What is loaded
  - every collar (34,871) and directional survey; drill type mapped to geochem.drill_types (full MRT text kept in drill_type_local)
  - only samples that have chemistry; drill samples -> sample_context DRILLHOLE_INTERVAL + drillhole_id + depths, surface -> SURFACE
  - chemistry methods only (XRD, heavy-mineral counts, Davis tube, microprobe, laser-ablation and IR spot/mineral data are left out)
  - panned-concentrate analyses (treatment 'Panned Concentrate') are concentrate assays: the sample is typed SED_HMC, or, when the same MRT
    sample also has bulk analyses, the concentrate results go to a separate child sample (sample_number '... (panned concentrate)')
Values
  - MRT: 0 = below detection (with the detection limit); negative values are also below detection (value = -DL or -<limit>), except LOI
  - '<' rows: value = detection limit, lower_detection_limit = DL, qualifier '<' (same convention as the other sources)
  - units: ppm, %, wt% (-> %), ppb; troy oz per long ton -> ppm (x 30.6122); 'number' and unit-less values are left out
Packages: one MRT-* package per method (and digestion where stated); basis (total/partial) and priority set in geochem.source_package_rules.
Usage: python load_mrt_tas.py [--dry]    (--dry = load + verify, then ROLLBACK)
"""
import os, sys, io, csv, time, re, collections
import psycopg2
from lith_map_mrt import map_lithology

csv.field_size_limit(10 ** 9)
DRY = "--dry" in sys.argv
TAG = "migration_mrt_tas_20261102"
SRC = "AUSTRALIA_TAS_MRT"
XID = "MRT_TIGER"
PKG_DIR = "D:/CriticalMineralsDB/Tasmania/MRT_BulkData_BDR2023_01/csv"
HERE = os.path.dirname(os.path.abspath(__file__))

ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rows(name):
    r = csv.reader(open(os.path.join(PKG_DIR, name), encoding="utf-8", newline=""))
    h = next(r)
    for row in r:
        yield dict(zip(h, row))


def num(s):
    s = (s or "").strip()
    if not s: return None
    try: return float(s)
    except ValueError:
        m = re.match(r"^\s*([0-9]*\.?[0-9]+)", s)
        return float(m.group(1)) if m else None


def date(s):
    s = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m and m.group(1) > "1800" else None


N = "\\N"


def out(v):
    return N if v is None or v == "" else v


# ---------------------------------------------------------------- dictionaries
DRILL = {"diamond": "DIAMOND", "augers": "AUGER", "hollow flight auger": "AUGER", "percussion": "PERCUSSION", "cable tool": "PERCUSSION",
         "reverse circulation": "RC", "aircore": "AIRCORE", "rotary": "ROTARY", "pit": "PIT", "percussion_diamond": "PERCUSSION_DIAMOND",
         "reverse circulation_diamond": "PERCUSSION_DIAMOND", "rotary_diamond": "ROTARY_DIAMOND", "rotary_percussion": "ROTARY_PERCUSSION",
         "push tube": "PUSH_TUBE"}


def drill_type(s):
    parts = [p.strip().lower() for p in (s or "").split(",") if p.strip()]
    codes = [DRILL.get(p, "UNKNOWN") for p in parts]
    if not codes: return "UNKNOWN"
    if "DIAMOND" in codes: return "DIAMOND"
    for cd in codes:
        if cd != "UNKNOWN": return cd
    return "UNKNOWN"


DRILL_SAMPLE_TYPE = {"DIAMOND": "CORE_SAMPLE", "PERCUSSION_DIAMOND": "CORE_SAMPLE", "ROTARY_DIAMOND": "CORE_SAMPLE", "PUSH_TUBE": "CORE_SAMPLE",
                     "RC": "CHIPS_RC", "PERCUSSION": "CHIPS_PERCUSSION", "ROTARY_PERCUSSION": "CHIPS_PERCUSSION", "ROTARY": "CHIPS_ROTARY",
                     "AUGER": "CHIPS_AUGER", "AIRCORE": "CORE_AIRCORE", "PIT": "TRENCH_SAMPLE"}


def sample_type(grp, mrt_type, site, dtype):
    t = mrt_type.lower()
    if grp == "DH":
        if t in ("soil",): return "SOIL_AUG"
        if t in ("sediment", "stream sediment"): return "SEDIMENT_SAMPLE"
        if t.startswith("tailings"): return "TAILINGS_GENERAL"
        if t == "concentrate": return "SED_HMC"
        return DRILL_SAMPLE_TYPE.get(dtype, "DRILL_SAMPLE")
    if t == "stream sediment": return "SED_STREAM"
    if t == "soil": return "SOIL_SAMPLE"
    if t == "sediment": return "SEDIMENT_SAMPLE"
    if t.startswith("tailings"): return "TAILINGS_GENERAL"
    if t == "concentrate": return "SED_HMC"
    if t == "mineralised": return "ROCK_SELECT"
    if t == "rock":
        s = site.lower()
        return "ROCK_OUTCROP" if s == "outcrop" else "ROCK_FLOAT" if s == "float" else "ROCK_SAMPLE"
    return "SAMPLE_UNKNOWN"


# package code -> (name, method_code, basis, priority)
PACKAGES = {
    "MRT-XRF": ("MRT - XRF (whole rock / pressed pellet / fused bead)", "NONE-XRF", "T", 3),
    "MRT-PXRF": ("MRT - portable XRF (Niton)", "NONE-XRF", "T", 8),
    "MRT-HCL-XRF": ("MRT - hot/cold HCl leach with XRF", "UNKNOWN-UNKNOWN", "P", 6),
    "MRT-FA": ("MRT - fire assay (Au, Ag, PGE)", "FA-AAS", "T", 2),
    "MRT-AAS": ("MRT - AAS, digestion not stated or acid digestion", "UNKNOWN-UNKNOWN", "P", 4),
    "MRT-AAS-AR": ("MRT - aqua regia with AAS", "UNKNOWN-UNKNOWN", "P", 4),
    "MRT-ES": ("MRT - emission spectroscopy, digestion not stated", "UNKNOWN-UNKNOWN", "P", 5),
    "MRT-ES-ACID": ("MRT - acid digestion with ICP emission spectroscopy", "UNKNOWN-UNKNOWN", "P", 2),
    "MRT-ES-AR": ("MRT - aqua regia with ICP emission spectroscopy", "AR-ICPOES", "P", 2),
    "MRT-ES-MX": ("MRT - multi-acid digestion with ICP emission spectroscopy", "MX-ICPOES", "P", 2),
    "MRT-ES-CAUSTIC": ("MRT - caustic leach with emission spectroscopy", "UNKNOWN-UNKNOWN", "P", 6),
    "MRT-ICPMS": ("MRT - ICP-MS, digestion not stated or acid digestion", "UNKNOWN-UNKNOWN", "P", 1),
    "MRT-ICPMS-AR": ("MRT - aqua regia with ICP-MS", "AR-ICPMS", "P", 1),
    "MRT-ICPMS-MX": ("MRT - multi-acid digestion with ICP-MS", "MX-ICPMS", "P", 1),
    "MRT-INAA": ("MRT - neutron activation analysis", "NONE-INAA", "T", 2),
    "MRT-LECO": ("MRT - LECO combustion (C, S)", "NONE-LECO", "T", 1),
    "MRT-CS": ("MRT - carbon/sulphur analyser", "NONE-LECO", "T", 2),
    "MRT-CNONCARB": ("Non-Carbonate carbon - MRT", "NONE-LECO", "T", 1),
    "MRT-GFAAS": ("MRT - graphite furnace AAS", "UNKNOWN-UNKNOWN", "P", 3),
    "MRT-AFS": ("MRT - atomic fluorescence spectroscopy", "UNKNOWN-UNKNOWN", "P", 3),
    "MRT-COLOR": ("MRT - colorimetry", "NONE-COLORIMETRY", "P", 6),
    "MRT-ISE": ("MRT - specific ion electrode", "UNKNOWN-UNKNOWN", "T", 5),
    "MRT-IC": ("MRT - ion exchange chromatography", "UNKNOWN-UNKNOWN", "P", 6),
    "MRT-WETCHEM": ("MRT - classical wet chemical rock analysis", "NONE-GRAV", "T", 4),
    "MRT-TGA": ("MRT - thermogravimetric (LOI, H2O)", "NONE-TGA", "T", 5),
    "MRT-BCL": ("MRT - bulk cyanide leach", "CN-AAS", "P", 7),
    "MRT-COLDEXT-AAS": ("MRT - cold extraction with AAS", "UNKNOWN-UNKNOWN", "P", 7),
    "MRT-OTHER": ("MRT - other method", "UNKNOWN-UNKNOWN", "P", 9),
    "MRT-UNK": ("MRT - method not recorded", "UNKNOWN-UNKNOWN", "P", 9),
}
SKIP_METHODS = ("XRD", "Heavy Mineral", "Davis Tube", "Electron Microprobe", "Laser Ablation", "IR Spectroscopy")


def package(meth, treat):
    m, t = meth.lower(), treat.lower()
    if m == "xrf": return "MRT-XRF"
    if m == "niton xrf": return "MRT-PXRF"
    if m in ("hot hcl-xrf", "cold hcl-xrf"): return "MRT-HCL-XRF"
    if m == "fire assay" or (m.startswith("aas") and "fire assay" in t): return "MRT-FA"
    if m.startswith("aas"): return "MRT-AAS-AR" if "aqua regia" in t else "MRT-AAS"
    if m == "emission spectroscopy":
        if "aqua regia" in t: return "MRT-ES-AR"
        if "multi-acid" in t or "four acid" in t or "4 acid" in t: return "MRT-ES-MX"
        if "caustic" in t: return "MRT-ES-CAUSTIC"
        if "acid" in t: return "MRT-ES-ACID"
        return "MRT-ES"
    if m == "icpms analysis":
        if "aqua regia" in t: return "MRT-ICPMS-AR"
        if "multi-acid" in t or "four acid" in t or "4 acid" in t: return "MRT-ICPMS-MX"
        return "MRT-ICPMS"
    return {"neutron activation analysis": "MRT-INAA", "leco": "MRT-LECO", "carbon sulphur analysis": "MRT-CS", "graphite furnace aas": "MRT-GFAAS",
            "atomic fluorescence spectroscopy": "MRT-AFS", "colorimetry": "MRT-COLOR", "specific ion electrode": "MRT-ISE",
            "ion exchange chromatography": "MRT-IC", "rock analyses - wet chemistry": "MRT-WETCHEM", "thermogravimetric": "MRT-TGA",
            "bulk cyanide leach": "MRT-BCL", "cold extraction followed by aa": "MRT-COLDEXT-AAS", "other": "MRT-OTHER"}.get(m, "MRT-UNK")


ANALYTE = {"Fe2O3TOT": "FETO3", "H2O+": "H2O", "H2O-": "Moisture", "TOTAL": "Sum", "C NonCarb": "C"}
SKIP_FIELDS = {"206Pb", "207Pb", "208Pb", "Al2O3Avl", "C Graphitic", "Fe2O3+Al2O3", "FeOTOT", "FeS2", "Insol", "RxSiO2", "SO2",
               "SulphateasSO3", "SulphideasSO3", "WO", "pH"}
NEG_OK = {"LOI", "Sum"}
UNIT = {"parts per million (ppm)": ("ppm", 1.0), "percent (%)": ("%", 1.0), "weight percent (wt %)": ("%", 1.0),
        "parts per billion (ppb)": ("ppb", 1.0), "troy ounces per long ton": ("ppm", 30.6122)}
FRACTION_RE = re.compile(r"(?i)(?:[-+]\d+(?:[-+]\d+)?\s*#|sieve\s*[-+]?\d+\s*micron|[-+]\d+\s*micron|panned concentrate|size fraction|crushed sample|pulp)")
META = {"Sample Status", "ID *", "Analysis Type", "Linked To Table *", "Linked To ID *", "Analysis Date", "Submitted Date", "Processed Mediums", "Treatments",
        "Treatment Comments", "Laboratory", "Lab Job No.", "User Analysis No", "Lab Analysis No.", "Repeat No.", "Analysis Comments", "Add Comment",
        "RM8 References", "Types", "Reg No.", "Field No.", "Raw X", "Raw Y", "Raw Datum", "Longitude (GDA94)", "Latitude (GDA94)", "mE (MGA94/Z55)",
        "mN (MGA94/Z55)", "X/Y Accuracy", "Height", "Height Accuracy", "Analysis Method", ""}

# ---------------------------------------------------------------- read the package
holes = {}
for d in rows("drilling__DH_DRILLHOLE.csv"):
    holes[d["Drill ID"]] = {"date": date(d["Date Drilled"])}
collars = []
for d in rows("drilling__CollarExport.csv"):
    did = d["Drill ID"]
    dt = drill_type(d["Drill Types"])
    holes.setdefault(did, {})["dtype"] = dt
    wedge = d["Wedge Parent Hole ID"].strip()
    collars.append([did, d["Name"].strip(), d["Keywords"].strip(), d["Company"].strip(), d["Associated Tenement"].strip(), dt, d["Drill Types"].strip(),
                    d["Purpose"].strip(), d["Driller Category"].strip(), holes.get(did, {}).get("date"), num(d["EOH Length"]),
                    num(d["Azimuth"]), num(d["Dip"]), num(d["Z"]), num(d["X"]), num(d["Y"]), num(d["Positional Accuracy"]),
                    d["Position Method"].strip(), num(d["Elevation Accuracy"]), d["Elevation Method"].strip(),
                    {"yes": True, "true": True, "no": False, "false": False}.get(d["Collared Underground"].strip().lower()),
                    wedge if wedge and wedge != did else None, num(d["Wedge Downhole Depth"]), d["Core Status"].strip(), d["Core Store Location"].strip()])
log("collars", len(collars))
surveys = []
az_ref = {"True": "TRUE", "MAGNETIC": "MAGNETIC", "UNK": None, "": None}
for d in rows("drilling__DHSurvey.csv"):
    dep = num(d["DEPTH"])
    if dep is None or dep < 0: continue
    az = num(d["AZIMUTH"]); dip = num(d["DIP"])
    if az is not None and not 0 <= az <= 360: az = None
    if dip is not None and not -90 <= dip <= 90: dip = None
    surveys.append([d["Drill_ID"], dep, az, dip, az_ref.get(d["AZIMUTH_DATUM"], None)])
log("surveys", len(surveys))

samples = {}
for grp, f in (("DH", "drillhole__SamplesObservations__DH.csv"), ("SURF", "surface__SamplesObservations_surface.csv")):
    for d in rows(f):
        samples[d["ID *"]] = (grp, d)
log("sample records", len(samples))

stats = collections.Counter()
res_path = os.path.join(HERE, "_mrt_results.csv")
has_bulk, has_conc = set(), set()
with open(res_path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    for f in sorted(os.listdir(PKG_DIR)):
        if not f.endswith("__Results.csv"): continue
        meth = f.split("__")[1]
        if meth.startswith(SKIP_METHODS):
            stats["skipped method files"] += 1; continue
        for d in rows(f):
            sid = d["Linked To ID *"]
            if sid not in samples:
                stats["analysis with unknown sample"] += 1; continue
            treat = d.get("Treatments", "")
            conc = "panned concentrate" in treat.lower()
            medium = d.get("Processed Mediums", "").strip()
            meth_name = meth + (f" / {medium}" if medium else "")
            digest = "; ".join(x for x in [treat.strip(), d.get("Treatment Comments", "").strip()] if x) or None
            fraction = "; ".join(FRACTION_RE.findall(treat) + ([medium] if medium else [])) or None
            a_comment = d.get("Analysis Comments", "").strip()
            repeat = d.get("Repeat No.", "").strip()
            pkg = package(meth, treat)
            lab = d.get("Laboratory", "").strip().strip("-").strip() or None
            job = d.get("Lab Job No.", "").strip() or None
            adate = date(d.get("Analysis Date", ""))
            n_vals = 0
            for k, v in d.items():
                if k in META or k is None or k.endswith((" Unit", " Detection Limit", " Comments")) or v == "": continue
                x = num(v)
                if x is None: stats["non-numeric"] += 1; continue
                if k in SKIP_FIELDS: stats["field left out: " + k] += 1; continue
                code = ANALYTE.get(k, k)
                urow = d.get(k + " Unit", "").strip()
                if urow not in UNIT: stats["unit left out: " + (urow or "(none)")] += 1; continue
                unit, fac = UNIT[urow]
                dl = num(d.get(k + " Detection Limit", ""))
                if dl is not None and dl <= 0: dl = None
                if x == 0 or (x < 0 and code not in NEG_OK):
                    lim = dl if dl is not None else (abs(x) if x < 0 else None)
                    q, val, ldl = "<", (lim * fac if lim is not None else None), (lim * fac if lim is not None else None)
                    stats["below detection"] += 1
                else:
                    q, val, ldl = None, x * fac, (dl * fac if dl is not None else None)
                p = "MRT-CNONCARB" if k == "C NonCarb" else pkg
                comment = "; ".join(x for x in [d.get(k + " Comments", "").strip(), f"analysis: {a_comment}" if a_comment else "",
                                                 f"repeat {repeat}" if repeat else "", f"MRT field {k}" if k != code else ""] if x) or None
                w.writerow([d["ID *"], sid, "C" if conc else "B", p, code, unit, out(q), out(val), out(ldl), out(lab), out(job), out(adate),
                            meth_name, out(digest), out(fraction), out(comment)])
                n_vals += 1; stats["values"] += 1
            if n_vals:
                (has_conc if conc else has_bulk).add(sid)
log("results staged to csv", dict(stats))

# sample rows: one per (MRT sample, part) where part B = bulk, C = panned concentrate (C only when the sample also has bulk results)
srows = []
for sid in sorted(has_bulk | has_conc, key=int):
    grp, d = samples[sid]
    did = d["Drill ID"].strip() if grp == "DH" else ""
    dtype = holes.get(did, {}).get("dtype", "UNKNOWN") if did else None
    st = sample_type(grp, d["Types *"], d["Site Type"], dtype)
    parts = []
    if sid in has_bulk: parts.append(("B", st))
    if sid in has_conc: parts.append(("C", "SED_HMC"))
    lat, lon = num(d["Latitude (GDA94)"]), num(d["Longitude (GDA94)"])
    comments = "; ".join(x for x in [d["Sample Description"].strip(), ("Locality: " + d["Locality"].strip()) if d["Locality"].strip() else "",
                                      ("Originators: " + d["Originators"].strip()) if d["Originators"].strip() else "",
                                      ("References: " + d["References"].strip()) if d["References"].strip() else ""] if x)
    for part, stc in parts:
        num_ = d["Reg. #"].strip() or d["Field #"].strip() or ("MRT " + sid)
        if part == "C" and sid in has_bulk: num_ += " (panned concentrate)"
        srows.append([sid, part, grp, stc, f"MRT: {d['Types *']} | {d['Site Type']}".strip(" |"),
                      "DRILLHOLE_INTERVAL" if grp == "DH" else "SURFACE", lat, lon, num(d["Height"]), date(d["Collection Date"]),
                      d["Field #"].strip(), num_, "MRT " + sid, did or None,
                      num(d["Depth From"]) if grp == "DH" else None, num(d["Depth To"]) if grp == "DH" else None, comments,
                      d["Lithology"].strip(), d["Lithostratigraphy"].strip(), d["Chronostratigraphy"].strip()])
log("samples to load", len(srows), "| MRT samples", len(has_bulk | has_conc), "| concentrate-only", len(has_conc - has_bulk),
    "| concentrate split off", len(has_conc & has_bulk), "| no coordinates", sum(1 for r in srows if r[6] is None))

# ---------------------------------------------------------------- gold load
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


copy("st_collar", """did text, name text, prospect text, company text, tenement text, dtype text, dtype_local text, purpose text, driller text, ddate date,
  eoh numeric, az numeric, dip numeric, z numeric, x numeric, y numeric, pacc numeric, pmeth text, eacc numeric, emeth text, underground boolean,
  parent text, wedge_depth numeric, core_status text, core_store text""", collars)
copy("st_survey", "did text, depth numeric, az numeric, dip numeric, azref text", surveys)
copy("st_sample", """sid text, part text, grp text, stype text, stype_local text, ctx text, lat double precision, lon double precision, height numeric,
  sdate date, field_no text, sample_no text, sample_alt text, did text, dfrom numeric, dto numeric, comments text, lith text, lithostrat text, chronostrat text""", srows)
c.execute("""CREATE TEMP TABLE st_result (aid text, sid text, part text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric,
  lab text, job text, adate date, meth_name text, digest text, fraction text, comment text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); nres = c.fetchone()[0]
assert nres == stats["values"], (nres, stats["values"])
log("staged: collars", len(collars), "surveys", len(surveys), "samples", len(srows), "results", nres)

# packages + per-source rules
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for code, (name, mcode, basis, prio) in PACKAGES.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "Mineral Resources Tasmania bulk data package BDR2023_01 analysis group (labs vary; the lab is on each result)", TAG))
c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
             SELECT package_id, 'P', 5, 'placeholder; see source_package_rules' FROM geochem.analytical_packages WHERE package_code LIKE 'MRT-%' ON CONFLICT DO NOTHING""")
for code, (name, mcode, basis, prio) in PACKAGES.items():
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "MRT method/treatment mapping " + TAG, code))

# ZnO is reported by MRT but missing from the analyte dictionary (oxide, like PbO / NiO)
c.execute("""INSERT INTO geochem.analytes (analyte_code, analyte_name, element_symbol, atomic_number, element_group, is_element, is_oxide, typical_reporting_unit,
  is_critical_mineral, critical_mineral_category, geochemical_group, typical_crustal_abundance, typical_crustal_abundance_unit, typical_mineral_hosts,
  plausible_max_value, plausible_max_unit, plausible_max_notes, pct_reporting_valid, analysis_group, is_active, created_by, created_date)
  SELECT 'ZnO', 'ZnO', 'Zn', 30, 'Transition metals', false, true, '%%', true, 'Base metals', 'Chalcophile elements', 70, 'ppm', 'Zincite (rare); Zn mostly in sphalerite',
         100, '%%', 'Zn fraction in ZnO = 80.3%%; sphalerite 67.1%% Zn -> 83.5%% ZnO; zincite = 100%% ZnO', true, 'Oxide', true, %s, now()
  WHERE NOT EXISTS (SELECT 1 FROM geochem.analytes WHERE analyte_code = 'ZnO')""", (TAG,))

# dictionary completeness: nothing may drop silently
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL"),
                   ("drill type", "SELECT DISTINCT s.dtype FROM st_collar s LEFT JOIN geochem.drill_types t ON t.drill_type_code = s.dtype WHERE t.drill_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)

# drill holes + surveys
c.execute(f"""
INSERT INTO drilling.drillholes (source_system, source_hole_id, hole_name, prospect, company, tenement, drill_type_id, drill_type_local, purpose, driller_category,
  date_drilled, total_depth_m, azimuth_deg, dip_deg, collar_elevation_m, elevation_datum, lat, lon, geom, geog, original_x, original_y, original_crs,
  position_accuracy_m, position_method, elevation_accuracy_m, elevation_method, collared_underground, wedge_depth_m, core_status, core_store_location,
  is_active, created_by, created_date)
SELECT '{SRC}', s.did, s.name, nullif(s.prospect, ''), nullif(s.company, ''), nullif(s.tenement, ''), t.drill_type_id, nullif(s.dtype_local, ''), nullif(s.purpose, ''),
  nullif(s.driller, ''), s.ddate, s.eoh, CASE WHEN s.az BETWEEN 0 AND 360 THEN s.az END, CASE WHEN s.dip BETWEEN -90 AND 90 THEN s.dip END, s.z,
  CASE WHEN s.z IS NOT NULL THEN 'AHD (TAS83)' END,
  ST_Y(p.pt), ST_X(p.pt), p.pt, p.pt::geography, s.x, s.y, 'GDA94 / MGA zone 55 (EPSG:28355)',
  s.pacc, nullif(s.pmeth, ''), s.eacc, nullif(s.emeth, ''), s.underground, s.wedge_depth, nullif(s.core_status, ''), nullif(s.core_store, ''),
  true, '{TAG}', now()
FROM st_collar s JOIN geochem.drill_types t ON t.drill_type_code = s.dtype
LEFT JOIN LATERAL (SELECT CASE WHEN s.x IS NOT NULL AND s.y IS NOT NULL THEN ST_SetSRID(ST_Transform(ST_SetSRID(ST_MakePoint(s.x, s.y), 28355), 4283), 4326) END AS pt) p ON true""")
log("drillholes", c.rowcount)
c.execute(f"""UPDATE drilling.drillholes h SET parent_drillhole_id = p.drillhole_id FROM st_collar s JOIN drilling.drillholes p ON p.source_system = '{SRC}' AND p.source_hole_id = s.parent
              WHERE h.source_system = '{SRC}' AND h.source_hole_id = s.did AND s.parent IS NOT NULL""")
log("wedge parents linked", c.rowcount)
c.execute(f"""INSERT INTO drilling.surveys (drillhole_id, depth_m, azimuth_deg, dip_deg, azimuth_reference, created_by, created_date)
              SELECT h.drillhole_id, s.depth, s.az, s.dip, s.azref, '{TAG}', now() FROM st_survey s
              JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.did""")
log("surveys", c.rowcount, "of", len(surveys))
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'DRILLHOLE', drillhole_id, '{XID}', source_hole_id, '{TAG}', now() FROM drilling.drillholes WHERE source_system = '{SRC}'""")

# partitions
c.execute(f"CREATE TABLE geochem.analytical_results_australia_tas_mrt PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
c.execute(f"CREATE TABLE geochem.result_classifications_australia_tas_mrt PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")

# samples
c.execute("ALTER TABLE geochem.samples ADD COLUMN _mrt_key text")
c.execute(f"""
INSERT INTO geochem.samples (geom, field_id, sample_number, sample_number_alt, sample_type_id, sample_type_local, sample_context, depth_from_m, depth_to_m,
  sample_date, elevation_m, comments, is_active, created_by, created_date, source_system, drillhole_id, _mrt_key)
SELECT coalesce(CASE WHEN s.lat IS NOT NULL AND s.lon IS NOT NULL THEN ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326) END, h.geom),
  nullif(s.field_no, ''), s.sample_no, s.sample_alt, t.sample_type_id, s.stype_local, s.ctx, s.dfrom, s.dto, s.sdate, s.height, nullif(s.comments, ''),
  true, '{TAG}', now(), '{SRC}', h.drillhole_id, s.sid || ':' || s.part
FROM st_sample s JOIN geochem.sample_types t ON t.sample_type_code = s.stype
LEFT JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.did
WHERE coalesce(CASE WHEN s.lat IS NOT NULL AND s.lon IS NOT NULL THEN ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326) END, h.geom) IS NOT NULL
ORDER BY s.sid::bigint, s.part""")
log("samples", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', CASE WHEN sample_number LIKE '% (panned concentrate)' THEN split_part(_mrt_key, ':', 1) || ':CONC' ELSE split_part(_mrt_key, ':', 1) END,
                     '{TAG}', now() FROM geochem.samples WHERE source_system = '{SRC}'""")
c.execute(f"CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT _mrt_key AS k, sample_id FROM geochem.samples WHERE source_system = '{SRC}'")
c.execute("CREATE UNIQUE INDEX ON st_map (k)")
c.execute("DELETE FROM st_result r WHERE NOT EXISTS (SELECT 1 FROM st_map m WHERE m.k = r.sid || ':' || r.part)")
n_nogeo = c.rowcount; nres -= n_nogeo
c.execute("SELECT count(*) FROM st_sample s WHERE NOT EXISTS (SELECT 1 FROM st_map m WHERE m.k = s.sid || ':' || s.part)")
log("left out for lack of any location: samples", c.fetchone()[0], "results", n_nogeo)
c.execute("ALTER TABLE geochem.samples DROP COLUMN _mrt_key")
c.execute("SELECT count(*), count(lat), count(drillhole_id) FROM geochem.samples WHERE source_system = %s", (SRC,))
log("gold samples (total, with lat/lon, with drill hole)", c.fetchone())

# lithology observations: every drill-hole record with a lithology or stratigraphic unit (downhole logs as well as analysed samples, linked to
# the hole with depths and to the sample when it was loaded) plus the analysed surface samples. MRT text kept verbatim in lithology_local;
# lithology_id from lith_map_mrt (exact name, synonym, base name, keyword; UNKNOWN when nothing fits); how it matched is in comments.
c.execute("SELECT lower(lithology_name), lithology_code FROM geochem.lithology WHERE is_active ORDER BY lithology_id DESC")
by_name = dict(c.fetchall())
lith_rows, how_n = [], collections.Counter()
loaded_keys = set()
c.execute("SELECT k FROM st_map"); loaded_keys = {r[0] for r in c.fetchall()}
for sid, (grp, d) in samples.items():
    lith, ls, cs = d["Lithology"].strip(), d["Lithostratigraphy"].strip(), d["Chronostratigraphy"].strip()
    if not (lith or ls): continue
    key = f"{sid}:B" if f"{sid}:B" in loaded_keys else f"{sid}:C" if f"{sid}:C" in loaded_keys else None
    did = d["Drill ID"].strip() if grp == "DH" else ""
    if grp == "SURF" and key is None: continue          # surface observations with no analysed sample have nowhere to attach
    code, how = map_lithology(lith, by_name) if lith else (None, "none")
    how_n[how] += 1
    note = "; ".join(x for x in [f"Chronostratigraphy: {cs}" if cs else "", f"lithology matched by {how}" if lith else "",
                                 f"MRT record {sid} ({d['Types *']})"] if x)
    lith_rows.append([key, did or None, num(d["Depth From"]) if grp == "DH" else None, num(d["Depth To"]) if grp == "DH" else None,
                      code or "UNKNOWN", lith, ls, "DRILLHOLE_INTERVAL" if grp == "DH" else "SURFACE", note])
assert all(r[4] in set(by_name.values()) for r in lith_rows), "lithology code not in dictionary"
copy("st_lith", "k text, did text, dfrom numeric, dto numeric, code text, lith text, lithostrat text, ctx text, note text", lith_rows)
c.execute(f"""
INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sample_id, drillhole_id, depth_from_m, depth_to_m,
  strat_formation, comments, is_active, created_by, created_date)
SELECT l.lithology_id, nullif(s.lith, ''), s.ctx, m.sample_id, h.drillhole_id, s.dfrom, s.dto, nullif(s.lithostrat, ''), s.note, true, '{TAG}', now()
FROM st_lith s JOIN geochem.lithology l ON l.lithology_code = s.code
LEFT JOIN st_map m ON m.k = s.k
LEFT JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.did
WHERE m.sample_id IS NOT NULL OR h.drillhole_id IS NOT NULL""")
log("lithology obs", c.rowcount, "of", len(lith_rows), "| match:", dict(how_n))
c.execute(f"""SELECT count(*), count(drillhole_id), count(*) FILTER (WHERE drillhole_id IS NOT NULL AND sample_id IS NULL),
                     count(*) FILTER (WHERE lithology_id <> (SELECT lithology_id FROM geochem.lithology WHERE lithology_code = 'UNKNOWN'))
              FROM geochem.lithology_observations WHERE created_by = '{TAG}'""")
log("lithology obs (total, on a drill hole, log-only intervals, with a named lithology)", c.fetchone())

# interval QC (flags only): sample intervals and lithology-log intervals of each drill hole
QC = "drilling.interval_qc (drillhole_id, sample_id, lithology_observation_id, issue, detail, created_by)"
for label, src_sql, idcol in [
        ("sample", f"""SELECT s.drillhole_id, s.sample_id AS sid, NULL::bigint AS lid, s.depth_from_m AS f, s.depth_to_m AS t, h.total_depth_m AS eoh
                       FROM geochem.samples s JOIN drilling.drillholes h USING (drillhole_id)
                       WHERE s.source_system = '{SRC}' AND s.sample_number NOT LIKE '% (panned concentrate)'""", "sid"),
        ("lithology", f"""SELECT o.drillhole_id, o.sample_id AS sid, o.lithology_observation_id AS lid, o.depth_from_m AS f, o.depth_to_m AS t, h.total_depth_m AS eoh
                          FROM geochem.lithology_observations o JOIN drilling.drillholes h USING (drillhole_id) WHERE o.created_by = '{TAG}'""", "lid")]:
    c.execute(f"""INSERT INTO {QC}
      SELECT drillhole_id, CASE WHEN '{label}' = 'sample' THEN sid END, lid, issue, detail, '{TAG}' FROM (
        SELECT x.*, 'MISSING_DEPTH' AS issue, 'from or to depth not recorded' AS detail FROM ({src_sql}) x WHERE f IS NULL OR t IS NULL
        UNION ALL SELECT x.*, 'FROM_GT_TO', format('from %s m > to %s m', f, t) FROM ({src_sql}) x WHERE f > t
        UNION ALL SELECT x.*, 'ZERO_LENGTH', format('point sample at %s m (from = to)', f) FROM ({src_sql}) x WHERE f = t
        UNION ALL SELECT x.*, 'BEYOND_EOH', format('to %s m is past the end of hole %s m', t, eoh) FROM ({src_sql}) x WHERE eoh IS NOT NULL AND t > eoh + 0.5
      ) q""")
    log(f"interval QC {label}: basic flags", c.rowcount)
c.execute(f"""INSERT INTO {QC}
  SELECT drillhole_id, sample_id, NULL, 'OVERLAP', format('%s-%s m overlaps an earlier interval reaching %s m', depth_from_m, depth_to_m, prev_max), '{TAG}'
  FROM (SELECT s.drillhole_id, s.sample_id, s.depth_from_m, s.depth_to_m,
               max(s.depth_to_m) OVER (PARTITION BY s.drillhole_id ORDER BY s.depth_from_m, s.depth_to_m, s.sample_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max
        FROM geochem.samples s WHERE s.source_system = '{SRC}' AND s.drillhole_id IS NOT NULL AND s.depth_from_m IS NOT NULL AND s.depth_to_m IS NOT NULL
          AND s.sample_number NOT LIKE '% (panned concentrate)') x
  WHERE prev_max IS NOT NULL AND depth_from_m < prev_max - 0.001""")
log("interval QC sample overlaps", c.rowcount)
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
  r.lab, meth.method_code, r.meth_name, r.digest, r.val, r.ldl, NULL, r.job, r.adate, false, true, '{TAG}', now(),
  'MRT:' || r.aid, r.fraction, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.sid || ':' || r.part
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual
ORDER BY m.sample_id, r.aid""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results WHERE source_system = '{SRC}'"); ngr = c.fetchone()[0]
log("gold results", ngr, "in", round(time.time() - t0), "s")
assert ngr == nres, (ngr, nres)

c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END,
  CASE WHEN r.qualifier_code = '<' THEN CASE WHEN r.lower_detection_limit IS NOT NULL THEN 'QUALIFIER_LDL' ELSE 'QUALIFIER_VALUE' END END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results r WHERE r.source_system = '{SRC}'""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_mrt_20261102', now(), now(), count(*), 'rule-based classification at load (MRT 0 / negative = below detection)'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute(f"SELECT result_status, use_in_statistics, count(*) FROM geochem.result_classifications WHERE source_system = '{SRC}' GROUP BY 1,2 ORDER BY 3 DESC")
log("classification", c.fetchall())

# verification
c.execute(f"""SELECT p.package_code, count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p ON p.package_id = r.package_id
 WHERE r.source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC"""); log("per package", c.fetchall())
c.execute(f"""SELECT t.sample_type_code, s.sample_context, count(*) FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id)
 WHERE s.source_system = '{SRC}' GROUP BY 1,2 ORDER BY 3 DESC"""); log("sample types", c.fetchall())
c.execute(f"SELECT count(DISTINCT sample_id), count(DISTINCT analyte_id) FROM geochem.analytical_results WHERE source_system = '{SRC}'")
log("samples with results, analytes", c.fetchone())
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.source_system = '{SRC}' AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id)""")
log("samples without results (must be 0)", c.fetchone()[0])
c.execute(f"""SELECT count(*) FROM drilling.drillholes WHERE source_system = '{SRC}' AND (lat NOT BETWEEN -44.5 AND -39 OR lon NOT BETWEEN 143 AND 149.5)""")
log("collars outside Tasmania's box", c.fetchone()[0])
c.execute(f"""SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}' AND lat IS NOT NULL AND (lat NOT BETWEEN -44.5 AND -39 OR lon NOT BETWEEN 143 AND 149.5)""")
log("samples outside Tasmania's box", c.fetchone()[0])

if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
os.remove(res_path)
