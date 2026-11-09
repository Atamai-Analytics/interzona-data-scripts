"""Add ONE element from IGME Geoquímica (Spain) to interzona_cm source SPAIN_IGME_GEOCHEMISTRY (2026-11-08; generalises load_igme_lithium.py).

Input: D:/CriticalMineralsDB/Spain/download_20261108/igme_test_<EL>_rows.jsonl and _detail.jsonl (igme_download_test.py <EL>).
Method per campaign: from the detail records (25 random samples per campaign) - for each sample, the detail entry of <EL> whose value equals the
table value gives (technique, type, detection limit, unit). A campaign must be consistent (>= 90 % of checked samples the same, none restricted),
else the script stops for review. Technique label -> our method code via TECH (unknown labels stop the script). Packages are per campaign +
IGME technique label (the lithium packages are reused for the same campaign + label). Samples are reused by IGME id; new samples are added.
Values below the campaign detection limit get qualifier '<' (value kept as reported). Restricted elements (As, Au, Hg, U) are refused.
Usage: python load_igme_element.py <EL> [--check]
"""
import os, sys, io, csv, json, re, time, collections
import psycopg2

EL = sys.argv[1]
CHECK = "--check" in sys.argv
assert EL not in ("As", "Au", "Hg", "U"), "IGME restricts this element"
TAG = f"migration_igme_{EL.lower()}_20261108"
SRC, PART, XID = "SPAIN_IGME_GEOCHEMISTRY", "spain_igme_geochemistry", "IGME_GEOQUIMICA"
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


# IGME technique label -> (method code, priority in the wide table: ICP-MS 1, ICP-OES 2, XRF/INAA 3, mixed/unknown 5)
TECH = {"TD-MS": ("4A-ICPMS", 1), "TD-ICP-MS": ("4A-ICPMS", 1), "ICP-MS": ("4A-ICPMS", 1), "TD-ICP": ("4A-ICPOES", 2), "ICP": ("4A-ICPOES", 2),
        "INAA": ("NONE-INAA", 3), "XRF": ("NONE-XRF", 3), "DCP": ("TD-DCP", 2)}
LI_PKG = {(19, "TD-MS"): "IGME-MGE-TDMS", (2, "ICP"): "IGME-BADAJOZ-ICP", (1, "ICP-MS"): "IGME-FOREGS-SED-ICPMS", (18, "ICP-MS"): "IGME-FOREGS-WAT-ICPMS"}
UNIT = {"ppm": "ppm", "ppb": "ppb", "%": "%", "µg/l": "µg/L", "mg/l": "mg/L"}
STYPE = {"Sedimento": "SED_STREAM", "Suelo C": "SOIL_C", "Suelo": "SOIL_SAMPLE", "Roca": "ROCK_SAMPLE", "No se sabe": "SAMPLE_UNKNOWN",
         "Batea": "SED_HMC"}   # Batea = panned concentrate (FOREGS water rows are also labelled Batea by IGME; campaign 18 is forced to WATER_SAMPLE)


def method_for(label, camp):
    if camp == 18: return "WATER-ICPMS", 1
    if label in TECH: return TECH[label]
    if label.upper().startswith("MULT"):                                   # IGME's combined value from several techniques
        parts = [p.strip() for p in label[4:].split("/")]
        if parts and all(p in ("TD-ICP", "TD-ICP-MS", "TD-MS") for p in parts): return "4A-ICPMS", 1   # all total-digestion ICP(-MS)
        return "UNKNOWN-UNKNOWN", 5
    raise SystemExit(f"unknown IGME technique label {label!r} (campaign {camp}) - add it to TECH")


rows = [json.loads(l) for l in open(f"{DL}/igme_test_{EL}_rows.jsonl", encoding="utf-8")]
det = [json.loads(l) for l in open(f"{DL}/igme_test_{EL}_detail.jsonl", encoding="utf-8")]
camp_of = {r["id"]: r["codCampana"] for r in rows}
ev = collections.defaultdict(collections.Counter)
for d in det:
    m = [e for e in d["detail"] if e["concentracion"] is not None and d["table_value"] is not None and abs(e["concentracion"] - d["table_value"]) < 1e-9]
    key = (m[0]["tecnica"], m[0]["tipo"], m[0]["limiteDeteccion"], m[0]["unidades"], m[0]["restringido"]) if m else ("NO MATCH",)
    ev[camp_of[d["id"]]][key] += 1
PK = {}
for camp, cnt in ev.items():
    (key, n), tot = cnt.most_common(1)[0], sum(cnt.values())
    log("campaign", camp, "evidence", dict(cnt))
    if key[0] == "NO MATCH" or n / tot < 0.9 or key[4]: raise SystemExit(f"campaign {camp}: method evidence not consistent / restricted - review: {dict(cnt)}")
    tech, tipo, dlv, unit, _ = key
    mcode, prio = method_for(tech, camp)
    code = LI_PKG.get((camp, tech)) or "IGME-C%d-%s" % (camp, re.sub(r"[^A-Z0-9]+", "", tech.upper()))
    PK[camp] = (code, mcode, "T" if (tipo or "").lower().startswith("total") or camp == 18 else "P", prio, tech, tipo, dlv, unit)
log("packages", PK)

