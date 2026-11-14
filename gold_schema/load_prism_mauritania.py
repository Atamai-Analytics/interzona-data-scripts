"""Mauritania PRISM-I/II geochemistry (USGS Open-File Report 2013-1280, chapter D; metadata Access_Constraints None, Use_Constraints:
acknowledgement of the USGS appreciated) -> interzona_cm gold, new source MAURITANIA_USGS_PRISM (own partitions, rollback = delete by
created_by = TAG). Evidence: D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\USGS_PRISM_MAURITANIA.

Input (downloaded 2026-11-14 with the user's approval) in D:/CriticalMineralsDB/Africa/Mauritania_PRISM2_20261114:
  MasterChem.mdb tblMasterChem - 30,718 samples (one row each), samples collected 1999-2004 by BGS / BRGM (PRISM-I, World Bank IDA-38100)
  and analysed mostly by ALS Chemex (four-acid ICP-MS / ICP-AES, fire assay Au/PGE, AAS, XRF majors); MasterLocations.mdb tblSample_Locs
  for the sample medium; QAQC/*.xls for the laboratory limits of reporting (LOR).
IMPORTANT data treatment by the compilers (chapter D, section 3): '<' values were REPLACED by 0.5 x LOR and '>' values by the upper limit, and
where an element was determined by several methods the HIGHEST value was kept - the per-element method is not recorded. So:
  - values are loaded as published; a value equal to 0.5 x one of the element's ALS LORs (from the QA/QC summaries) is classified
    BELOW_DL_PROBABLE (dl_value = that LOR, not used in statistics); Pt 0.00025 (the compilers' replacement for '<0.1' and for erroneous
    Pt values, per the Comment field) likewise, without a limit
  - '>' replacements cannot be identified and stay as values (caveat in the package / data source text)
Packages: PRISM-MRT-COMPILED (mixed methods, highest value per element, method UNKNOWN-UNKNOWN, basis T) and PRISM-MRT-BLEG (BLEG stream
samples, cyanide-leach gold, method BLEG-AAS, basis P).
Sample types from MasterLocations (Sample_type / Sample_type_French), else from the source table name.
Usage: python load_prism_mauritania.py [--check]
"""
import os, sys, io, csv, json, time, collections
import psycopg2, pyodbc

CHECK = "--check" in sys.argv
TAG = "migration_prism_mrt_20261114"
SRC = "MAURITANIA_USGS_PRISM"
PART = "mauritania_usgs_prism"
XID = "USGS_PRISM_MRT_SAMPLE_ID"
D = "D:/CriticalMineralsDB/Africa/Mauritania_PRISM2_20261114/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
LOR = {  # element -> ALS limits of reporting, from QAQC/*.xls summary tables (Method, LOR columns)
    "Ag": [0.01, 0.5, 1.0], "Al": [0.01], "As": [0.2, 5.0], "Au": [0.001, 0.005], "B": [10.0], "Ba": [0.5, 10.0], "Be": [0.05, 0.5],
    "Bi": [0.01, 2.0], "Ca": [0.01], "Cd": [0.02, 0.5], "Ce": [0.01], "Co": [0.1, 1.0], "Cr": [1.0], "Cs": [0.05], "Cu": [0.2, 1.0],
    "Fe": [0.01], "Ga": [0.05], "Ge": [0.05], "Hf": [0.1], "In": [0.005], "K": [0.01], "La": [0.5], "Li": [0.2], "Mg": [0.01], "Mn": [5.0],
    "Mo": [0.05, 1.0], "Na": [0.01], "Nb": [0.1], "Ni": [0.2, 1.0], "P": [10.0], "Pb": [0.5, 2.0], "Pd": [0.001], "Pt": [0.005, 0.1],
    "Rb": [0.1], "Re": [0.002], "S": [0.01], "Sb": [0.05, 5.0], "Se": [1.0], "Sn": [0.2], "Sr": [0.2, 1.0], "Ta": [0.05], "Te": [0.05],
    "Th": [0.2], "Ti": [0.01], "Tl": [0.02], "U": [0.1], "V": [1.0], "W": [0.1, 10.0], "Y": [0.1], "Zn": [2.0], "Zr": [0.5]}
