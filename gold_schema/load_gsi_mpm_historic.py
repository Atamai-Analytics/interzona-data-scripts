"""GSI Mineral Prospectivity Mapping (MPM) project - historic soil geochemistry, NW Midlands Ireland -> interzona_cm gold.
New source IRELAND_GSI_MPM_HISTORIC (own partition; rollback = delete by created_by = TAG).
Licence: CC BY 4.0 (GSI_Licence_CC_BY_40.txt in the download + ISO metadata). Attribution: "Contains Irish Public Sector Data (Geological Survey
Ireland) licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence."
Files: D:/CriticalMineralsDB/Ireland/MPM_Project_Historic_Soil_Geochemistry_Excel_Files.zip (user download), extracted to
D:/CriticalMineralsDB/Ireland/MPM_Historic_Soils. GSI metadata (MPM_Project_Historic_Soils_All_CuPbZn_Merged_Metadata.pdf, Feb 2022).

The merged Cu-Pb-Zn layer (353,967 points) = the three compilations below, which are loaded instead (more elements and provenance):
  GSI   GSI_Historic_Soils_Compilation_MPM_Project   138,957 points digitised by GSI from 276 scanned company survey maps (GOLDMINE Open File),
        1960s-2000s; Cu/Pb/Zn (+ occasional Ag, Ba, Mn); raster -> licensee, period, GOLDMINE URL, report lab/method where known.
  VEIL  VEIL_ShSo1_ShSo2_GSI_MPM_Project             152,669 shallow-soil points digitised for Vedanta Exploration Ireland (1965-1995 surveys);
        Cu/Pb/Zn (+ occasional Hg ppb, F); company, year, county, map, lab where recorded.
  GSRO  GSRO_Compliation_GSI_MPM_Project             62,886 rows submitted to the Geoscience Regulation Office by licensees (2009-2016 reports):
        'NEW DATA' multi-element lab results (ICP aqua regia or not stated) and 'LEGACY DATA' re-digitised historic Cu/Pb/Zn; 545 rows are
        pXRF-only (not in the merged layer). GSI: "no guarantees of data quality ... treated with caution".
Value conventions (GSI Notes sheets): -999 = below the lower limit of detection (limit kept only where the original text survives, e.g. '<10');
  '<x' text -> BELOW_DL_QUALIFIED with dl x; '>x' -> ABOVE_UDL; -1 = illegible and <Null> = no data (skipped); 0 skipped (not a value);
  GSRO small negative lab values (e.g. -0.002) are the lab's '<|x|' convention -> BELOW_DL_QUALIFIED with dl |x|.
Not loaded: VEIL check re-assays (140 rows) and second-depth samples (78), GSRO pH and sample weight.
Usage: python load_gsi_mpm_historic.py [--check]
"""
import os, re, sys, io, csv, time, collections
import openpyxl, psycopg2
from pyproj import Transformer

CHECK = "--check" in sys.argv
TAG = "migration_gsi_mpm_historic_20261115"
SRC, PART, XID = "IRELAND_GSI_MPM_HISTORIC", "ireland_gsi_mpm_historic", "GSI_MPM_SAMPLE_ID"
D = "D:/CriticalMineralsDB/Ireland/MPM_Historic_Soils/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


