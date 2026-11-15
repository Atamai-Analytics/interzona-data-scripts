"""GEMAS - Geochemical Mapping of Agricultural and Grazing Land Soil of Europe (EuroGeoSurveys Geochemistry Expert Group with Eurometaux;
34 countries, sampled 2008-early 2009, 1 site per 2,500 km2) -> interzona_cm gold, new source EUROPE_GEMAS (own partitions; rollback = delete by
created_by = TAG). Licence CC BY 4.0 (EGDI metadata record 399663a7-0941-45a3-8952-28bbae54a5b6, useConstraints "Creative Commons BY 4.0").
Input: D:/CriticalMineralsDB/Europe/GEMAS_20261114/ - full feature dumps (2026-11-14, user approved "Load both") of the Geological Survey Ireland
ArcGIS service IE_GSI_GEMAS_Geochemistry_Agricultural_Grazing_Land_Soil_EU_WGS84: layer 15 (Ap agricultural soil 0-20 cm: aqua regia + XRF +
C/S + LOI), layer 69 (Gr grazing land soil 0-10 cm: aqua regia + XRF + C/S + LOI), layer 121 (Ap: Mobile Metal Ion extraction).
Units: aqua regia and MMI elements mg/kg; XRF major oxides, LOI, C_tot and S_tot in %; XRF trace elements mg/kg. The XRF element columns for
the major elements (SI_XRF, AL_XRF ...) are the oxides converted and are left out; TOC, pH, CEC, grain size, Pb isotopes and susceptibility are
not loaded (no matching analytes / not element concentrations).
Below detection: GEMAS reports values below the detection limit as half the limit, so in every column the lowest value, where it makes up at least
1% of the samples, is classified BELOW_DL_PROBABLE with dl_value = 2 x that value (inferred limit; not used in statistics). Samples without
coordinates (5 Ap, 1 Gr) are skipped. Ap and MMI results share the Ap sample (same ID).
Packages: GEMAS-AR (AR-ICPMS, basis P), GEMAS-MMI (MMI-ICPMS, basis P), GEMAS-XRF (NONE-XRF, T), GEMAS-LECO (NONE-LECO, T).
comments start 'GEMAS <Ap|Gr> <country code>' (Geostatistics survey key: one sample type and country).
Usage: python load_gemas.py [--check]
"""
import os, sys, io, csv, json, time, collections
import psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_gemas_20261114"
SRC = "EUROPE_GEMAS"
PART = "europe_gemas"
XID = "GEMAS_SAMPLE_ID"
D = "D:/CriticalMineralsDB/Europe/GEMAS_20261114/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
META = {"OBJECTID", "ID", "COUNTRY", "C_ID", "TYPE_", "TYPE2", "XCOO", "YCOO", "XLAEA", "YLAEA", "ALT", "CIA", "SAND", "SILT", "CLAY", "SAND_NORM",
        "SILT_NORM", "CLAY_NORM", "SOILTYPE", "SOILCLASS", "CLIMATE", "MEANTEMPANNPREC", "MEANTEMP", "ANNPREC", "F22", "PM", "CEC", "PH_CACL2", "TOC", "SHAPE",
        "F1", "F1_1", "F1_12", "F1_12_13", "F1_12_13_14", "F1_12_13_14_15", "SUSCEPTIBILITY", "SUSCEPTIBILITY_FE2O3", "ELEMENT"}
OXIDES = {"SIO2": "SiO2", "TIO2": "TiO2", "AL2O3": "Al2O3", "FE2O3": "Fe2O3", "MNO": "MnO", "MGO": "MgO", "CAO": "CaO", "NA2O": "Na2O", "K2O": "K2O",
          "P2O5": "P2O5", "LOI": "LOI"}
SKIP_XRF_MAJOR = {"SI_XRF", "TI_XRF", "AL_XRF", "FE_XRF", "MN_XRF", "MG_XRF", "CA_XRF", "NA_XRF", "K_XRF", "P_XRF"}


def element(col):
    return {"AS_": "As", "IN_": "In"}.get(col, col[:1] + col[1:].lower())


