"""NURE Hydrogeochemical and Stream Sediment Reconnaissance (HSSR) sediment data, USGS reformatted release (Smith 1997, USGS Open-File Report
97-492, version 1.40; https://mrdata.usgs.gov/nure/sediment/; metadata: Access_Constraints None, Use_Constraints None) -> interzona_cm gold,
new source USA_NURE_HSSR (own partitions, rollback = delete by created_by = TAG).

Input: D:/CriticalMineralsDB/USA/nure_hssr_20261113/nuresed.csv (downloaded 2026-11-13 with the user's approval; one row per sample, one column
per element). Conventions from the metadata (nurehssr.met): negative value = below the detection limit (-2 in AG_PPM = <2 ppm Ag); coordinates
NAD27 (converted to WGS84 with pyproj); the DOE laboratory responsible is in DOELAB; METHODS lists the laboratory's method codes used for the
record (per record, not per element), so except for uranium (separate columns per method) the element method is recorded as the laboratory's
multi-element method family.
What is loaded
  - original records only: replicate records are left out (REPLC other than 0 / 000 / blank; for LLL also 100 is an original)
  - every element column with a value; zero values left out; PO4 / SO4 and descriptive fields left out (field descriptions go into comments)
  - packages NURE-<lab>-<U_DN|U_FL|U_MS|U_NA|U_XX|MULTI>; total basis assumed (instrumental neutron activation, DNC, XRF and emission methods);
    uranium by delayed neutron counting has the highest priority
  - comments carry 'NURE quad <1x2 degree quadrangle>; methods <codes>' - the Geostatistics page uses this as the survey key, so a grid never
    mixes quadrangles analysed with different method sets or laboratories
Sample types: STREAM / STREAM BANK -> SED_STREAM; POND-NATURAL, POND-ARTIFICIAL, LAKE -> SED_LAKE; SOIL -> SOIL_SAMPLE; BEDROCK / rock media ->
ROCK_SAMPLE; spring, talus, playa, sinter, other -> SEDIMENT_SAMPLE.
Usage: python load_nure_hssr.py [--check]
"""
import os, sys, io, csv, time, collections
import psycopg2
from pyproj import Transformer

CHECK = "--check" in sys.argv
TAG = "migration_nure_hssr_20261113"
SRC = "USA_NURE_HSSR"
PART = "usa_nure_hssr"
XID = "NURE_HSSR_REC_NO"
F = "D:/CriticalMineralsDB/USA/nure_hssr_20261113/nuresed.csv"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


LABTAG = {"LASL": "LASL", "SRL-W": "SRLW", "SRL-E": "SRLE", "ORGDP": "ORGDP", "LLL": "LLL"}
LABNAME = {"LASL": "Los Alamos Scientific Laboratory", "SRLW": "Savannah River Laboratory (western region)", "SRLE": "Savannah River Laboratory (eastern region)",
           "ORGDP": "Oak Ridge Gaseous Diffusion Plant", "LLL": "Lawrence Livermore Laboratory"}
LABMETHOD = {"LASL": "NURE-LASL", "SRLW": "NURE-SRL", "SRLE": "NURE-SRL", "ORGDP": "NURE-ORGDP", "LLL": "NURE-LLL"}
# package kind -> (gold method code or None = the lab's family, priority)
KIND = {"U_DN": ("NONE-DNC", 1), "U_MS": ("UNK-ICPMS", 1), "U_NA": ("NONE-INAA", 2), "U_FL": ("UNK-FLUOR", 2), "U_XX": ("UNKNOWN-UNKNOWN", 3), "MULTI": (None, 3)}
NEW_METHODS = {
    "UNK-FLUOR": ("Fluorometry (sample decomposition not stated)", "Unknown", "Digestion not stated", "FLUOR", "Fluorometry"),
    "UNK-ICPMS": ("ICP-MS (sample decomposition not stated)", "Unknown", "Digestion not stated", "ICP-MS", "Inductively Coupled Plasma Mass Spectrometry"),
    "NURE-LASL": ("NURE Los Alamos multi-element methods (neutron activation, emission spectrography, XRF / AAS by record; see the METHODS codes)", "Mixed", "Laboratory-specific (NURE LASL)", "MULTI", "NURE laboratory method family"),
    "NURE-SRL": ("NURE Savannah River multi-element methods (mainly neutron activation; see the METHODS codes)", "None", "No Digestion (neutron activation)", "MULTI", "NURE laboratory method family"),
    "NURE-ORGDP": ("NURE Oak Ridge multi-element methods (emission spectrography / ICP, fluorometric U; see the METHODS codes)", "Mixed", "Laboratory-specific (NURE ORGDP)", "MULTI", "NURE laboratory method family"),
    "NURE-LLL": ("NURE Livermore multi-element methods (neutron activation, DNC; see the METHODS codes)", "None", "No Digestion (neutron activation)", "MULTI", "NURE laboratory method family"),
}
U_COLS = {"u_dn_ppm": "U_DN", "u_fl_ppm": "U_FL", "u_ms_ppm": "U_MS", "u_na_ppm": "U_NA", "u_xx_ppm": "U_XX"}
SKIP_COLS = {"orgn_pct", "po4_ppm", "so4_ppm"}


