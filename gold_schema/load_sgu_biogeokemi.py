"""SGU Biogeokemi, regional provtagning (Swedish stream-plant geochemistry, CC0 1.0) -> interzona_cm gold, source SWEDEN_SGU_BIOGEOKEMI.

Input: D:/CriticalMineralsDB/Sweden/download_20261107/biogeokemi-regional/extracted/biogeokemi_regional.gpkg (biogeokemi-regional.zip, SGU
last-modified 2024-05-27, downloaded 2026-11-07; product description saved beside it; evidence in Documents/Licence_Evidence/SGU_Sweden).
What it is: roots of sedges (Carex) and meadowsweet (Filipendula ulmaria) and whole aquatic moss (Fontinalis antipyretica) from small streams,
about 1 sample per 7 km2, 1982-2005; species is not recorded per sample. Plants were ashed (Hg/Se samples air-dried); XRF and aqua-regia values are
recalculated by SGU to DRY-WEIGHT concentrations using each sample's ash content. Plant values are not comparable with soil, till or rock values.
Rules: as load_sgu_markgeokemi.py ('0' = not analysed; negative = below the limit of determination; implausible negatives left out and logged).
One sample per IDKOD+IDNR; sample type VEGETATION_SAMPLE; ash content kept in comments.
Not loaded: backvattenvaxter_askhalter (SGU's Fe/Mn/organic-corrected index, negatives set to 0 - a derived product) and ph_rinnandevatten (stream pH).
Usage: python load_sgu_biogeokemi.py [--check]
"""
import os, sys, io, csv, re, time, struct, sqlite3, collections
import psycopg2
from pyproj import Transformer

CHECK = "--check" in sys.argv
TAG = "migration_sgu_biogeokemi_20261107"
SRC = "SWEDEN_SGU_BIOGEOKEMI"
PART = "sweden_sgu_biogeokemi"
XID = "SGU_BIOGEOKEMI"
GEO = "D:/CriticalMineralsDB/Sweden/download_20261107/biogeokemi-regional/extracted/biogeokemi_regional.gpkg"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# table -> (package code, package name, method code, basis, priority, fraction, lab note)
TABLES = {
    "backvattenvaxter_totalhalt": ("SGU-BIO-XRF", "SGU - stream plants, XRF on pressed pellets of ashed plant, recalculated to dry weight", "NONE-XRF", "T", 2,
                                   "plant, dry weight", "SGU regional biogeochemical mapping (ashed sample, XRF)"),
    "backvattenvaxter_kungsvattenlakning": ("SGU-BIO-AR-ICPMS", "SGU - stream plants, aqua regia (ashed plant) with ICP-MS, recalculated to dry weight", "AR-ICPMS", "P", 1,
                                            "plant, dry weight", "SGU laboratory (Elan 5000)"),
    "backvattenvaxter_salpetersyralakning": ("SGU-BIO-HNO3", "SGU - stream plants, 7M nitric acid (air-dried plant) with AAS (Hg) / ICP-MS (Se)", "HNO3-ICPMS", "P", 1,
                                             "plant, dry weight", "SGU laboratory"),
}
UNIT = {"ppm": "ppm", "ppb": "ppb", "proc": "%", "procent": "%"}
STYPE = [("morän", "TILL_SAMPLE"), ("sediment", "SEDIMENT_SAMPLE"), ("ytprov", "SOIL_SAMPLE")]
ANALYTE_FIX = {"al2o3": "Al2O3", "bao": "BaO", "cao": "CaO", "fe2o3": "Fe2O3", "k2o": "K2O", "mgo": "MgO", "mno": "MnO", "na2o": "Na2O",
               "p2o5": "P2O5", "sio2": "SiO2", "tio2": "TiO2"}
t3006 = Transformer.from_crs(3006, 4326, always_xy=True)


def gpkg_point(blob):
    """(x, y) from a GeoPackage point geometry blob, else None."""
    if not blob or blob[:2] != b"GP": return None
    flags = blob[3]; env = (flags >> 1) & 7
    off = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    bo = "<" if blob[off] == 1 else ">"
    if struct.unpack(bo + "I", blob[off + 1:off + 5])[0] % 1000 != 1: return None
    return struct.unpack(bo + "dd", blob[off + 5:off + 21])


