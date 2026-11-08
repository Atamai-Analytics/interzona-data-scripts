"""IGME (Instituto Geológico y Minero de España) geochemistry - LITHIUM ONLY (first slice) -> interzona_cm, source SPAIN_IGME_GEOCHEMISTRY.

Input: D:/CriticalMineralsDB/Spain/download_20261108/igme_test_Li_rows.jsonl (igme_download_test.py, 2026-11-08: IGME API resultCampSubs,
43,702 samples in 4 campaigns) and igme_test_Li_detail.jsonl (fichaDetalle for 25 random samples per campaign: technique, type, detection limit).
Licence: IGME generic user licence 2022 (Law 37/2007): free commercial reuse, credit "Source: © NC Geological Survey of Spain (IGME)";
evidence D:/CriticalMineralsDB/Documents/Licence_Evidence/IGME_Spain/EVIDENCE.md. Restricted elements (As, Au, Hg, U) are not part of this slice.
Method per campaign (same technique / DL in all 25 checked samples of each campaign; applied to the whole campaign):
  Mapa Geoquímico de España (19): TD-MS, Total, DL 0.5 ppm      -> 4A-ICPMS
  Badajoz Sur (2):                 ICP, Total, DL 1 ppm         -> 4A-ICPOES (IGME does not name the acids; 'Total' as reported)
  España-FOREGS Sediments (1):     ICP-MS, Total, DL 0.05 ppm   -> 4A-ICPMS
  España-FOREGS Water (18):        ICP-MS, DL 0.005 ug/L        -> WATER-ICPMS (filtered water; not in the wide table, which is solids only)
No value is below its detection limit; all results are DETECTED. One sample per IGME id; samples get the IGME id as sample_number and
external_ids source IGME_GEOQUIMICA. Later elements will be added to the same source_system (samples are reused by IGME id).
Usage: python load_igme_lithium.py [--check]
"""
import os, sys, io, csv, json, time, collections
import psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_igme_li_20261108"
SRC = "SPAIN_IGME_GEOCHEMISTRY"
PART = "spain_igme_geochemistry"
XID = "IGME_GEOQUIMICA"
DL = "D:/CriticalMineralsDB/Spain/download_20261108"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# campaign code -> (package code, package name, method code, basis, priority, IGME technique label, detection limit, expected unit)
PKG = {
    19: ("IGME-MGE-TDMS", "IGME Mapa Geoquímico de España - total digestion, ICP-MS (IGME label TD-MS, Total)", "4A-ICPMS", "T", 1, "TD-MS", 0.5, "ppm"),
    2: ("IGME-BADAJOZ-ICP", "IGME Badajoz Sur - ICP after total digestion (IGME label ICP, Total; acids not stated)", "4A-ICPOES", "T", 2, "ICP", 1, "ppm"),
    1: ("IGME-FOREGS-SED-ICPMS", "IGME España-FOREGS stream sediments - ICP-MS, total (IGME label ICP-MS, Total)", "4A-ICPMS", "T", 1, "ICP-MS", 0.05, "ppm"),
    18: ("IGME-FOREGS-WAT-ICPMS", "IGME España-FOREGS stream water - filtered water, ICP-MS (IGME label ICP-MS)", "WATER-ICPMS", "T", 1, "ICP-MS", 0.005, "µg/L"),
}
UNIT = {"ppm": "ppm", "µg/l": "µg/L"}
STYPE = {"Sedimento": "SED_STREAM", "Suelo C": "SOIL_C", "Suelo": "SOIL_SAMPLE", "Roca": "ROCK_SAMPLE", "No se sabe": "SAMPLE_UNKNOWN"}

# ---- check the method evidence (detail records) agrees with PKG
det = [json.loads(l) for l in open(f"{DL}/igme_test_Li_detail.jsonl", encoding="utf-8")]
ev = collections.defaultdict(set)
for d in det:
    for e in d["detail"]: ev[d["campaign"]].add((e["tecnica"], e["tipo"], e["limiteDeteccion"], e["restringido"]))
log("method evidence per campaign:", {k: sorted(v) for k, v in ev.items()})

rows = [json.loads(l) for l in open(f"{DL}/igme_test_Li_rows.jsonl", encoding="utf-8")]
samples, results, stats = {}, [], collections.Counter()
for r in rows:
    camp = r["codCampana"]; pkg = PKG[camp]
    if r["sustancia"] != "Li": stats["not Li"] += 1; continue
    if r["concentracion"] is None: stats["null value"] += 1; continue
    unit = UNIT[r["unidad"]]; assert unit == pkg[7], (camp, unit)
    lon, lat = r["xgeometria"], r["ygeometria"]
    if not (-18.5 < lon < 4.5 and 27 < lat < 44.0): stats["outside Spain box"] += 1; continue
    st = "WATER_SAMPLE" if camp == 18 else STYPE[r["tipoMuestra"]]
    if r["id"] not in samples:
        samples[r["id"]] = [r["id"], st, f"{r['tipoMuestra']} ({r['nombreCamp']})", lon, lat,
                            "; ".join(x for x in [f"IGME campaign {r['nombreCamp']} (programme {r['nombrePrograma']})", f"IGME sample {r['id']} / ref {r['refMuestra']}",
                                                  f"MAGNA 1:50k sheet {r['hoja']}" if r.get("hoja") else "",
                                                  f"UTM zone {r['huso']} {r['x']} E {r['y']} N" if r.get("x") else "",
                                                  f"lithology {r['litologia']}" if r.get("litologia") and r["litologia"] != "Desconocida" else ""] if x)]
    below = r["concentracion"] < pkg[6]
    stats["below DL"] += below
    results.append([r["id"], pkg[0], "Li", unit, "<" if below else N, r["concentracion"], pkg[6], N, f"IGME technique {pkg[5]}, detection limit {pkg[6]} {unit}"])
    stats["values"] += 1
