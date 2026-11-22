"""Saudi Geological Survey (SGS) National Geological Database (NGD) regional stream-sediment geochemistry -> interzona_cm gold, new source
SAUDI_SGS_NGD (own partitions; rollback = python load_sgs_saudi_ngd.py --undo, i.e. delete by created_by = TAG).

Licence: SGS-NGD Statement Open License Agreement (shipped with every download: internal use; own products need SGS's advance permission) plus SGS's
written reply of 2026-11-15 (ngdwebmaster@sgs.gov.sa): no fees for using and uploading the NGD regional stream-sediment data into our commercial
application; SGS must be clearly credited as the source. A clarification on client-facing display was sent 2026-11-15 (no reply yet).
Evidence: D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\SGS_Saudi (EVIDENCE.md, licence PDF, reply .msg).

Input: D:/CriticalMineralsDB/Saudi Arabia/DS_SAMPLES_GM_0xxC - the ORIGINAL workbooks (not the _ForImport copies), Geochemical Atlas of the Kingdom
of Saudi Arabia (1:250,000 quadrangles, about 1 sample per 25 km2, 2-0.177 mm fraction milled to <100 um, SGS laboratories Jiddah):
  GM-048C Yanbu al Bahr (GAYQ)  640 samples, 68 analytes; header: methods by column (SiO2 colorimetric, other majors + Ag + Pb AAS, Au GFAAS, rest
                                ICP), units and detection-limit rows; year '2005' only; jobs CL1793/CL1797/CL1798/CL1799.
  GM-052C Al Madinah (GAMQ)     626 samples, 68 analytes; methods by column (majors incl. SiO2 + Ag + Pb AAS, Au GFAAS, rest ICP-OES Optima 4300 DV);
                                units row, no detection-limit row ('< x' values carry the limit); no date; job & sequence numbers CL0073-/CL0090-.
  GM-053C Wadi al 'Ays (GAAQ)   637 samples, 56 analytes (adds U; no B, In, Ir, Os, Pd, Pt, Rb, Re, Rh, Ru, Se, Te, Tl); detection-limit row,
                                no method row -> SGS survey metadata: ICP-OES for majors and traces, AAS for Ag, Pb, Au; 'Data Reported: 10/07/2010'.
Methods (SGS metadata PDF): 1 g, HF/HClO4/HCl/HNO3 digestion; LOI by furnace (metadata says 500 C; the 048C and 053C headers say 1000 C - the
survey header is recorded in the result comment). An HF digestion cannot retain Si, so SiO2 must come from a separate decomposition that SGS does
not describe; noted in the caveats.
Sample dates: none of the files gives a collection date (2005 = year in the 048C header, 10/07/2010 = report date) -> sample_date stays NULL and
the information is in comments. Units are loaded exactly as published (Te is ppm in 048C but ppb in 052C; Ru is ppm in both) - unit_screen.py
decides whether anything needs a source-backed fix.
'< x' -> qualifier '<', value = x, lower_detection_limit = x. Detected values carry the survey's published detection limit where it has a DL row.
Sample GAAQ 682 sits in the 048C shapefile but its assays are in the 053C workbook (loaded once, from 053C). The 23 non-stream observation points
in the shapefiles (chip / rock / sand) have no assays and are not loaded.
comments start 'SGS NGD survey <quadrangle> quadrangle' (the Geostatistics survey key).
Usage: python load_sgs_saudi_ngd.py [--check | --undo]
"""
import os, re, sys, io, csv, time, collections
import pandas as pd
import psycopg2

CHECK = "--check" in sys.argv
UNDO = "--undo" in sys.argv
TAG = "migration_sgs_saudi_ngd_20261122"
SRC = "SAUDI_SGS_NGD"
PART = "saudi_sgs_ngd"
XID = "SGS_NGD_SAMPLE_ID"
ROOT = "D:/CriticalMineralsDB/Saudi Arabia/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
LAB = "SGS-JEDDAH"
FRACTION = "2-0.177 mm (-10+80 mesh), milled to <100 um"
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