def mapping(col, layer):
    """-> (package, analyte, unit) or None"""
    if col in META or col in SKIP_XRF_MAJOR: return None
    if col in OXIDES: return ("GEMAS-XRF", OXIDES[col], "%")
    if col == "C_TOT": return ("GEMAS-LECO", "C", "%")
    if col == "S_TOT": return ("GEMAS-LECO", "S", "%")
    if col.endswith("_XRF"): return ("GEMAS-XRF", element(col[:-4]), "ppm")
    return ("GEMAS-MMI" if layer == "MMI" else "GEMAS-AR", element(col), "ppm")


stats = collections.Counter()
samples, rows = {}, []
for fn, layer in [("gemas_layer15_Ap_AR_XRF.json", "Ap"), ("gemas_layer69_Gr_AR_XRF.json", "Gr"), ("gemas_layer121_Ap_MMI.json", "MMI")]:
    feats = json.load(open(D + fn))["features"]
    for f in feats:
        a = f["attributes"]
        if a.get("ID") is None or a.get("XCOO") is None: stats[f"{layer} no id/position"] += 1; continue
        typ = "Ap" if layer in ("Ap", "MMI") else "Gr"
        k = f"{typ}:{int(a['ID'])}"
        if layer != "MMI":
            if k in samples: stats["duplicate row " + layer] += 1; continue
            lat, lon = a["YCOO"], a["XCOO"]
            assert 25 < lat < 82 and -32 < lon < 45, (k, lat, lon)
            depth = "0-20 cm (ploughed agricultural soil)" if typ == "Ap" else "0-10 cm (grazing land soil)"
            note = "; ".join(x for x in [f"GEMAS {typ} {a.get('COUNTRY') or 'unknown'}", depth, f"site {int(a['ID'])}",
                                         f"soil class {a['SOILCLASS']}" if a.get("SOILCLASS") else "", f"parent material {a['PM']}" if a.get("PM") else "",
                                         f"pH(CaCl2) {a['PH_CACL2']}" if a.get("PH_CACL2") is not None else "", f"TOC {a['TOC']} %" if a.get("TOC") is not None else "",
                                         f"climate {a['CLIMATE']}" if a.get("CLIMATE") else "", "sampled 2008-2009"] if x)
            samples[k] = [k, "SOIL_A", f"GEMAS {'agricultural (Ap)' if typ == 'Ap' else 'grazing land (Gr)'} soil"[:100], lat, lon, str(int(a["ID"])), k, note, "SURFACE"]
            stats["samples " + typ] += 1
        elif k not in samples:
            stats["MMI without Ap sample"] += 1; continue
        for col, v in a.items():
            mp = mapping(col, layer)
            if mp is None or v is None: continue
            if isinstance(v, str):
                try: v = float(v)
                except ValueError: stats["text value " + col] += 1; continue
            if v <= 0: stats["zero or negative"] += 1; continue
            rows.append([k, mp[0], mp[1], mp[2], float(v), f"{layer}:{col}"])
log_counts = dict(stats)
# probable below-detection: per (layer, column) the minimum value if it makes up >= 1% of the values
by_col = collections.defaultdict(list)
for r in rows: by_col[r[5]].append(r[4])
mins = {}
for col, vals in by_col.items():
    m = min(vals); n = sum(1 for v in vals if abs(v - m) <= 1e-12 * max(1, m))
    if n >= 0.01 * len(vals) and n >= 5: mins[col] = m
results = []
for k, pkg, an, unit, v, col in rows:
    probable = col in mins and abs(v - mins[col]) <= 1e-12 * max(1, v)
    if probable: stats["probable below detection"] += 1
    results.append([k, pkg, an, unit, v, 2 * v if probable else None,
                    f"GEMAS {col}" + (f"; value = half the inferred detection limit {2 * v:g} {unit} (GEMAS reports <DL as DL/2)" if probable else ""),
                    "<2 mm, 0-20 cm" if k.startswith("Ap") else "<2 mm, 0-10 cm", 1 if probable else 0])