ROCK = {"roche_grab": "ROCK_GRAB", "roche _grab": "ROCK_GRAB", "roche": "ROCK_GRAB", "rock chip": "ROCK_CHIP", "affleurement naturel": "ROCK_OUTCROP",
        "pétro sélectif": "ROCK_SELECT"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def acc(f):
    return pyodbc.connect(r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + D + f + ";ReadOnly=1").cursor()


c1 = acc("MasterChem.mdb"); c1.execute("SELECT * FROM tblMasterChem"); cols = [d[0] for d in c1.description]
chem = [dict(zip(cols, r)) for r in c1.fetchall()]
c2 = acc("MasterLocations.mdb"); c2.execute("SELECT * FROM tblSample_Locs"); lcols = [d[0] for d in c2.description]
locs = {r[0]: dict(zip(lcols, r)) for r in c2.fetchall()}
EL = [x for x in cols if x.endswith("_ppm") or x.endswith("_%")]


def stype(loc, table):
    if loc:
        t, fr = (loc["Sample_type"] or "").lower(), (loc["Sample_type_French"] or "").strip().lower()
        if t == "rock": return ROCK.get(fr, "ROCK_SAMPLE"), fr or "rock"
        if t == "bleg": return "SED_STREAM", "BLEG stream sediment"
        if t == "sediment": return "SED_STREAM", fr or "stream sediment"
        if t == "soil": return ("SOIL_RESIDUAL", "regolith") if fr == "regolith" else ("SOIL_SAMPLE", fr or "soil")
    tl = table.lower()
    if "bleg" in tl: return "SED_STREAM", "BLEG stream sediment"
    if "drainage" in tl: return "SED_STREAM", "stream sediment"
    if "soil" in tl: return "SOIL_SAMPLE", "soil"
    return "SAMPLE_UNKNOWN", "medium not recorded"


stats = collections.Counter()
samples, results = {}, []
for r in chem:
    sid = str(r["Sample_ID"]).strip()
    loc = locs.get(r["Sample_ID"])
    lat, lon = r["Latitude"], r["Longitude"]
    if not (lat and lon) and loc: lat, lon = loc["Latitude"], loc["Longitude"]
    if not (lat and lon): stats["no position"] += 1; continue
    assert 14 < lat < 28 and -18 < lon < -4, (sid, lat, lon)
    st, local = stype(loc, r["Table"] or "")
    bleg = local.startswith("BLEG")
    pkg = "PRISM-MRT-BLEG" if bleg else "PRISM-MRT-COMPILED"
    region = (loc or {}).get("Sampling_region") or "region not recorded"
    origin = (loc or {}).get("Origin_database") or (r["Table"] or "")
    note = "; ".join(x for x in [
        f"PRISM region {region}", f"origin {origin}", f"subarea {loc['Subarea']}" if loc and loc.get("Subarea") else "",
        f"source table {r['Table']}" if r["Table"] else "", f"origin table {loc['Origin_table']}" if loc and loc.get("Origin_table") else "",
        f"lab lot {r['Lot']}" if r["Lot"] else "", f"technique {r['Analytical_Technique']}" if r["Analytical_Technique"] else "",
        (r["Comment"] or "")[:200], "PRISM-I sample (BGS / BRGM, 1999-2004), compiled by the USGS (OFR 2013-1280)"] if x)
    samples[sid] = [sid, st, f"PRISM Mauritania: {local}"[:100], lat, lon, sid, sid, note, "SURFACE", None]
    stats["samples " + st] += 1
    for e in EL:
        v = r[e]
        if v is None: continue
        v = float(v)
        if v <= 0: stats["zero or negative"] += 1; continue
        el, unit = e.rsplit("_", 1)
        el = {"H2O/LOI": "LOI"}.get(el, el)
        unit = "%" if unit == "%" else "ppm"
        dl, cmt = None, None
        if el == "Pt" and abs(v - 0.00025) < 1e-9:
            dl, cmt = "PT", "compilers' replacement value for Pt '<0.1' or an erroneous Pt value (0.00025)"
        else:
            for l in LOR.get(el, []):
                if abs(v - 0.5 * l) <= 1e-9 * max(1, l):
                    dl, cmt = l, f"value = 0.5 x LOR {l:g} {unit}: probably a censored '<{l:g}' replaced by the compilers"
                    break
        if dl: stats["probable below detection"] += 1
        results.append([sid, pkg, el, unit, v, None if dl in (None, "PT") else dl, cmt, "BLEG" if bleg else None, 1 if dl else 0])
log("staged samples", len(samples), "results", len(results), dict(stats))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
if not CHECK:
    g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "source already has samples: delete them by created_by first"
for pk, name, mcode, basis, desc in [
        ("PRISM-MRT-COMPILED", "PRISM Mauritania compiled geochemistry (ALS Chemex, mixed methods)", "UNKNOWN-UNKNOWN", "T",
         "PRISM-I samples (BGS / BRGM 1999-2004) compiled by the USGS in MasterChem.mdb (OFR 2013-1280): four-acid ICP-MS / ICP-AES, fire assay, AAS "
         "and XRF at ALS Chemex; where several methods measured an element the highest value was kept; '<' replaced by 0.5 x LOR and '>' by the "
         "upper limit by the compilers"),
        ("PRISM-MRT-BLEG", "PRISM Mauritania BLEG stream-sediment gold (bulk leach extractable)", "BLEG-AAS", "P",
         "Bulk-leach extractable gold (cyanide leach) on regional BLEG stream-sediment samples, PRISM-I, compiled by the USGS (OFR 2013-1280)")]:
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'ALS'),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""", (pk, name, mcode, desc, TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, 1, 'PRISM Mauritania' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, 1, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, "PRISM Mauritania " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date", samples.values())
copy("st_result", "k text, pkg text, analyte text, unit text, val numeric, dl numeric, comment text, fraction text, probable int", results)
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
c.execute("SELECT t.sample_type_code, count(*) FROM st_sample s JOIN st_map USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype GROUP BY 1 ORDER BY 2 DESC")
log("sample types", c.fetchall())
if CHECK:
    c.execute("SELECT pkg, count(*), sum(probable) FROM st_result GROUP BY 1"); log("per package (results, probable <DL)", c.fetchall())
    g.rollback(); g.close(); log("CHECK RUN - rolled back"); sys.exit(0)

c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, NULL, NULL,
  'ALS Chemex (PRISM-I)', meth.method_code, p.package_name, meth.digest_name, r.val, r.dl, NULL, NULL, NULL, false, true, '{TAG}', now(),
  NULL, r.fraction, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id""")