# package code -> (name, method_code, basis, priority, description)
PKGS = {
    "SGS-NGD-ICPOES": ("SGS NGD stream sediments - four-acid digestion / ICP-OES", "4A-ICPOES", "T", 2,
                       "Saudi Geological Survey laboratories, Jiddah: 1 g, HF/HClO4/HCl/HNO3 digestion, ICP-OES (Optima 4300 DV for Al Madinah); "
                       "trace elements in all surveys and major oxides of Wadi al 'Ays"),
    "SGS-NGD-AAS": ("SGS NGD stream sediments - AAS (Ag, Pb; majors of Yanbu and Al Madinah; Au of Wadi al 'Ays)", "4A-AAS", "T", 3,
                    "Saudi Geological Survey laboratories, Jiddah: atomic absorption spectrometry after HF/HClO4/HCl/HNO3 digestion (majors: "
                    "decomposition not described by SGS)"),
    "SGS-NGD-GFAAS": ("SGS NGD stream sediments - graphite furnace AAS (Au)", "4A-GFAAS", "T", 2,
                      "Saudi Geological Survey laboratories, Jiddah: Au by graphite furnace AAS (Yanbu, Al Madinah)"),
    "SGS-NGD-SIO2-COLOR": ("SGS NGD stream sediments - colorimetric SiO2 (Yanbu)", None, "T", 5,
                           "Saudi Geological Survey laboratories, Jiddah: SiO2 by colorimetry; decomposition not described"),
    "SGS-NGD-LOI": ("SGS NGD stream sediments - loss on ignition", "NONE-GRAV", "T", 5,
                    "Saudi Geological Survey laboratories, Jiddah: loss on ignition (temperature as given by each survey header)"),
}

# survey: file, quadrangle name, code, sample/lon/lat columns, element row, unit row, DL row, method row, date note, metadata
SURVEYS = [
    dict(gm="GM-048C", folder="DS_SAMPLES_GM_048C", file="GM-048C_GA-GAYQ Yanbu Database.xls", quad="Yanbu al Bahr", code="GAYQ",
         cid=1, clon=2, clat=3, cjob=None, erow=5, urow=6, dlrow=7, mrow=4,
         date_note="year 2005 given in the data header (collection date not given)", loi="LOI at 1000 C (survey header)",
         jobs="jobs CL1793, CL1797, CL1798, CL1799"),
    dict(gm="GM-052C", folder="DS_SAMPLES_GM_052C", file="GM-052C_GA-GAMQ Al Madinah Dataset.xls", quad="Al Madinah", code="GAMQ",
         cid=2, clon=3, clat=4, cjob=1, erow=5, urow=6, dlrow=None, mrow=4,
         date_note="no date given in the data file", loi="LOI temperature not given in the survey header (SGS metadata: 500 C)", jobs=""),
    dict(gm="GM-053C", folder="DS_SAMPLES_GM_053C", file="GM-053C_GA-GAAQ Wadi al Ays Dataset.xlsx", quad="Wadi al 'Ays", code="GAAQ",
         cid=0, clon=1, clat=2, cjob=None, erow=5, urow=7, dlrow=6, mrow=None,
         date_note="data reported 10/07/2010 (collection date not given)", loi="LOI at 1000 C (survey header)", jobs=""),
]
OXIDES = {"SiO2", "Al2O3", "Fe2O3", "CaO", "MgO", "Na2O", "K2O", "TiO2", "MnO", "P2O5", "SO3"}


def el_code(h):
    h = str(h).replace("\ufffd", "").strip()
    if h.upper().replace(".", "").startswith("LOI") or "LOI" in h:
        return "LOI"
    if h.startswith("SiO2"):
        return "SiO2"
    return h


def method_pkg(sv, el, meth):
    if el == "LOI":
        return "SGS-NGD-LOI"
    if meth is None:   # 053C: SGS survey metadata
        return "SGS-NGD-AAS" if el in ("Au", "Ag", "Pb") else "SGS-NGD-ICPOES"
    m = meth.upper()
    if m.startswith("CLOU") or m.startswith("COLO"):
        return "SGS-NGD-SIO2-COLOR"
    if m.startswith("GFAAS"):
        return "SGS-NGD-GFAAS"
    if m.startswith("AAS"):
        return "SGS-NGD-AAS"
    if m.startswith("ICP"):
        return "SGS-NGD-ICPOES"
    raise ValueError((sv["gm"], el, meth))


def num(x):
    try:
        v = float(str(x).replace(",", "").strip())
    except ValueError:
        return None
    return None if v != v else v   # empty header cells arrive as NaN


