"""NGU (Geological Survey of Norway) inorganic soil geochemistry -> interzona_cm gold, new source NORWAY_NGU_GEOCHEMISTRY (own partitions,
rollback = delete by created_by = TAG). Licence NLOD 2.0 (commercial use allowed, credit NGU); evidence in
D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\NGU_Norway.

Input: D:/CriticalMineralsDB/Norway/ngu_geokjemi_api_20261114/samples_inorganic_features.json - every feature of the OGC API collection
https://geotest.ngu.no/api/features/geokjemi/collections/samples_inorganic (downloaded 2026-11-14 with the user's approval; the service behind
NGU's Mineral Exploration map). 10,764 mineral-soil samples from 13 survey areas (1980-2025), all '15 g sample / Aqua Regia / ICP-AES/MS'
at ACME, ALS or Bureau Veritas; 65 elements, all ppm (checked: Al/Fe/Ca/Mg in the 1e4-1e5 range, Au 0.0003 = 0.3 ppb).
Conventions: negative value = below the detection limit (|value| = limit); REE columns of the older surveys arrive as text numbers.
The geometry is correct (lon, lat); the attribute names latitudeWgs84 / longitudeWgs84 are swapped in the service, so they are not used.
What is loaded
  - every sample (field duplicates, duplettTriplett 0.1, are kept and marked in comments); external id = the service feature id (fid)
  - one package per laboratory: NGU-AR-ICPMS-<ACME|ALS|BV>, method AR-ICPMS, basis P (aqua regia is a partial digestion), priority 1
  - zero values left out
Sample type: soil class (jordklasse) 'Morene...' -> TILL_SAMPLE, otherwise SOIL_SAMPLE (NGU calls the medium 'mineral soil'; most records
have no soil class). Fraction = '<2 mm' or '<0.063 mm'. Field year (feltAar) only, so sample_date stays NULL and the year is in comments.
comments start 'NGU survey <area> <year>; lab <lab>' - the Geostatistics page uses that as the survey key (one area, year and laboratory).
Usage: python load_ngu_geochem.py [--check]
"""
import os, sys, io, csv, json, time, collections
import psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_ngu_geochem_20261114"
SRC = "NORWAY_NGU_GEOCHEMISTRY"
PART = "norway_ngu_geochemistry"
XID = "NGU_GEOKJEMI_FID"
F = "D:/CriticalMineralsDB/Norway/ngu_geokjemi_api_20261114/samples_inorganic_features.json"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
LAB = {"ACME": "ACME", "ALS": "ALS", "Bureau Veritas": "BV"}
AREA = {"S\u00f8r_Norge": "S\u00f8r-Norge", "NordSalten": "Nord-Salten", "Nordland_Troms": "Nordland-Troms", "More og Romsdal": "M\u00f8re og Romsdal"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


feats = json.load(open(F, encoding="utf-8"))
stats = collections.Counter()
samples, results = {}, []
for f in feats:
    p = f["properties"]
    k = str(f["id"])
    lon, lat = f["geometry"]["coordinates"][:2]
    assert 57 < lat < 72 and 4 < lon < 32, (k, lat, lon)
    lab = LAB[p["lab"]]
    area = AREA.get(p["provetakingsomrade"], p["provetakingsomrade"])
    yr = p.get("feltAar")
    soil = (p.get("jordklasse") or "").strip()
    st = "TILL_SAMPLE" if soil.lower().startswith("morene") else "SOIL_SAMPLE"
    frac = f"<{p['maxKornstorrelse']:g} {p['maxKornstorrelseUnit']}"
    depth = f"{p['provedypFra']}-{p.get('provedypTil') or ''} {p.get('provedypEnhet') or ''}".strip(" -") if p.get("provedypFra") else ""
    note = "; ".join(x for x in [
        f"NGU survey {area} {yr or 'year unknown'}", f"lab {p['lab']}", f"NGU project {p['nguProsjektNummer']}", f"{p['typeUndersokelse']} survey",
        f"locality {p['lokalitetKode']}", f"sample {p['proveKode']}", p["ekstraksjon"], f"fraction {frac}", f"depth {depth}" if depth else "",
        f"soil class {soil}" if soil else "", "field duplicate" if p.get("duplettTriplett") else "",
        f"position accuracy about {p['noyaktighetsEstimat']} m" if p.get("noyaktighetsEstimat") else "",
        (p.get("feltNotat") or "").strip()[:150]] if x)
    local = f"NGU mineral soil ({soil})" if soil else "NGU mineral soil"
    samples[k] = [k, st, local[:100], lat, lon, p["proveKode"], f"NGU-{p['nguProsjektNummer']}-{p['lokalitetKode']}-{p['proveKode']}", note, "SURFACE", None, frac]
    stats["samples " + st] += 1
    for e, v in p.items():
        if not e.startswith("grunnstoff") or v is None:
            continue
        el = e[len("grunnstoff"):]
        v = float(v)
        if v == 0: stats["zero value"] += 1; continue
        if v < 0:
            results.append([k, f"NGU-AR-ICPMS-{lab}", el, "ppm", "<", -v, -v, "NGU: negative value = below detection limit", frac]); stats["below detection"] += 1
        else:
            results.append([k, f"NGU-AR-ICPMS-{lab}", el, "ppm", None, v, None, None, frac])
        stats["results " + lab] += 1
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
c.execute("SELECT method_id FROM geochem.analytical_methods WHERE method_code = 'AR-ICPMS'")
mid = c.fetchone()[0]
for lab, name in (("ACME", "ACME (Vancouver)"), ("ALS", "ALS"), ("BV", "Bureau Veritas")):
    pk = f"NGU-AR-ICPMS-{lab}"
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = %s),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pk, f"NGU soil geochemistry, aqua regia ICP-AES/MS, {name}", lab, mid,
               f"NGU (Geological Survey of Norway) regional/local mineral-soil surveys: 15 g sample, aqua regia digestion (partial), ICP-AES/MS at {name}", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'P', 1, 'NGU aqua regia' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (pk,))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, 'P', 1, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, "NGU aqua regia (partial) " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date, frac text",
     samples.values())
copy("st_result", "k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, comment text, fraction text", results)
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
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
if CHECK:
    c.execute("SELECT pkg, count(*), count(*) FILTER (WHERE qual = '<') FROM st_result GROUP BY 1"); log("per package", c.fetchall())
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
 VALUES (%s, %s, now(), now(), %s, 'rule-based classification at load (NGU negative value = below detection)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "Geological Survey of Norway (NGU)",
           "NGU inorganic soil geochemistry (Prøvepunkter geokjemi, samples_inorganic; 13 regional/local mineral-soil surveys 1980-2025)",
           "NLOD 2.0 (Norwegian Licence for Open Government Data; compatible with CC BY 4.0)", "https://data.norge.no/nlod/en/2.0/",
           "Contains data under the Norwegian licence for Open Government data (NLOD) made available by the Geological Survey of Norway (NGU).",
           "Cleared: NGU data policy (NGU data and products under NLOD, commercial use allowed) and the API licence link NLOD 2.0, checked 2026-11-14. Loaded 2026-11-14.",
           "Aqua regia (partial) ICP-AES/MS only, three laboratories over 1980-2025: compare within one survey and laboratory; field year only; served from NGU's 'geotest' API (test dataset label).",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\NGU_Norway\ (data policy page, API root, EVIDENCE.md)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG)
g.close()