geo = sqlite3.connect(f"file:{GEO}?mode=ro", uri=True); geo.row_factory = sqlite3.Row
samples, stats, odd_log = {}, collections.Counter(), []
res_path = os.path.join(HERE, "_sgu_biogeokemi_results.csv")
fh = open(res_path, "w", newline="", encoding="utf-8"); w = csv.writer(fh)
for t, (pkg, _, _, _, _, frac, _) in TABLES.items():
    cols = [r[1] for r in geo.execute(f'PRAGMA table_info("{t}")')]
    vcols = [(cn, m.group(1), m.group(2)) for cn in cols for m in [re.match(r"^([a-z0-9]+)_(ppm|ppb|proc|procent)$", cn)] if m]
    common = {}
    for cn, _, _ in vcols:
        r = geo.execute(f'SELECT "{cn}", count(*) FROM "{t}" WHERE "{cn}" < 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 1').fetchone()
        common[cn] = abs(r[0]) if r else None
    nsg = t.endswith("nsg_sgab")
    for r in geo.execute(f'SELECT * FROM "{t}"'):
        key = f"{r['idkod']}.{r['idnr']}"
        if key not in samples:
            x, y = r["ew"], r["ns"]
            if not (x and y):
                p = gpkg_point(r["geom"]); x, y = (p if p else (None, None))
            if not (x and y): stats["sample without position"] += 1; samples[key] = None; continue
            lon, lat = t3006.transform(float(x), float(y))
            if not (10.5 < lon < 24.5 and 55 < lat < 69.2):
                stats["sample outside Sweden (mistyped coordinates, left out)"] += 1; odd_log.append((t, key, "position", f"{y} N {x} E")); samples[key] = None; continue
            pt = (r["provtyp"] or "")
            st = "VEGETATION_SAMPLE"
            yr = r["prov_artal"]
            acc = "±50 m" if yr and int(yr) <= 1997 else ("±10 m" if yr else None)
            ash = r["askhalt_pr"] if "askhalt_pr" in r.keys() else None
            samples[key] = [key, st, "SGU stream plants (Carex/Filipendula roots or Fontinalis moss), dry weight", lon, lat,
                            "; ".join(x for x in [f"sampled {yr}" if yr else "", f"SGU sample {key}", f"ash content {ash} %" if ash else "",
                                                  f"position {acc} (SGU)" if acc else ""] if x)]
        if samples[key] is None: continue
        for cn, el, un in vcols:
            v = r[cn]
            if v is None or v == 0: stats["zero / empty (not analysed)"] += 1; continue
            code = ANALYTE_FIX.get(el, el.capitalize())
            if v < 0:
                if common[cn] and abs(v) > 100 * common[cn]:
                    stats[f"left out: implausible negative {t}.{cn}"] += 1; odd_log.append((t, key, cn, v)); continue
                q, val, ldl = "<", abs(v), abs(v); stats["below limit"] += 1
            else:
                q, val, ldl = None, v, None
            w.writerow([key, pkg, code, UNIT[un], q or N, val, ldl if ldl is not None else N, frac, N, f"SGU table {t}"])
            stats["values"] += 1
fh.close()
samples = {k: v for k, v in samples.items() if v}
log("samples", len(samples), "| types", collections.Counter(v[1] for v in samples.values()))
log("results staged", {k: v for k, v in stats.items()})
with open(os.path.join(HERE, "sgu_biogeokemi_left_out.csv"), "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows([("table", "sample", "column", "value")] + odd_log)

# ---------------------------------------------------------------- gold
if not CHECK:
    p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
    p0.autocommit = True
    p0.cursor().execute("SET lock_timeout = '20s'")
    p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_{PART} PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
    p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_{PART} PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
    p0.close()
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"],
                     keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor()
c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); cw = csv.writer(buf)
    for r in data: cw.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0); c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "skey text, stype text, stype_local text, lon double precision, lat double precision, comments text", samples.values())