nins = c.rowcount
log("results inserted", nins, "of", len(results))
assert nins == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.result_comment LIKE 'value = 0.5 x LOR%' OR r.result_comment LIKE 'compilers'' replacement%' THEN 'BELOW_DL_PROBABLE' ELSE 'DETECTED' END,
  r.lower_detection_limit, CASE WHEN r.lower_detection_limit IS NOT NULL THEN 'ALS_LOR_QAQC' END,
  NOT (coalesce(r.result_comment, '') LIKE 'value = 0.5 x LOR%' OR coalesce(r.result_comment, '') LIKE 'compilers'' replacement%')
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'value = 0.5 x an ALS LOR -> BELOW_DL_PROBABLE (compilers replaced < values by half the LOR)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "U.S. Geological Survey with the Ministry of Petroleum, Energy and Mines of Mauritania (PRISM-II, World Bank IDA-38100)",
           "PRISM-I/II geochemistry of rocks and unconsolidated materials in Mauritania (USGS OFR 2013-1280, chapter D, MasterChem.mdb)",
           "US public domain for the most part (USGS release; metadata Access_Constraints None; acknowledgement of the USGS appreciated)",
           "https://doi.org/10.3133/ofr20131280",
           "Source: U.S. Geological Survey Open-File Report 2013-1280 (PRISM-II), with the Ministry of Petroleum, Energy and Mines of Mauritania; samples collected by BGS and BRGM under PRISM-I.",
           "Cleared: FGDC metadata Geochemistry_IRM.xml Access_Constraints None, use constraint = acknowledgement of the USGS appreciated; release readme notes that it may contain copyrighted material noted in the text (none noted for the geochemistry). Checked 2026-11-14.",
           "Compiled values: '<' replaced by 0.5 x LOR, '>' by the upper limit, highest of several methods kept, per-element method unknown; probable censored values flagged BELOW_DL_PROBABLE; samples 1999-2004, no dates; the report calls the data unsuitable for multivariate statistics.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\USGS_PRISM_MAURITANIA\ (metadata, readme, EVIDENCE.md)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG)
g.close()
