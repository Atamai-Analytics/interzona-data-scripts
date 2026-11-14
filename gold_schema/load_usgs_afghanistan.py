"""USGS pre-mining environmental baseline geochemistry of Afghan deposits (Aynak and Balkhab copper, Hajigak and Nuqra Khana iron; 2019 and
2020 field seasons; ScienceBase releases, metadata Access/Use constraints none, 2020 releases marked CC0 1.0) -> interzona_cm gold, new
source AFGHANISTAN_USGS_BASELINE (own partitions, rollback = delete by created_by = TAG).
Input: D:/CriticalMineralsDB/Afghanistan/USGS_20261114/<release>/ (downloaded 2026-11-14 with the user's approval).
What is loaded: SOLID samples only (rock, sediment, soil, mine waste); water samples, reference materials, blanks, QC rows ('N/a') and field
duplicates are left out. Columns 'C_<method>_<analyte>_<unit>' (2020) or 'C_<method> <analyte> (<unit>)' (2019); AGAT Laboratories:
ICPOES_MS-49 four-acid ICP-OES/MS, ICPOES_MS-60 sodium peroxide fusion ICP-OES/MS, WDXRF-MAJORS fused-disk XRF majors + LOI, FA_AU-PD-PT
fire assay, CO2-CARB carbonate CO2, TOTAL-C / TOTAL-S LECO. '<x' -> qualifier '<' with limit x; '>x' -> '>' (upper limit x). Carbonate
carbon (CRBNT_C) and organic carbon are left out (CO2 and total C kept).
comments start 'USGS baseline <deposit> <season>' (Geostatistics survey key).
Usage: python load_usgs_afghanistan.py [--check]
"""
import os, sys, io, csv, re, glob, time, datetime, collections
import psycopg2
import pandas as pd

CHECK = "--check" in sys.argv
TAG = "migration_usgs_afghanistan_20261114"
SRC = "AFGHANISTAN_USGS_BASELINE"
PART = "afghanistan_usgs_baseline"
XID = "USGS_AFG_BASELINE_SAMPLE"
D = "D:/CriticalMineralsDB/Afghanistan/USGS_20261114/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
# method -> (package code, gold method code, basis, priority, description)
METH = {
    "ICPOES_MS-60": ("USGS-AFG-NAPEROX-ICPMS", "NAPEROX-ICPMS", "T", 1, "Sodium peroxide fusion, ICP-OES/MS (60 elements), AGAT Laboratories"),
    "ICPOES_MS-49": ("USGS-AFG-4A-ICPMS", "4A-ICPMS", "T", 2, "Four-acid digestion, ICP-OES/MS (49 elements), AGAT Laboratories"),
    "WDXRF-MAJORS": ("USGS-AFG-XRF", "LIBOR-XRF", "T", 1, "Fused-disk wavelength-dispersive XRF major oxides and LOI"),
    "FA_AU-PD-PT": ("USGS-AFG-FA", "FA-ICPMS", "T", 1, "Fire assay Au, Pd, Pt"),
    "FA_TRACE_AU-PD-PT": ("USGS-AFG-FA", "FA-ICPMS", "T", 1, "Fire assay Au, Pd, Pt"),
    "CO2-CARB": ("USGS-AFG-CO2", "NONE-LECO", "T", 1, "Carbonate CO2 (acid release, infrared detection)"),
    "TOTAL-C": ("USGS-AFG-LECO", "NONE-LECO", "T", 1, "Total carbon and total sulfur by combustion (LECO)"),
    "TOTAL-S": ("USGS-AFG-LECO", "NONE-LECO", "T", 1, "Total carbon and total sulfur by combustion (LECO)"),
}
SKIP_METH = {"TRACE-H2O", "ORGANIC-C"}
SKIP_AN = {"CRBNT_C"}
UNIT = {"%": "%", "wt%": "%", "ppm": "ppm", "ppb": "ppb"}
TYPES = {"rock": "ROCK_SAMPLE", "sediment": "SEDIMENT_SAMPLE", "soil": "SOIL_SAMPLE", "mine waste": "TAILINGS_GENERAL"}
COLRE = re.compile(r"^C_(" + "|".join(re.escape(m) for m in sorted(set(METH) | SKIP_METH, key=len, reverse=True)) +
                   r")[ _](.+?)[ _]\(?(%|wt%|ppm|ppb|ppt|per mil|mg/L|ug/L|uS/cm)\)?$")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def deposit_season(path):
    m = re.search(r"(Aynak|Balkhab|Haji-?gak|Nuqra_Khana)", os.path.basename(path), re.I)
    dep = m.group(1).replace("Haji-gak", "Hajigak").replace("_", " ").title().replace("Hajigak", "Hajigak")
    s = re.search(r"20(19|20)", os.path.basename(path)).group(0)
    return dep, s


def pdate(v):
    if v is None or str(v).strip() in ("", "nan"): return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y"):
        try: return datetime.datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except ValueError: pass
    return None