print(time.strftime("%H:%M:%S"), "staged samples", len(samples), "results", len(results), dict(stats), flush=True)
print("columns with an inferred detection limit:", len(mins), sorted((c_, round(v_, 6)) for c_, v_ in mins.items()), flush=True)

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
for pk, name, mcode, basis, prio in [("GEMAS-AR", "GEMAS aqua regia extraction, ICP-MS/ICP-AES", "AR-ICPMS", "P", 1),
                                     ("GEMAS-MMI", "GEMAS Mobile Metal Ion (MMI) extraction, ICP-MS (Ap soils)", "MMI-ICPMS", "P", 2),
                                     ("GEMAS-XRF", "GEMAS X-ray fluorescence, total element concentrations", "NONE-XRF", "T", 1),
                                     ("GEMAS-LECO", "GEMAS total carbon and total sulfur (combustion, infrared)", "NONE-LECO", "T", 1)]:
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pk, name, mcode, name + " - EuroGeoSurveys GEMAS project (2008-2009 sampling; one laboratory per method for all of Europe)", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'GEMAS' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "GEMAS " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text", samples.values())
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
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, NULL, true,
  '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
print("samples inserted", c.rowcount, "| without results", len(samples) - c.rowcount, flush=True)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
if CHECK:
    c.execute("SELECT pkg, count(*), sum(probable) FROM st_result GROUP BY 1"); print("per package (results, probable <DL)", c.fetchall())
    c.execute("SELECT analyte, unit, percentile_cont(0.5) WITHIN GROUP (ORDER BY val) FROM st_result WHERE pkg='GEMAS-MMI' AND analyte IN ('Cu','Zn','Au','Pb') GROUP BY 1,2"); print("MMI medians", c.fetchall())
    g.rollback(); g.close(); print("CHECK RUN - rolled back"); sys.exit(0)
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, NULL, NULL,
  'GEMAS project laboratory', meth.method_code, p.package_name, meth.digest_name, r.val, r.dl, NULL, NULL, NULL, false, true, '{TAG}', now(),
  NULL, r.fraction, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id""")
nins = c.rowcount
print("results inserted", nins, "of", len(results), flush=True)
assert nins == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.result_comment LIKE '%%half the inferred detection limit%%' THEN 'BELOW_DL_PROBABLE' ELSE 'DETECTED' END,
  r.lower_detection_limit, CASE WHEN r.lower_detection_limit IS NOT NULL THEN 'INFERRED_HALF_DL' END,
  r.result_comment NOT LIKE '%%half the inferred detection limit%%'
FROM geochem.analytical_results_{PART} r""")
print("classified", c.rowcount, flush=True)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'GEMAS <DL reported as DL/2: per-column frequent minimum -> BELOW_DL_PROBABLE')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "EuroGeoSurveys Geochemistry Expert Group and Eurometaux (GEMAS project); data service by Geological Survey Ireland via EGDI",
           "GEMAS - Geochemical Mapping of Agricultural and Grazing Land Soil of Europe (aqua regia, XRF, MMI, C/S)",
           "CC BY 4.0 (EGDI metadata 399663a7-0941-45a3-8952-28bbae54a5b6)", "https://creativecommons.org/licenses/by/4.0/",
           "Contains GEMAS data (Reimann et al. 2014, Chemistry of Europe's agricultural soils; EuroGeoSurveys/Eurometaux), via EGDI, CC BY 4.0.",
           "Cleared: EGDI ISO metadata useConstraints 'Creative Commons BY 4.0', accessConstraints 'no limitations to public access' - checked 2026-11-14.",
           "Low density (1 site per 2,500 km2), sampled 2008-2009; aqua regia and MMI are partial extractions; <DL values were reported as DL/2 (flagged BELOW_DL_PROBABLE with an inferred limit).",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\EUROPE_GEMAS\ (EGDI metadata XML, EVIDENCE.md)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); print("COMMITTED", TAG, flush=True)
c.execute(f"ANALYZE geochem.analytical_results_{PART}"); c.execute(f"ANALYZE geochem.result_classifications_{PART}"); g.commit()
g.close()