def stype(media, src):
    if media == "ROCK" or src == "BEDROCK": return "ROCK_SAMPLE"
    if src in ("STREAM", "STREAM BANK"): return "SED_STREAM"
    if src in ("POND-NATURAL", "POND-ARTIFICIAL", "LAKE"): return "SED_LAKE"
    if src == "SOIL": return "SOIL_SAMPLE"
    return "SEDIMENT_SAMPLE"


to84 = Transformer.from_crs("EPSG:4267", "EPSG:4326", always_xy=True)
stats = collections.Counter()
samples = {}
res_path = os.path.join(HERE, "_nure_results.csv")
used_pk = {}
nres = 0
with open(F, encoding="latin-1", newline="") as fh, open(res_path, "w", newline="", encoding="utf-8") as out:
    rd = csv.DictReader(fh)
    els = [c for c in rd.fieldnames if c.endswith(("_ppm", "_pct")) and c not in SKIP_COLS]
    w = csv.writer(out)
    for r in rd:
        # Replicate codes differ by laboratory: LASL 0 (1-5 = replicates), SRL 000, ORGDP blank (letters = replicates), LLL a 3-digit code whose
        # usual values are 100 (13,445 records) and 000; rarer LLL codes (101, 110, 400 ...) are treated as replicates.
        rep = r["replc"].strip()
        if rep not in ("0", "000", "") and not (r["doelab"].strip() == "LLL" and rep == "100"): stats["replicate record left out"] += 1; continue
        try: lat, lon = float(r["latitude"]), float(r["longitude"])
        except ValueError: stats["no position"] += 1; continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0): stats["bad position"] += 1; continue
        lab = LABTAG.get(r["doelab"].strip())
        if lab is None: stats["unknown lab " + r["doelab"]] += 1; continue
        key = r["rec_no"].strip()
        lon84, lat84 = to84.transform(lon, lat)
        st = stype(r["smpmedia"].strip(), r["sampsrc"].strip())
        frac = r["sizefrxn"].strip() or None
        meth = r["methods"].strip() or "not recorded"
        note = "; ".join(x for x in [
            f"NURE quad {r['quad'].strip() or 'unknown'}", f"methods {meth}", f"NURE HSSR record {key}", f"lab {r['doelab'].strip()}",
            f"study {r['study'].strip()}" if r["study"].strip() else "", f"phase {r['phase'].strip()}" if r["phase"].strip() else "",
            f"state {r['state'].strip()}", f"source {r['sampsrc'].strip()}" if r["sampsrc"].strip() else "",
            f"sediment {r['sedtype'].strip()}" if r["sedtype"].strip() else "", f"geology {r['sgeounit'].strip()} {r['rocktyp'].strip()}".strip() if (r["sgeounit"].strip() or r["rocktyp"].strip()) else "",
            f"coordinates: {r['coordprb'].strip()}" if r["coordprb"].strip() else "", "position converted from NAD27",
            r["comments"].strip()[:200], r["comment2"].strip()[:200]] if x and x != "geology")
        d = r["sampdat"].strip()
        sdate = d.replace("/", "-") if len(d) == 10 and d[:2] in ("19", "20") else None
        labid = (r["laslid"] or r["srlid"] or r["ornlid"] or r["lllid"]).strip() or None
        samples[key] = [key, st, f"NURE HSSR {r['smpmedia'].strip().lower()}: {r['sampsrc'].strip().lower() or 'unspecified source'}"[:250],
                        lat84, lon84, labid, r["prime_id"].strip() or key, note, "SURFACE", sdate, frac]
        stats["samples " + st] += 1
        for col in els:
            v = r[col].strip()
            if not v: continue
            try: x = float(v)
            except ValueError: stats["bad value"] += 1; continue
            if x == 0: stats["zero value"] += 1; continue
            kind = U_COLS.get(col, "MULTI")
            el = col.split("_")[0]
            code = "U" if col in U_COLS else el[0].upper() + el[1:]
            unit = "%" if col.endswith("_pct") else "ppm"
            if x < 0: qual, val, ldl = "<", -x, -x; stats["below detection"] += 1
            else: qual, val, ldl = None, x, None
            pk = f"NURE-{lab}-{kind}"
            used_pk[pk] = (lab, kind)
            cmt = f"NURE {r['doelab'].strip()} methods {meth}" + (f"; U method {r['u_xx_mthd'].strip()}" if kind == "U_XX" and r["u_xx_mthd"].strip() else "")
            w.writerow([key, pk, code, unit, qual or N, val, N if ldl is None else ldl, cmt, frac or N])
            nres += 1
