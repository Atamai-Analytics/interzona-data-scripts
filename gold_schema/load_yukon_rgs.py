"""Yukon Geological Survey - Regional Geochemical Surveys (RGS) stream-sediment compilation (Nov 2020) -> interzona_cm gold.
New source YUKON_YGS_RGS (own partition; rollback = delete by created_by = TAG, then supersede_cdogs_yukon.py --undo).
Licence: Open Government Licence - Yukon v2.0 (commercial use allowed, attribution). Evidence: Licence_Evidence/YUKON_YGS_RGS/LICENCE_NOTES.md.
File: D:/CriticalMineralsDB/Yukon/Regional_Geochemical_Surveys_RGS_All_250k.fgdb.zip (map-data.service.yukon.ca, downloaded 2026-11-16),
extracted to D:/CriticalMineralsDB/Yukon/_x; layer Regional_Geochemical_Surveys_RGS_All_250k = RGS_All (all AAS, INAA and ICP-MS results), 31,380 samples.

Samples: -80 mesh (<0.177 mm) stream sediments collected 1976-2006 by GSC / YGS regional surveys; ~24,000 reanalysed by aqua regia ICP-MS (YGS Open
Files 2011-2016). 27,764 of them are also in CDoGS (CANADA_NRCAN_CDOGS) with only the original AAS/INAA results: supersede_cdogs_yukon.py switches
those CDoGS copies off so each site is counted once.
Packages (one per method family):
  YGS_RGS_ICPMS   aqua regia ICP-MS reanalysis            partial  priority 1
  YGS_RGS_INAA    INAA (and FA-NA for Au)                 total    priority 2
  YGS_RGS_FAAAS   Au fire assay - AAS (2 determinations)  total    priority 2
  YGS_RGS_DNC     U delayed neutron counting              total    priority 2
  YGS_RGS_FUS     F fusion-ISE, W colorimetric, Sn fusion total    priority 4
  YGS_RGS_AAS     AAS after Lefort aqua regia / hot HNO3  partial  priority 3
  YGS_RGS_HGAAS   As, Sb hydride AAS; Hg cold-vapour AAS  partial  priority 3
Value conventions (checked against the data): -9999 = not analysed (skipped); other negative values = below the detection limit |v| (YGS sign
convention) -> BELOW_DL_QUALIFIED, dl |v|; a method block that is 0 or empty in every column for a sample = not analysed (skipped);
other zeros (old AAS/INAA/fusion columns) = below detection with no limit given -> BELOW_DL_QUALIFIED, dl = the lowest positive value reported
in that column (dl_source INFERRED_COLUMN_MIN_POSITIVE), except the second Au fire-assay determination (AU2_AAS_FA_PPB), where 0 = not done
(skipped). Empty columns AU_INA_WT and ND_INA_SS not loaded. No per-sample dates (survey year in comments).
Usage: python load_yukon_rgs.py [--check]
"""
import os, sys, io, csv, time, collections
import psycopg2, pyogrio, warnings
warnings.filterwarnings("ignore")

CHECK = "--check" in sys.argv
TAG = "migration_yukon_rgs_20261116"
SRC, PART, XID = "YUKON_YGS_RGS", "yukon_ygs_rgs", "YGS_RGS_SAMPLE_ID"
GDB = "D:/CriticalMineralsDB/Yukon/_x/Regional_Geochemical_Surveys_RGS_All_250k.gdb"
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


# code -> (name, method_code, basis, priority, description)
PKGS = {
    "YGS_RGS_ICPMS": ("Yukon RGS stream sediments - aqua regia ICP-MS reanalysis", "AR-ICPMS", "P", 1,
                      "Reanalysis of archived -80 mesh RGS stream sediments by aqua regia digestion and ICP-MS (YGS Open Files 2011-2016); partial digestion"),
    "YGS_RGS_INAA": ("Yukon RGS stream sediments - INAA / FA-NA", "NONE-INAA", "T", 2,
                     "Instrumental neutron activation analysis of 5-40 g -80 mesh sediment (Au also by fire assay - neutron activation); total"),
    "YGS_RGS_FAAAS": ("Yukon RGS stream sediments - Au fire assay AAS", "FA-AAS", "T", 2,
                      "Gold by fire assay with AAS finish on original RGS samples; two determinations where reported"),
    "YGS_RGS_DNC": ("Yukon RGS stream sediments - U delayed neutron counting", "NONE-DNC", "T", 2, "Uranium by delayed neutron counting"),
    "YGS_RGS_FUS": ("Yukon RGS stream sediments - fusion methods (F, W, Sn)", "FUS-ISE", "T", 4,
                    "F by fusion and ion-selective electrode, W by colorimetry, Sn by fusion; original RGS analyses"),
    "YGS_RGS_AAS": ("Yukon RGS stream sediments - AAS (Lefort aqua regia / hot nitric)", "UNKNOWN-UNKNOWN", "P", 3,
                    "Original RGS AAS after Lefort aqua regia or concentrated hot nitric acid digestion (partial); superseded by ICP-MS where both exist"),
    "YGS_RGS_HGAAS": ("Yukon RGS stream sediments - hydride / cold-vapour AAS", "MX-HGAAS", "P", 3,
                      "As and Sb by hydride-generation AAS, Hg by cold-vapour AAS (original RGS analyses)"),
}
UNIT = {"PPM": "ppm", "PPB": "ppb", "PCT": "%"}