stats = collections.Counter()
samples, results = {}, []
files = [f for f in glob.glob(D + "*/*") if f.endswith((".csv", ".xlsx")) and "water" not in f.lower() and "Afghan_" not in os.path.basename(f)]
for f in sorted(files):
    dep, season = deposit_season(f)
    df = pd.read_csv(f, encoding="utf-8-sig", dtype=str) if f.endswith(".csv") else pd.read_excel(f, dtype=str)
    df = df.fillna("")
    df.columns = [c.strip() for c in df.columns]
    idc = "Sample ID" if "Sample ID" in df.columns else "Sample identifier"
    for _, r in df.iterrows():
        typ = (r.get("Sample type") or "").strip().lower()
        if typ not in TYPES: stats["skipped type " + (typ[:30] or "blank")] += 1; continue
        sid = str(r[idc]).strip()
        try: lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except (TypeError, ValueError): stats["no position"] += 1; continue
        assert 29 < lat < 39 and 60 < lon < 75, (sid, lat, lon)
        k = f"{dep}|{season}|{sid}"
        assert k not in samples, k
        note = "; ".join(x for x in [f"USGS baseline {dep} {season}", f"{dep} deposit pre-mining environmental baseline, {season} field season",
                                     str(r.get("Notes") or r.get("Description") or "").strip()[:200].replace("nan", ""),
                                     f"job {r['Job number']}" if "Job number" in df.columns and str(r.get("Job number")) not in ("nan", "None") else ""] if x)
        samples[k] = [k, TYPES[typ], f"USGS Afghanistan baseline: {typ}"[:100], lat, lon, sid, sid, note, "SURFACE", pdate(r.get("Date"))]
        stats["samples " + TYPES[typ]] += 1
        for col in df.columns:
            if not col.startswith("C_"): continue
            m = COLRE.match(col)
            assert m, ("unparsed column", col)
            meth, an, unit = m.group(1), m.group(2).strip(), m.group(3)
            if meth in SKIP_METH or an in SKIP_AN: continue
            v = r[col]
            if v is None or str(v).strip() in ("", "nan", "OK", "ID", "--"): continue
            v = str(v).strip()
            q, ldl, udl = None, None, None
            if v.startswith("<"): q = "<"; v = v[1:]
            elif v.startswith(">"): q = ">"; v = v[1:]
            try: x = float(v)
            except ValueError: stats["bad value " + v[:10]] += 1; continue
            if x <= 0 and q is None: stats["zero or negative"] += 1; continue
            if q == "<": ldl = x
            if q == ">": udl = x
            pkg = METH[meth][0]
            results.append([k, pkg, {"LOI": "LOI"}.get(an, an), UNIT[unit], q, x, ldl, udl, f"USGS method {meth}"])
            stats["below detection" if q == "<" else "above range" if q == ">" else "detected"] += 1
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
for meth, (pk, mcode, basis, prio, desc) in METH.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""", (pk, f"USGS Afghanistan baseline: {desc}", mcode,
                 f"USGS pre-mining environmental baseline (Afghanistan, 2019-2020): {desc}", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'USGS Afghanistan baseline' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""",
              (basis, prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "USGS Afghanistan baseline " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date", samples.values())
copy("st_result", "k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric, comment text", results)
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
if CHECK:
    c.execute("SELECT pkg, count(*), count(*) FILTER (WHERE qual = '<') FROM st_result GROUP BY 1"); log("per package", c.fetchall())
    g.rollback(); g.close(); log("CHECK RUN - rolled back"); sys.exit(0)
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  'AGAT Laboratories (USGS contract)', meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, r.udl, NULL, NULL, false, true, '{TAG}', now(),
  NULL, NULL, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
log("results inserted", nins, "of", len(results))
assert nins == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UDL' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'rule-based classification at load (< / > qualifiers)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "U.S. Geological Survey",
           "Pre-mining environmental baseline characterization of the Aynak and Balkhab copper and Hajigak and Nuqra Khana iron deposits, Afghanistan (2019 and 2020 field seasons; solid samples)",
           "US public domain / CC0 1.0 (ScienceBase; metadata Access and Use constraints none)", "https://creativecommons.org/publicdomain/zero/1.0/",
           "Source: U.S. Geological Survey pre-mining environmental baseline data releases for Aynak, Balkhab, Hajigak and Nuqra Khana, Afghanistan (2019-2020).",
           "Cleared: ScienceBase metadata Access/Use constraints none; 2020 releases marked CC0 1.0 - checked 2026-11-14.",
           "Deposit-scale baseline sampling around four deposits only (not regional coverage); water samples, reference materials and duplicates not loaded.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\USGS_AFGHANISTAN\ (metadata, EVIDENCE.md)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG)
c.execute(f"ANALYZE geochem.analytical_results_{PART}"); c.execute(f"ANALYZE geochem.result_classifications_{PART}"); g.commit()
g.close()