c.execute("""CREATE TEMP TABLE st_result (skey text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, fraction text, x text, comment text)
             ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as f:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", f)
c.execute("SELECT count(*) FROM st_result"); nres = c.fetchone()[0]
assert nres == stats["values"], (nres, stats["values"])

# method + packages
c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, digest_chemical_formula, digest_temp_celsius,
             digest_completeness, digest_volatilisation, digest_resistant_to, digest_description, instrument_code, instrument_name, instrument_description,
             application, notes, is_active, created_by, created_date)
             SELECT 'HNO3-ICPMS', 'Nitric Acid Digest / ICP-MS', 'HNO3', 'Nitric Acid', 'HNO3', 200, 'Partial', 'Low', 'Most silicates and resistant minerals',
                    'Partial leach in hot nitric acid (SGU: 2 g in 10 ml 7M HNO3 on a hot plate). Does not attack silicates.', 'ICP-MS',
                    'Inductively Coupled Plasma Mass Spectrometry', 'Multi-element trace analysis.', 'Trace elements (soil, till, sediment)',
                    'Added for SGU Markgeokemi (Swedish standard SS 028183, modified).', true, %s, now()
             WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = 'HNO3-ICPMS')""", (TAG,))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
for t, (pkg, name, mcode, basis, prio, frac, lab) in TABLES.items():
    if not name: continue
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pkg, name, mid[mcode], f"SGU Markgeokemi, regional sampling: {lab}", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'SGU Markgeokemi' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, pkg))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "SGU table mapping " + TAG, pkg))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
log("dictionary checks passed")

c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.skey, nextval('geochem.samples_sample_id_seq') AS sample_id,
             ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326) AS pt FROM st_sample s WHERE EXISTS (SELECT 1 FROM st_result r WHERE r.skey = s.skey)""")
c.execute("CREATE UNIQUE INDEX ON st_map (skey)")
c.execute(f"""INSERT INTO geochem.samples (sample_id, geom, sample_number, sample_type_id, sample_type_local, sample_context, comments, is_active,
  created_by, created_date, source_system) OVERRIDING SYSTEM VALUE
  SELECT m.sample_id, m.pt, s.skey, t.sample_type_id, s.stype_local, 'SURFACE', nullif(s.comments, ''), true, '{TAG}', now(), '{SRC}'
  FROM st_sample s JOIN st_map m USING (skey) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', skey, '{TAG}', now() FROM st_map""")
c.execute(f"SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}' AND (lat NOT BETWEEN 55 AND 69.2 OR lon NOT BETWEEN 10.5 AND 24.5)")
log("samples outside Sweden box (must be 0)", c.fetchone()[0])
c.execute("SELECT pkg, analyte, count(*), count(*) FILTER (WHERE qual = '<') FROM st_result GROUP BY 1,2 ORDER BY 1,2")
per = collections.defaultdict(list)
for pkg, an, n, nb in c.fetchall(): per[pkg].append(f"{an} {n}" + (f" ({round(100 * nb / n)}% <)" if nb else ""))
for pkg, lst in per.items(): log(pkg, len(lst), "analytes:", ", ".join(lst))
if CHECK:
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back before the result rows"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, p.package_name, NULL, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(), NULL, r.fraction, r.comment
FROM st_result r JOIN st_map m ON m.skey = r.skey JOIN geochem.analytes a ON a.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results_{PART}"); ngr = c.fetchone()[0]
log("gold results", ngr, "of", nres); assert ngr == nres
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_sgu_biogeokemi_20261107', now(), now(), count(*), 'rule-based classification at load (SGU negative = below limit)'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,false,%s,true,%s,%s,%s,'2026-11-07',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Geological Survey of Sweden (SGU)", "Biogeokemi, regional provtagning (stream-plant geochemistry), GeoPackage, SGU last modified 2024-05-27",
           "CC0 1.0 Universal (public domain dedication)", "https://www.sgu.se/produkter-och-tjanster/geologiska-data/om-geologiska-data/licensvillkor/",
           "Source: Geological Survey of Sweden (SGU), Biogeokemi regional provtagning, CC0 1.0. Attribution is not required under CC0 and is given as a courtesy.",
           "Cleared: CC0 1.0 stated in the product description and SGU licence page (checked 2026-11-07). Loaded 2026-11-07.",
           "Stream-plant samples (roots and aquatic moss), dry-weight concentrations recalculated by SGU from ashed material; NOT comparable with soil, till or rock. "
           "Reflects stream-water chemistry, including pollution (old mine waste, acid deposition). Species not recorded per sample. Ash-corrected index and stream pH not loaded.",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/SGU_Sweden/EVIDENCE.md", TAG))
g.commit(); log("COMMITTED"); g.close(); os.remove(res_path)