# code -> (name, method_code, lab_code, basis, priority, description)
PKGS = {
    "MPM_GSI_HIST": ("GSI MPM historic soils - digitised company survey maps (GSI compilation)", "UNKNOWN-UNKNOWN", "UNK", "P", 1,
                     "Cu, Pb, Zn (occasionally Ag, Ba, Mn) digitised by GSI from scanned 1960s-2000s exploration-company soil survey maps (GOLDMINE Open File); "
                     "laboratory and method mostly not recorded (where recorded: AAS or spectrographic, nitric-perchloric digestion, -80 mesh)"),
    "MPM_VEIL_HIST": ("GSI MPM historic soils - digitised company survey maps (Vedanta VEIL compilation)", "UNKNOWN-UNKNOWN", "UNK", "P", 1,
                      "Cu, Pb, Zn (occasionally Hg, F) digitised for Vedanta Exploration Ireland Ltd from scanned 1965-1995 company shallow-soil maps; "
                      "laboratory recorded for some maps (IBM Lab, Metals & Chemicals Cork, Robertson Research), method mostly not recorded"),
    "MPM_GSRO_LEGACY": ("GSI MPM historic soils - legacy Cu/Pb/Zn submitted to GSRO", "UNKNOWN-UNKNOWN", "UNK", "P", 2,
                        "Historic Cu, Pb, Zn re-digitised by licensees and submitted to the Geoscience Regulation Office; little provenance - treat with caution"),
    "MPM_GSRO_LAB": ("GSI MPM soils - licensee multi-element lab results submitted to GSRO", "UNKNOWN-UNKNOWN", "UNK", "P", 1,
                     "Multi-element soil results reported by licensees (2009-2016 reports) to the Geoscience Regulation Office; ICP aqua regia or method not stated"),
    "MPM_GSRO_PXRF": ("GSI MPM soils - licensee portable XRF results submitted to GSRO", "NONE-EDXRF", "UNK", "T", 3,
                      "Portable XRF readings reported by licensees to the Geoscience Regulation Office (units ppm as reported)"),
    "MPM_GSRO_LOI": ("GSI MPM soils - loss on ignition submitted to GSRO", None, "UNK", "T", 5, "Loss on ignition reported by licensees to the GSRO"),
}

tr = Transformer.from_crs(2157, 4326, always_xy=True)
stats = collections.Counter()
samples, results = {}, []
NUM = (int, float)


def rows_of(path, sheet):
    wb = openpyxl.load_workbook(D + path, read_only=True, data_only=True)
    it = wb[sheet].iter_rows(values_only=True)
    h = [str(x).strip() if x is not None else "" for x in next(it)]
    for r in it:
        if any(x is not None for x in r):
            yield dict(zip(h, r))


def blank(v):
    return v is None or (isinstance(v, str) and v.strip() in ("", "<Null>", "n/a"))


def parse(v, gsro_lab=False):
    """-> (status, value, dl, ul, qualifier) or None (skip)"""
    if blank(v): return None
    if isinstance(v, str):
        s = v.strip().replace(" ", "")
        m = re.match(r"^([<>])(\d+(?:\.\d+)?)$", s)
        if m:
            x = float(m.group(2))
            return ("B", x, x, None, "<") if m.group(1) == "<" else ("A", x, None, x, ">")
        try: v = float(s)
        except ValueError:
            stats["unparsed text " + s] += 1; return None
    v = float(v)
    if v == -999: return ("N", None, None, None, "ND")
    if v == -1: stats["illegible (-1)"] += 1; return None
    if v == 0: stats["zero skipped"] += 1; return None
    if v < 0:
        if gsro_lab and v > -1: return ("B", -v, -v, None, "<")
        stats["other negative " + str(v)] += 1; return None
    return ("D", v, None, None, None)


def add_sample(k, stype, local, e, n, field, comments, d_from=None, d_to=None):
    lon, lat = tr.transform(float(e), float(n))
    assert 52.9 < lat < 54.6 and -9.8 < lon < -6.8, (k, lat, lon)
    if k in samples:
        stats["duplicate key"] += 1; k = k + "#2"
    samples[k] = [k, stype, local, lat, lon, field, field, comments[:1000], "SURFACE", d_from, d_to]
    stats["samples " + k.split(":")[0]] += 1
    return k


def add_result(k, pkg, el, unit, parsed, comment=None):
    st, v, dl, ul, q = parsed
    results.append([k, pkg, el, unit, v, dl, ul, q, comment, st])
    stats[f"results {pkg} {st}"] += 1


def num(v):
    return float(v) if isinstance(v, NUM) else None


def depth_m(v):
    x = num(v)
    return x if x and x > 0 else None


# ---------------- GSI compilation
G = "GSI_Historic_Soils_Compilation_MPM_Project.xlsx"
raster = {r["Raster_ID"]: r for r in rows_of(G, "GSI_MPM_Project_Raster_List")}
report = collections.defaultdict(list)
for r in rows_of(G, "GSI_MPM_Project_Report_List"):
    report[r["Raster_ID"]].append(r)