stats = collections.Counter()
samples, results = {}, []
odd = collections.Counter()
if not UNDO:
    for sv in SURVEYS:
        o = pd.read_excel(ROOT + sv["folder"] + "/" + sv["file"], header=None, dtype=object)
        ncol = o.shape[1]
        els, units, dls, meths = {}, {}, {}, {}
        cur = None
        for j in range(ncol):
            if sv["mrow"] is not None:
                mv = o.iat[sv["mrow"], j]
                if isinstance(mv, str) and mv.strip() and mv.strip() != "Method":
                    cur = mv.strip()
            e = o.iat[sv["erow"], j]
            if isinstance(e, str) and e.strip() and e.strip() not in ("Element", "Elements"):
                # Yanbu: the LOI unit cell is '%' with '1000 oC' in the column header row below
                els[j] = el_code(e); meths[j] = cur if sv["mrow"] is not None else None
                units[j] = str(o.iat[sv["urow"], j]).strip()
                if sv["dlrow"] is not None:
                    dls[j] = num(o.iat[sv["dlrow"], j])
        assert len(set(els.values())) == len(els), (sv["gm"], "duplicate analyte columns")
        for j in els:
            assert units[j] in ("%", "ppm", "ppb"), (sv["gm"], els[j], units[j])
            assert (els[j] in OXIDES or els[j] == "LOI") == (units[j] == "%"), (sv["gm"], els[j], units[j])
        stats[f"{sv['gm']} analytes"] = len(els)
        for i in range(o.shape[0]):
            sid = o.iat[i, sv["cid"]]
            if not isinstance(sid, str) or not re.match(r"^GA[A-Z]Q[ -]?\d+$", sid.strip()):
                continue
            sid = sid.strip()
            n = int(re.findall(r"\d+", sid)[0])
            key = f"{sv['code']}-{n:03d}"
            assert key not in samples, ("duplicate sample", key)
            lon, lat = float(o.iat[i, sv["clon"]]), float(o.iat[i, sv["clat"]])
            assert 16 < lat < 33 and 34 < lon < 56, (key, lat, lon)
            job = str(o.iat[i, sv["cjob"]]).strip() if sv["cjob"] is not None else ""
            note = "; ".join(x for x in [
                f"SGS NGD survey {sv['quad']} quadrangle ({sv['code']}, {sv['gm']})",
                "Geochemical Atlas of the Kingdom of Saudi Arabia, regional stream sediment, about 1 sample per 25 km2",
                sv["date_note"], f"job {job}" if job else sv["jobs"], f"fraction {FRACTION}"] if x)
            samples[key] = [key, "SED_STREAM", "SGS regional stream sediment (Geochemical Atlas)", lat, lon, sid, sid, note, "SURFACE", None]
            stats["samples " + sv["gm"]] += 1
            for j, el in els.items():
                v = o.iat[i, j]
                if v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip()):
                    stats["blank cell"] += 1; continue
                pkg = method_pkg(sv, el, meths[j])
                cmt = sv["loi"] if el == "LOI" else None
                if el == "SiO2" and pkg != "SGS-NGD-SIO2-COLOR":
                    cmt = "SiO2: decomposition not described by SGS (an HF digestion cannot retain Si)"
                if isinstance(v, str) and v.strip().startswith("<"):
                    x = num(v.strip()[1:])
                    if x is None or x <= 0:
                        odd[f"{sv['gm']} {el} {v!r}"] += 1; continue
                    results.append([key, pkg, el, units[j], "<", x, x, cmt, FRACTION]); stats["below detection"] += 1
                    continue
                x = num(v)
                if x is None:
                    odd[f"{sv['gm']} {el} {v!r}"] += 1; continue
                if x <= 0:
                    odd[f"{sv['gm']} {el} value<=0"] += 1; continue
                results.append([key, pkg, el, units[j], None, x, dls.get(j), cmt, FRACTION]); stats["detected"] += 1
    log("staged samples", len(samples), "results", len(results), dict(stats))
    if odd:
        log("NOT LOADED (unparsable / zero):", dict(odd))
    pk = collections.Counter((r[1], r[2]) for r in results)
    log("per package:", dict(collections.Counter(r[1] for r in results)))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor()
c.execute("SET statement_timeout = 0")