def column_map(col):
    """-> (package, analyte, unit, block) or None"""
    p = col.split("_")
    el = p[0].capitalize()
    if col == "AU2_AAS_FA_PPB": return ("YGS_RGS_FAAAS", "Au", "ppb", "LEG")
    if col == "AU_AAS_FA_PPB": return ("YGS_RGS_FAAAS", "Au", "ppb", "LEG")
    if col in ("AU_INA_WT", "ND_INA_SS"): return None
    if col == "SN_INA_PPM_FUSION": return ("YGS_RGS_FUS", "Sn", "ppm", "INA")
    meth, unit = p[1], UNIT[p[-1]]
    return {"ICP": ("YGS_RGS_ICPMS", "ICP"), "INA": ("YGS_RGS_INAA", "INA"), "AAS": ("YGS_RGS_AAS", "LEG"), "AAH": ("YGS_RGS_HGAAS", "LEG"),
            "CV": ("YGS_RGS_HGAAS", "LEG"), "NAD": ("YGS_RGS_DNC", "LEG"), "FUSION": ("YGS_RGS_FUS", "LEG"), "ISE": ("YGS_RGS_FUS", "LEG"),
            "CLR": ("YGS_RGS_FUS", "LEG")}[meth][0:1] + (el, unit) + ({"ICP": "ICP", "INA": "INA"}.get(meth, "LEG"),)


df = pyogrio.read_dataframe(GDB, read_geometry=False)
META = ["OPEN_FILE_ORIGINAL", "OPEN_FILE_REANALYSIS", "SAMPLE_ID", "NTS_MAP250K", "YEAR", "SAMPLE_NUMBER", "REPEAT_STATION", "LATITUDE_DD", "LONGITUDE_DD"]
cols = {c: column_map(c) for c in df.columns if c not in META}
cols = {c: m for c, m in cols.items() if m}
colmin = {c: float(df[c][df[c] > 0].min()) for c in cols}
blocks = collections.defaultdict(list)
for c, m in cols.items(): blocks[m[3]].append(c)
log("columns", len(cols), {b: len(v) for b, v in blocks.items()})

stats = collections.Counter()
samples, results = [], []
for r in df.itertuples(index=False):
    d = r._asdict()
    sid = d["SAMPLE_ID"].strip()
    lat, lon = float(d["LATITUDE_DD"]), float(d["LONGITUDE_DD"])
    assert 59.9 < lat < 69.7 and -141.1 < lon < -123.8, (sid, lat, lon)
    note = "; ".join(x for x in [
        "Yukon Geological Survey regional stream-sediment compilation (RGS, 2020), -80 mesh (<0.177 mm)",
        f"original survey {d['OPEN_FILE_ORIGINAL']}" if d["OPEN_FILE_ORIGINAL"] else "",
        f"ICP-MS reanalysis {d['OPEN_FILE_REANALYSIS']}" if d["OPEN_FILE_REANALYSIS"] else "",
        f"NTS {d['NTS_MAP250K']}", f"survey year {d['YEAR']}" if d["YEAR"] else "",
        "repeat station" if d["REPEAT_STATION"] == 1 else ""] if x)
    samples.append([sid, lat, lon, sid, str(d["SAMPLE_NUMBER"]), note[:1000]])
    stats["samples"] += 1
    for b, bcols in blocks.items():
        vals = [d[c] for c in bcols]
        live = [v for v in vals if v == v and v is not None and v != -9999]
        if not live or all(v == 0 for v in live):
            stats[f"block {b} not analysed"] += 1; continue
        for c in bcols:
            v = d[c]
            if v != v or v is None or v == -9999: continue
            if c == "AU2_AAS_FA_PPB" and v == 0:  # 0 in 95% of rows = no second determination, not below detection
                stats["AU2 zero (no second determination) skipped"] += 1; continue
            pkg, el, unit, _ = cols[c]
            cm = "second determination" if c.startswith("AU2_") else None
            if v < 0:
                results.append([sid, pkg, el, unit, -v, -v, "<", cm, "B", "NEGATIVE_CONVENTION"]); stats[f"{pkg} below DL (negative)"] += 1
            elif v == 0:
                results.append([sid, pkg, el, unit, colmin[c], colmin[c], "ND", cm, "B", "INFERRED_COLUMN_MIN_POSITIVE"]); stats[f"{pkg} below DL (zero)"] += 1
            else:
                results.append([sid, pkg, el, unit, float(v), None, None, cm, "D", None]); stats[f"{pkg} detected"] += 1