log("staged samples", len(samples), "results", nres, dict(stats))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
if not CHECK:
    g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '512MB'")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "USA_NURE_HSSR already has samples: delete them by created_by first"

for code, (name, dcode, dname, icode, iname) in NEW_METHODS.items():
    c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, instrument_code, instrument_name, notes, is_active,
                   created_by, created_date)
                 SELECT %s, %s, %s, %s, %s, %s, %s, true, %s, now() WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = %s)""",
              (code, name, dcode, dname, icode, iname, "Added for the NURE HSSR load", TAG, code))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for pk, (lab, kind) in used_pk.items():
    mcode, prio = KIND[kind]
    mcode = mcode or LABMETHOD[lab]
    what = "uranium by " + {"U_DN": "delayed neutron counting", "U_FL": "fluorometry", "U_MS": "ICP-MS", "U_NA": "neutron activation",
                            "U_XX": "another method (code in the result comment)"}[kind] if kind != "MULTI" else "multi-element analyses"
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pk, f"NURE HSSR {LABNAME[lab]}: {what}", mid[mcode], f"NURE HSSR (DOE, reformatted by USGS, OFR 97-492): {LABNAME[lab]}, {what}", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'T', %s, 'NURE HSSR' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, 'T', %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, prio, "NURE HSSR total basis assumed " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date, frac text",
     samples.values())
c.execute("CREATE TEMP TABLE st_result (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, comment text, fraction text) ON COMMIT DROP")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); assert c.fetchone()[0] == nres
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
log("dictionary checks passed")

c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
c.execute("CREATE UNIQUE INDEX ON st_map (k)")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments, sample_date, is_active,
  created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, s.sdate, true,
  '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount, "| without any result (not loaded)", len(samples) - c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
c.execute(f"""SELECT t.sample_type_code, count(*) FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id)
              WHERE s.created_by = '{TAG}' GROUP BY 1 ORDER BY 2 DESC"""); log("sample types", c.fetchall())
if CHECK:
    c.execute("SELECT pkg, count(*) FROM st_result GROUP BY 1 ORDER BY 2 DESC LIMIT 30"); log("values per package", c.fetchall())
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back before the result rows"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  split_part(p.package_code, '-', 2), meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(),
  NULL, r.fraction, r.comment
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("results inserted", nins, "of", nres, "in", round(time.time() - t0), "s")
assert nins == nres, (nins, nres)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'rule-based classification at load (NURE negative value = below detection)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "U.S. Geological Survey (data from the U.S. Department of Energy NURE program)",
           "NURE Hydrogeochemical and Stream Sediment Reconnaissance (HSSR) sediment and soil data, USGS reformatted release (Smith 1997, OFR 97-492, v1.40)",
           "US public domain (USGS release; metadata Access_Constraints None, Use_Constraints None)", "https://mrdata.usgs.gov/nure/sediment/",
           "Source: U.S. Geological Survey, NURE HSSR data (Smith, S.M., 1997, USGS Open-File Report 97-492), from the U.S. Department of Energy NURE program.",
           "Cleared: USGS metadata nurehssr.met states Access_Constraints None and Use_Constraints None (checked 2026-11-13). Loaded 2026-11-13.",
           "1975-1984 data from four DOE laboratories with different methods (results not comparable across laboratories or method sets); element methods recorded per record, not per element; positions converted from NAD27; many descriptive fields incomplete.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\USGS_NURE_HSSR\ (metadata copy, EVIDENCE.md)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
nores = c.fetchone()[0]
log("samples without results (must be 0)", nores)
assert nores == 0
g.commit(); log("COMMITTED", TAG)
g.close()
os.remove(res_path)