camp_name = {}
samples, results, stats = {}, [], collections.Counter()
for r in rows:
    camp = r["codCampana"]
    if camp not in PK: stats["campaign without method evidence"] += 1; continue
    code, mcode, basis, prio, tech, tipo, dlv, dunit = PK[camp]
    if r["concentracion"] is None: stats["null value"] += 1; continue
    unit = UNIT[r["unidad"]]
    lon, lat = r["xgeometria"], r["ygeometria"]
    if not (-18.5 < lon < 4.5 and 27 < lat < 44.0): stats["outside Spain box"] += 1; continue
    camp_name[camp] = r["nombreCamp"]
    st = "WATER_SAMPLE" if camp == 18 else STYPE.get(r["tipoMuestra"], "SAMPLE_UNKNOWN")
    if r["id"] not in samples:
        samples[r["id"]] = [r["id"], st, f"{r['tipoMuestra']} ({r['nombreCamp']})", lon, lat,
                            "; ".join(x for x in [f"IGME campaign {r['nombreCamp']} (programme {r['nombrePrograma']})", f"IGME sample {r['id']} / ref {r['refMuestra']}",
                                                  f"MAGNA 1:50k sheet {r['hoja']}" if r.get("hoja") else "",
                                                  f"UTM zone {r['huso']} {r['x']} E {r['y']} N" if r.get("x") else "",
                                                  f"lithology {r['litologia']}" if r.get("litologia") and r["litologia"] != "Desconocida" else ""] if x)]
    below = dlv is not None and r["concentracion"] < dlv
    stats["below DL"] += below; stats["values"] += 1
    results.append([r["id"], code, EL, unit, "<" if below else N, r["concentracion"], dlv, N, f"IGME technique {tech} ({tipo}), detection limit {dlv} {unit}"])
log("samples", len(samples), "| stats", dict(stats))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("""SELECT count(*) FROM geochem.analytical_results r JOIN geochem.analytes a USING (analyte_id) WHERE r.source_system = %s AND a.analyte_code = %s""", (SRC, EL))
assert c.fetchone()[0] == 0, f"{EL} already loaded for {SRC}"


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); cw = csv.writer(buf)
    for r in data: cw.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0); c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "skey text, stype text, stype_local text, lon double precision, lat double precision, comments text", samples.values())
copy("st_result", "skey text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, fraction text, comment text", results)
c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, digest_completeness, digest_description,
             instrument_code, instrument_name, application, notes, is_active, created_by, created_date)
             SELECT 'TD-DCP', 'Total Digestion / Direct Current Plasma Emission', 'TD', 'Total digestion (acids not stated)', 'Total (as reported)',
                    'Total digestion as reported by IGME; acid mix not stated.', 'DCP', 'Direct Current Plasma Atomic Emission Spectrometry',
                    'Stream sediments (older IGME regional campaigns)', 'Added for IGME Geoquímica DCP results (2026-11-08).', true, %s, now()
             WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = 'TD-DCP')""", (TAG,))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
for camp, (code, mcode, basis, prio, tech, tipo, dlv, unit) in PK.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, f"IGME {camp_name.get(camp, camp)} - IGME technique label {tech} ({tipo})", mid[mcode],
               f"IGME Geoquímica campaign {camp}; IGME technique label '{tech}', type {tipo}", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'IGME Geoquímica' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, code))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO NOTHING""", (SRC, basis, prio, "IGME campaign mapping " + TAG, code))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]; assert not miss, (label, miss)
log("dictionary checks passed")
# existing samples by IGME id; new ones inserted
c.execute(f"""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.skey, coalesce(x.sample_id, nextval('geochem.samples_sample_id_seq')) AS sample_id,
              x.sample_id IS NULL AS is_new, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326) AS pt FROM st_sample s
              LEFT JOIN geochem.samples x ON x.source_system = '{SRC}' AND x.sample_number = s.skey""")
c.execute("SELECT count(*) FILTER (WHERE is_new), count(*) FILTER (WHERE NOT is_new) FROM st_map"); new, old = c.fetchone()
log("samples new", new, "| reused", old)
c.execute(f"""INSERT INTO geochem.samples (sample_id, geom, sample_number, sample_type_id, sample_type_local, sample_context, comments, is_active,
  created_by, created_date, source_system) OVERRIDING SYSTEM VALUE
  SELECT m.sample_id, m.pt, s.skey, t.sample_type_id, s.stype_local, 'SURFACE', nullif(s.comments, ''), true, '{TAG}', now(), '{SRC}'
  FROM st_sample s JOIN st_map m USING (skey) JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE m.is_new""")
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', skey, '{TAG}', now() FROM st_map WHERE is_new""")
if CHECK:
    c.execute("SELECT pkg, count(*), count(*) FILTER (WHERE qual = '<'), min(val), max(val) FROM st_result GROUP BY 1 ORDER BY 1"); log("per package (n, <DL, min, max)", c.fetchall())
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
nins = c.rowcount
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("results inserted", nins, "of", len(results)); assert nins == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r WHERE r.created_by = '{TAG}'""")
c.execute("""UPDATE core.data_sources SET dataset_name = 'IGME Geoquímica (info.igme.es/Geoquimica) - loaded one element at a time, retrieved 2026-11-08',
             caveats = replace(caveats, 'Lithium only so far (other elements not loaded yet).', 'Loaded one element at a time; not all IGME elements yet (see the analytes present).')
             WHERE source_system = %s""", (SRC,))
g.commit(); log("COMMITTED", EL)