if UNDO:
    c.execute(f"DELETE FROM geochem.result_classifications WHERE source_system = '{SRC}'"); log("classifications", c.rowcount)
    c.execute(f"DELETE FROM geochem.analytical_results WHERE source_system = '{SRC}' AND created_by = '{TAG}'"); log("results", c.rowcount)
    c.execute(f"DELETE FROM geochem.sample_chemistry_wide WHERE source_system = '{SRC}'"); log("wide", c.rowcount)
    c.execute(f"DELETE FROM geochem.sample_occurrence_links l USING geochem.samples s WHERE s.sample_id = l.sample_id AND s.created_by = '{TAG}'"); log("links", c.rowcount)
    c.execute(f"DELETE FROM core.external_ids WHERE source_system = '{XID}' AND created_by = '{TAG}'"); log("external ids", c.rowcount)
    c.execute(f"DELETE FROM geochem.samples WHERE created_by = '{TAG}'"); log("samples", c.rowcount)
    c.execute(f"DELETE FROM geochem.source_package_rules WHERE source_system = '{SRC}'")
    c.execute(f"DELETE FROM geochem.package_wide_rules w USING geochem.analytical_packages p WHERE p.package_id = w.package_id AND p.created_by = '{TAG}'")
    c.execute(f"DELETE FROM geochem.analytical_packages WHERE created_by = '{TAG}'"); log("packages", c.rowcount)
    c.execute(f"DELETE FROM geochem.classification_batches WHERE source_system = '{SRC}'")
    c.execute(f"DELETE FROM core.data_sources WHERE source_system = '{SRC}' AND created_by = '{TAG}'"); log("data source", c.rowcount)
    g.commit(); log("UNDONE", TAG); sys.exit(0)

if not CHECK:
    g.commit()
    g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "source already has samples: run --undo first"
c.execute("SELECT lab_id FROM geochem.laboratories WHERE lab_code = %s", (LAB,))
assert c.fetchone(), "laboratory SGS-JEDDAH missing"
for code, (name, meth, basis, prio, desc) in PKGS.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = %s),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""", (code, name, LAB, meth, desc, TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'SGS NGD' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, code))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "SGS NGD method mapping " + TAG, code))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date",
     samples.values())
copy("st_result", "k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, comment text, fraction text", results)
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments, sample_date, is_active,
  created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, s.sdate, true,
  '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount, "| without results", len(samples) - c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
if CHECK:   # the partitions do not exist yet, so stop before the results
    c.execute("SELECT r.pkg, r.unit, count(*), count(*) FILTER (WHERE qual = '<') FROM st_result r GROUP BY 1, 2 ORDER BY 1, 2"); log("per package/unit", c.fetchall())
    g.rollback(); g.close(); log("CHECK RUN - rolled back"); sys.exit(0)
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  l.lab_name, meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(),
  NULL, r.fraction, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.laboratories l ON l.lab_id = p.lab_id
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
log("results inserted", nins, "of", len(results))
assert nins == len(results)

c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'rule-based classification at load (SGS ''< x'' = below detection limit x)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "Saudi Geological Survey (SGS) - National Geological Database (NGD)",
           "Geochemical Atlas of the Kingdom of Saudi Arabia: regional stream-sediment surveys GM-048C Yanbu al Bahr, GM-052C Al Madinah, GM-053C Wadi al 'Ays (NGD package 10/01/2022)",
           "SGS-NGD Statement Open License Agreement, with SGS written permission (2026-11-15) for use in our application: no fee, SGS credited as the source",
           "https://ngd.sgs.gov.sa/en/geochemical-surveys/",
           "Geochemical Atlas of the Kingdom of Saudi Arabia, regional stream-sediment data (National Geological Database) (c) Saudi Geological Survey 2022 - presented as modified (loaded into a database).",
           "Permission: SGS reply 2026-11-15 - no fees for using and uploading the NGD regional stream-sediment data into our commercial application; any use must clearly credit SGS. "
           "SGS's wording was 'the commercial application you use internally'; clarification on client-facing display sent 2026-11-15, awaiting reply. Do not redistribute the original files. Loaded 2026-11-22.",
           "Three 1:250,000 quadrangles of the Arabian Shield only (Madinah, Tabuk, Makkah regions). No collection dates (2005 = data year of Yanbu, 10/07/2010 = report date of Wadi al 'Ays). "
           "Four-acid ICP-OES / AAS; SiO2 decomposition not described (an HF digestion cannot retain Si); LOI temperature differs between the survey headers (1000 C) and the SGS metadata (500 C). "
           "Units as published (Te ppm in Yanbu but ppb in Al Madinah; Ru reported in ppm). Many PGE, Ir, Os, Rh, Re, Te, Tl, Se results are below detection.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\SGS_Saudi\ (EVIDENCE.md, licence PDF, SGS reply .msg)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG)
g.close()