log("samples", len(samples), "| types", collections.Counter(v[1] for v in samples.values()), "| stats", dict(stats))

p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
p0.autocommit = True
if not CHECK:
    p0.cursor().execute("SET lock_timeout = '20s'")
    p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_{PART} PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
    p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_{PART} PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
p0.close()
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); cw = csv.writer(buf)
    for r in data: cw.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0); c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "skey text, stype text, stype_local text, lon double precision, lat double precision, comments text", samples.values())
copy("st_result", "skey text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, fraction text, comment text", results)

c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, digest_completeness, digest_description,
             instrument_code, instrument_name, application, notes, is_active, created_by, created_date)
             SELECT 'WATER-ICPMS', 'Filtered Water / ICP-MS (no digestion)', 'NONE', 'None (filtered, acidified water)', 'Dissolved',
                    'Water sample filtered and acidified; dissolved concentrations, no digestion.', 'ICP-MS', 'Inductively Coupled Plasma Mass Spectrometry',
                    'Stream / surface water', 'Added for IGME España-FOREGS stream water (2026-11-08).', true, %s, now()
             WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = 'WATER-ICPMS')""", (TAG,))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
for camp, (pkg, name, mcode, basis, prio, lab, dl, unit) in PKG.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pkg, name, mid[mcode], f"IGME Geoquímica campaign {camp}; IGME technique label '{lab}', type Total, Li detection limit {dl} {unit}", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'IGME Geoquímica' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, pkg))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "IGME campaign mapping " + TAG, pkg))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]; assert not miss, (label, miss)
log("dictionary checks passed")
c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.skey, nextval('geochem.samples_sample_id_seq') AS sample_id,
             ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326) AS pt FROM st_sample s""")
c.execute(f"""INSERT INTO geochem.samples (sample_id, geom, sample_number, sample_type_id, sample_type_local, sample_context, comments, is_active,
  created_by, created_date, source_system) OVERRIDING SYSTEM VALUE
  SELECT m.sample_id, m.pt, s.skey, t.sample_type_id, s.stype_local, 'SURFACE', nullif(s.comments, ''), true, '{TAG}', now(), '{SRC}'
  FROM st_sample s JOIN st_map m USING (skey) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', skey, '{TAG}', now() FROM st_map""")
c.execute(f"SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}' AND (lat NOT BETWEEN 27 AND 44 OR lon NOT BETWEEN -18.5 AND 4.5)")
log("samples outside Spain box (must be 0)", c.fetchone()[0])
if CHECK:
    g.rollback(); log("CHECK RUN - rolled back"); sys.exit(0)
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(), NULL, r.fraction, r.comment
FROM st_result r JOIN st_map m ON m.skey = r.skey JOIN geochem.analytes a ON a.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results_{PART}"); ngr = c.fetchone()[0]
log("results", ngr, "of", len(results)); assert ngr == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_igme_li_20261108', now(), now(), count(*), 'rule-based classification at load (value below the IGME detection limit = below DL)'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-08',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Instituto Geológico y Minero de España (IGME-CSIC)", "IGME Geoquímica (info.igme.es/Geoquimica) - lithium from 4 campaigns, retrieved 2026-11-08",
           "IGME generic user licence 2022 (free re-use, commercial and non-commercial, Law 37/2007)", "https://www.igme.es/condiciones-de-uso/",
           "Source: © NC Geological Survey of Spain (IGME). FOREGS campaigns: FOREGS Geochemical Baseline Programme (EuroGeoSurveys), data via IGME.",
           "Cleared: IGME generic user licence (LicUsoIGME_GENERICA_EN_2022) allows commercial re-use with credit (checked 2026-11-08). Loaded 2026-11-08.",
           "Lithium only so far (other elements not loaded yet). Retrieved through IGME's public geochemistry API. Method per campaign from IGME's sample detail "
           "records (25 checked per campaign, all identical): national map TD-MS total DL 0.5 ppm; Badajoz Sur ICP total DL 1 ppm (acids not stated); FOREGS "
           "sediments ICP-MS total DL 0.05 ppm; FOREGS water ICP-MS DL 0.005 ug/L (dissolved, not in the wide table). IGME withholds As, Au, Hg and U "
           "(restricted) - not loaded. Do not imply IGME endorsement; quote IGME as source.",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/IGME_Spain/EVIDENCE.md", TAG))
g.commit(); log("COMMITTED")