for r in rows_of(G, "GSI_Hist_Soils_Comp_MPM_Project"):
    rid = r["Raster Unique ID"]; ra = raster.get(rid, {})
    dtype = str(ra.get("Data_Type") or "SS").strip()
    stype, local = ("SOIL_MAUG", "Historic deep overburden soil (power auger)") if dtype == "DOB" else (
        "SOIL_SAMPLE", "Historic shallow soil survey" + (" (infill)" if "Infill" in dtype else ""))
    rep = [x for x in report.get(rid, []) if not blank(x.get("Lab")) or not blank(x.get("Analysis Code")) or not blank(x.get("Analysis Method"))]
    lab = "; ".join(sorted({" ".join(str(x[c]).strip() for c in ("Lab", "Analysis Code", "Analysis Method", "Detection Limit (Cu, Pb, Zn)")
                                     if not blank(x.get(c)) and c in x) for x in rep}))
    cm = r.get("Comments")
    note = "; ".join(str(x) for x in [
        "GSI MPM historic soils, NW Midlands (GSI compilation, digitised from a company survey map)",
        f"licensee {ra.get('LICENSEE')}" if not blank(ra.get("LICENSEE")) else "",
        f"period {ra.get('PERIOD')}" if not blank(ra.get("PERIOD")) else "",
        f"map {rid}: {ra.get('DESCRIPTION')}" if not blank(ra.get("DESCRIPTION")) else f"map {rid}",
        f"lab/method: {lab}" if lab else "",
        f"note: {cm.strip()}" if isinstance(cm, str) and cm.strip() else "",
        f"GOLDMINE {ra.get('Raster_URL')}" if not blank(ra.get("Raster_URL")) else ""] if x)
    dep = depth_m(r.get("Depth (m)"))
    k = add_sample("GSI:" + str(r["GSI_Sample_ID"]), stype, local, r["Easting (ITM)"], r["Northing (ITM)"], str(r["GSI_Sample_ID"]), note, dep, dep)
    for col, el in (("Cu (ppm) Original", "Cu"), ("Pb (ppm) Original", "Pb"), ("Zn (ppm) Original", "Zn"),
                    ("Ag (ppm)", "Ag"), ("Ba (ppm)", "Ba"), ("Mn (ppm)", "Mn")):
        p = parse(r.get(col))
        if p: add_result(k, "MPM_GSI_HIST", el, "ppm", p)
log("GSI done", dict(stats))

# ---------------- VEIL compilation
V = "VEIL_ShSo1_ShSo2_GSI_MPM_Project.xlsx"
for r in rows_of(V, "VEIL_ShSo1_ShSo2_GSI_MPM"):
    st_raw = str(r.get("Sample Type") or "").strip()
    local = {"Base of Peat Soil": "Historic soil at base of peat", "Shallow Soils and Sub-Peat Drift": "Historic shallow soil / sub-peat drift",
             "Shallow Soils & DOB": "Historic shallow soil and deep overburden"}.get(st_raw, "Historic shallow soil survey")
    cm = r.get("Comment")
    note = "; ".join(str(x) for x in [
        "GSI MPM historic soils, NW Midlands (Vedanta VEIL compilation, digitised from a company survey map)",
        f"company {r.get('Company')}" if not blank(r.get("Company")) else "", f"year {r.get('Year')}" if not blank(r.get("Year")) else "",
        f"county {str(r.get('County')).title()}" if not blank(r.get("County")) else "",
        f"area {str(r.get('Area')).strip()}" if not blank(r.get("Area")) else "",
        f"map {r.get('Map_Name')} ({str(r.get('Scale')).strip()})" if not blank(r.get("Map_Name")) else "",
        f"analysed by {r.get('Analysed By')}" if not blank(r.get("Analysed By")) else "",
        f"analysis {r.get('Analysis Type')}" if not blank(r.get("Analysis Type")) else "",
        f"note: {cm.strip()}" if isinstance(cm, str) and cm.strip() else ""] if x)
    dep = depth_m(r.get("Depth (m)"))
    k = add_sample("VEIL:" + str(r["Sample_ID"]), "SOIL_SAMPLE", local, r["Easting (ITM)"], r["Northing (ITM)"], str(r["Sample_ID"]), note, dep, dep)
    hg_note = "source comment 'Hg in ppb?': unit uncertain in the original map" if isinstance(cm, str) and "Hg in ppb?" in cm else None
    for col, el, u in (("Cu (ppm)", "Cu", "ppm"), ("Pb (ppm)", "Pb", "ppm"), ("Zn (ppm)", "Zn", "ppm"), ("Hg (ppb)", "Hg", "ppb"), ("F (ppm)", "F", "ppm")):
        p = parse(r.get(col))
        if p: add_result(k, "MPM_VEIL_HIST", el, u, p, hg_note if el == "Hg" else None)
    if not blank(r.get("Cu (ppm) Check")): stats["VEIL check re-assays not loaded"] += 1
    if not blank(r.get("Cu (ppm) Sample_2")) or not blank(r.get("Pb (ppm) Sample_2")): stats["VEIL second-depth samples not loaded"] += 1