log("staged samples", len(samples), "results", len(results))
for k in sorted(stats): log(f"  {k}: {stats[k]:,}")

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor()
c.execute("SELECT analyte_code FROM geochem.analytes")
known = {a for (a,) in c.fetchall()}
miss = sorted({r[2] for r in results} - known)
assert not miss, ("unknown analytes", miss)
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, SRC + " already has samples: delete them by created_by first"
if not CHECK:
    g.commit(); g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0")

for pk, (name, mcode, basis, prio, desc) in PKGS.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""", (pk, name, mcode, desc, TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'Yukon RGS' FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""", (basis, prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "Yukon RGS " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"DROP TABLE IF EXISTS {table}")
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql})")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, lat float8, lon float8, field_no text, sample_no text, comments text", samples)
copy("st_result", "k text, pkg text, analyte text, unit text, val numeric, dl numeric, q text, comment text, st text, dls text", results)
for label, sql in [("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("method", "SELECT p.package_code FROM geochem.analytical_packages p WHERE p.package_code LIKE 'YGS_RGS_%' AND p.method_id IS NULL"),
                   ("qualifier", "SELECT DISTINCT r.q FROM st_result r LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.q WHERE r.q IS NOT NULL AND q.qualifier_id IS NULL")]:
    c.execute(sql); m = [r[0] for r in c.fetchall()]
    assert not m, (label, m)
c.execute("DROP TABLE IF EXISTS st_map")
c.execute("""CREATE TEMP TABLE st_map AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments,
  is_active, created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.field_no, t.sample_type_id, 'Yukon RGS stream sediment (-80 mesh)',
  'SURFACE', s.comments, true, '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = 'SED_STREAM'""")
log("samples inserted", c.rowcount, "| without results", len(samples) - c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
c.execute("SELECT pkg, st, count(*) FROM st_result GROUP BY 1, 2 ORDER BY 1, 2"); log("per package/status", c.fetchall())
if CHECK:
    g.rollback(); g.close(); log("CHECK RUN - rolled back"); sys.exit(0)

c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, r.q,
  'Not recorded (GSC / YGS contract laboratories)', meth.method_code, p.package_name, meth.digest_name,
  r.val, r.dl, NULL, NULL, NULL, false, true, '{TAG}', now(), r.st || '|' || coalesce(r.dls, ''), '-80 mesh (<0.177 mm)', r.comment
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
  CASE split_part(r.source_result_id, '|', 1) WHEN 'B' THEN 'BELOW_DL_QUALIFIED' ELSE 'DETECTED' END,
  r.lower_detection_limit, nullif(split_part(r.source_result_id, '|', 2), ''),
  split_part(r.source_result_id, '|', 1) = 'D'
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute(f"UPDATE geochem.analytical_results_{PART} SET source_result_id = NULL")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, %s)
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""",
          (SRC, "rule_" + TAG, nins, "negative value -> BELOW_DL_QUALIFIED dl |v|; zero (outside an all-zero method block) -> BELOW_DL_QUALIFIED, "
                                     "dl = lowest positive value in the column; -9999 and all-zero method blocks not loaded"))

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "Yukon Geological Survey (Government of Yukon)",
           "Regional Geochemical Surveys (RGS) - All - 250k: Yukon regional stream-sediment geochemistry compilation (Nov 2020), 31,380 samples "
           "collected 1976-2006, original AAS / INAA / fire-assay results and aqua regia ICP-MS reanalyses",
           "Open Government Licence - Yukon", "https://yukon.ca/en/your-government/open-government/open-government-licence-yukon",
           "Yukon Geological Survey, 2020. Regional Geochemical Surveys (RGS) - All - 250k. Contains information licensed under the Open Government Licence - Yukon.",
           "Cleared: dataset page open.yukon.ca lists Open Government Licence - Yukon (v2.0 allows commercial use with attribution; read 2026-11-16). "
           "Original samples largely collected by the Geological Survey of Canada (Open Government Licence - Canada).",
           "Stream sediments only (-80 mesh). Aqua regia ICP-MS is a partial digestion (Al, Ba, Cr, Fe, P, Sn, Ti, Y, Zr under-reported; Au by ICP-MS imprecise); "
           "original AAS is partial and superseded by ICP-MS where both exist. Zero values in the old AAS/INAA columns are loaded as below detection with "
           "the column's lowest reported value as the limit. No sample dates (survey year in the comments). 27,764 of these sites are also in the "
           "federal CDoGS compilation; those CDoGS copies were switched off so each site counts once.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\YUKON_YGS_RGS\ (LICENCE_NOTES.md, metadata)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG)
g.close()