log("VEIL done", dict(stats))

# ---------------- GSRO compilation
R = "GSRO_Compliation_GSI_MPM_Project.xlsx"
sid = lambda v: str(int(v)) if isinstance(v, float) and v == int(v) else str(v).strip()
meta = {}
for r in rows_of(R, "GSRO_Comp_GSI_MPM_Dataset_List"):
    key = sid(r["Sample_ID"])
    assert key not in meta, ("duplicate GSRO list id", key)
    meta[key] = r
EL = re.compile(r"^([A-Z][a-z]?)_(ppm|pct)$")
for r in rows_of(R, "GSRO_Comp_GSI_MPM_Project"):
    s = sid(r["Sample ID"]); m = meta[s]
    lab_cols = [(c, EL.match(c).group(1), "%" if c.endswith("pct") else "ppm") for c in r if EL.match(c) and not c.startswith(("Cu_", "Pb_", "Zn_"))]
    has_lab = any(not blank(r[c]) and r[c] != 0 for c, _, _ in lab_cols)
    legacy = str(m.get("Historical_Compilation")).startswith("LEGACY")
    fmt = lambda d: d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
    hz = m.get("Soil_Sample_Horizon")
    note = "; ".join(str(x) for x in [
        "GSI MPM soils, NW Midlands (GSRO compilation: " + ("legacy historic data re-submitted by a licensee" if legacy else "new survey data reported by a licensee") + ")",
        f"licensee {m.get('Licensee_Name')}", f"reported by {m.get('Reported_By')}" if not blank(m.get("Reported_By")) else "",
        f"PL {r.get('PL')}", f"report period {fmt(m.get('Report_Period_From'))} to {fmt(m.get('Report_Period_To'))}" if not blank(m.get("Report_Period_From")) else "",
        f"dataset {m.get('Original_Dataset')}", f"original source {m.get('Compilation_Source')}" if not blank(m.get("Compilation_Source")) else "",
        f"horizon {hz}" if not blank(hz) else "", f"description {m.get('Sample_Description')}" if not blank(m.get("Sample_Description")) else "",
        "lab certificate supplied" if m.get("Lab_Certificate_PDF") == "YES" else ""] if x)
    d_from, d_to = num(m.get("Depth_From")), num(m.get("Depth_To"))
    if d_from is None and d_to is None:
        d_to = depth_m(m.get("Sample_Depth")); d_from = d_to
    hz_s = str(hz or "").upper()
    stype = "SOIL_A" if hz_s in ("AH", "OH") else "SOIL_B" if hz_s in ("B", "HORIZON B") else "SOIL_SAMPLE"
    k = add_sample("GSRO:" + s, stype, "Licensee soil survey" if not legacy else "Historic soil survey (licensee re-submission)",
                   r["Easting (ITM)"], r["Northing (ITM)"], s, note, d_from, d_to)
    cpz_pkg = "MPM_GSRO_LAB" if has_lab or not legacy else "MPM_GSRO_LEGACY"
    for col, el in (("Cu (ppm)", "Cu"), ("Pb (ppm)", "Pb"), ("Zn (ppm)", "Zn")):
        p = parse(r.get(col), gsro_lab=True)
        if p: add_result(k, cpz_pkg, el, "ppm", p)
    for c, el, u in lab_cols:
        p = parse(r.get(c), gsro_lab=True)
        if p: add_result(k, "MPM_GSRO_LAB", el, u, p)
    p = parse(r.get("LOI_pct"))
    if p: add_result(k, "MPM_GSRO_LOI", "LOI", "%", p)
    for c in r:
        if c.startswith("pXRF "):
            p = parse(r.get(c))
            if p: add_result(k, "MPM_GSRO_PXRF", c.split()[1], "ppm", p)
log("GSRO done", dict(stats))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor()
c.execute("SELECT analyte_code FROM geochem.analytes")
known = {a for (a,) in c.fetchall()}
miss = sorted({r[2] for r in results} - known)
assert not miss, ("unknown analytes", miss)
log("staged samples", len(samples), "results", len(results))
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, SRC + " already has samples: delete them by created_by first"
if not CHECK:
    g.commit(); g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0")

for pk, (name, mcode, lab, basis, prio, desc) in PKGS.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = %s),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""", (pk, name, lab, mcode, desc, TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'GSI MPM historic soils' FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""", (basis, prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "GSI MPM historic soils " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"DROP TABLE IF EXISTS {table}")
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql})")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, d_from numeric, d_to numeric",
     samples.values())
copy("st_result", "k text, pkg text, analyte text, unit text, val numeric, dl numeric, ul numeric, q text, comment text, st text", results)
for label, sql in [("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("qualifier", "SELECT DISTINCT r.q FROM st_result r LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.q WHERE r.q IS NOT NULL AND q.qualifier_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); m = [r[0] for r in c.fetchall()]
    assert not m, (label, m)
c.execute("DROP TABLE IF EXISTS st_map")
c.execute("""CREATE TEMP TABLE st_map AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments, depth_from_m, depth_to_m,
  is_active, created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, s.d_from, s.d_to,
  true, '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount, "| without results", len(samples) - c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
c.execute("SELECT pkg, st, count(*) FROM st_result GROUP BY 1, 2 ORDER BY 1, 2"); log("per package/status", c.fetchall())
if CHECK:
    g.rollback(); g.close(); log("CHECK RUN - rolled back", dict(stats)); sys.exit(0)

c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, r.q,
  'Not recorded (historic exploration-company or licensee data compiled by GSI)', meth.method_code, p.package_name, meth.digest_name,
  r.val, r.dl, r.ul, NULL, NULL, false, true, '{TAG}', now(), r.st, NULL, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.q
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id""")
nins = c.rowcount
log("results inserted", nins, "of", len(results))
assert nins == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE r.source_result_id WHEN 'B' THEN 'BELOW_DL_QUALIFIED' WHEN 'N' THEN 'BELOW_DL_QUALIFIED' WHEN 'A' THEN 'ABOVE_UDL' ELSE 'DETECTED' END,
  r.lower_detection_limit,
  CASE r.source_result_id WHEN 'B' THEN 'QUALIFIER_LDL' WHEN 'N' THEN 'SOURCE_LLD_CODE_NO_LIMIT' END,
  r.source_result_id = 'D'
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute(f"UPDATE geochem.analytical_results_{PART} SET source_result_id = NULL")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, %s)
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""",
          (SRC, "rule_" + TAG, nins, "'<x' and GSRO negative lab values -> BELOW_DL_QUALIFIED (dl x); -999 -> BELOW_DL_QUALIFIED qualifier ND, no limit; '>x' -> ABOVE_UDL"))

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "Geological Survey Ireland (GSI) - Mineral Prospectivity Mapping (MPM) project",
           "Historic soil geochemistry, NW Midlands Ireland (MPM project, 2022): GSI, Vedanta (VEIL) and GSRO compilations of digitised company soil surveys "
           "(Cu, Pb, Zn and occasional Ag, Ba, Mn, Hg, F) plus licensee multi-element and portable XRF soil results",
           "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/",
           "Contains Irish Public Sector Data (Geological Survey Ireland) licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence.",
           "Cleared: GSI_Licence_CC_BY_40.txt shipped in the MPM download and the dataset ISO metadata (CC BY 4.0, specific attribution statement, no limitations "
           "to public access). Values originate from exploration-company surveys released through the GSI Open File / GSRO system. Checked 2026-11-15.",
           "Historic data digitised from scanned company maps (1960s-2016): laboratory, method and detection limits mostly not recorded; values of different "
           "companies and eras are not levelled - use for anomaly patterns within a survey rather than absolute comparison. -999 (below detection, limit "
           "unknown) loaded as ND with no limit; '<x' as below-limit; illegible (-1) and zero values skipped. GSRO submissions have little provenance "
           "(GSI: treat with caution). Hg in some VEIL maps flagged 'Hg in ppb?'. No per-sample dates (period, year or report period in the comments). "
           "VEIL check re-assays and second-depth samples, GSRO pH not loaded.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\GSI_MPM_HISTORIC\ (licence text, metadata PDF, EVIDENCE.md)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG, dict(stats))
g.close()
