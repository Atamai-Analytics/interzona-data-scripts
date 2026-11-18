"""SA SARIG phase 2: DRILL-HOLE laboratory assays -> interzona_cm gold, source AUSTRALIA_SA_SARIG (same source and partition as the phase 1
surface samples), drill holes in drilling.drillholes. Input: the files written by extract_sa_sarig_drill.py (sa_drill_holes / samples / results /
packages .csv). RESUMABLE: every stage commits on its own and is skipped when already done (the network to RDS drops now and then), results
go in sample-id batches. Rollback: delete rows with created_by = TAG from analytical_results (+ result_classifications by result_id), samples,
core.external_ids, drilling.drillholes, and packages created with TAG; drop geochem._stage_sad_*.

Stages  1 packages new to SA (same SA-<digestion>-<finish> families and rules as phase 1, sa_sarig_common)
        2 permanent staging tables geochem._stage_sad_h / _s / _r (results COPY in 1M-line chunks, resumes mid-file)
        3 drill holes (collar = position of the hole's first sampled interval; total depth unknown - deepest sampled interval in comments)
        4 samples (DRILLHOLE_INTERVAL, drillhole_id, depth_from_m / depth_to_m) + external ids, map geochem._stage_sad_m
        5 results + classifications per 100,000 sample ids
        6 data source text, verification, drop staging
Usage: python load_sa_sarig_drill.py <extract dir>
"""
import csv, io, os, sys, time, itertools
import psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sa_sarig_common import DIGN, pkg_rule

TAG = "migration_sa_sarig_drill_20261118"
SRC, PART, XID = "AUSTRALIA_SA_SARIG", "australia_sa_sarig", "SARIG_SAMPLE_NO"
D = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
BATCH = 100_000
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
t0 = time.time()


def log(*a):
    print(f"{time.strftime('%H:%M:%S')} {time.time() - t0:6.0f}s", *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'"); g.commit()


def q1(sql, args=None):
    c.execute(sql, args); return c.fetchone()[0]


def exists(t):
    return q1("SELECT to_regclass(%s) IS NOT NULL", (t,))


def nlines(path):
    with open(path, "rb") as f:
        return sum(buf.count(b"\n") for buf in iter(lambda: f.read(64 * 1024 * 1024), b""))


# ---------------------------------------------------------------- 1 packages
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
for pk, d, e, n in csv.reader(open(os.path.join(D, "sa_drill_packages.csv"), encoding="utf-8")):
    mcode, basis, prio = pkg_rule(d, e)
    name = f"SARIG samples - {DIGN[d]}, {e}"
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pk, name, mid[mcode], name + " (method family assigned from the SARIG laboratory method dictionary; original method code in result_comment)", TAG))
    if c.rowcount: log("new package", pk, mcode)
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'SARIG method family' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT (source_system, package_id) DO NOTHING""",
              (SRC, basis, prio, "SARIG method family " + TAG, pk))
g.commit(); log("1 packages ok")

# ---------------------------------------------------------------- 2 staging
RES = os.path.join(D, "sa_drill_results.csv")
if not exists("geochem._stage_sad_h"):
    c.execute("CREATE TABLE geochem._stage_sad_h (hole_no text, name text, lat float8, lon float8, collector text, d1 date, d2 date, maxto numeric)")
    with open(os.path.join(D, "sa_drill_holes.csv"), encoding="utf-8") as f: c.copy_expert("COPY geochem._stage_sad_h FROM STDIN WITH (FORMAT csv, NULL '\\N')", f)
    c.execute("""CREATE TABLE geochem._stage_sad_s (k text, stype text, slocal text, lat float8, lon float8, field_no text, comments text, sdate date,
                 hole_no text, dfrom numeric, dto numeric)""")
    with open(os.path.join(D, "sa_drill_samples.csv"), encoding="utf-8") as f: c.copy_expert("COPY geochem._stage_sad_s FROM STDIN WITH (FORMAT csv, NULL '\\N')", f)
    c.execute("""CREATE TABLE geochem._stage_sad_r (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric, lab text,
                 comment text, st text)""")
    g.commit(); log("staged holes and samples")
want = nlines(RES)
have = q1("SELECT count(*) FROM geochem._stage_sad_r")
if have < want:
    log(f"staging results: {have:,} of {want:,} lines already in")
    with open(RES, encoding="utf-8") as f:
        for _ in itertools.islice(f, have): pass
        while True:
            chunk = list(itertools.islice(f, 1_000_000))
            if not chunk: break
            c.copy_expert("COPY geochem._stage_sad_r FROM STDIN WITH (FORMAT csv, NULL '\\N')", io.StringIO("".join(chunk))); g.commit()
            have += len(chunk)
            if have % 10_000_000 < 1_000_000: log(f"  {have:,} staged")
assert q1("SELECT count(*) FROM geochem._stage_sad_r") == want
if not q1("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'geochem' AND tablename = '_stage_sad_r')"):
    c.execute("CREATE INDEX ON geochem._stage_sad_r (k)"); g.commit()
for label, sql in [("unit", "SELECT DISTINCT r.unit FROM geochem._stage_sad_r r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM geochem._stage_sad_r r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("analyte", "SELECT DISTINCT r.analyte FROM geochem._stage_sad_r r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM geochem._stage_sad_s s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]; assert not miss, (label, miss)
assert q1("""SELECT count(*) FROM geochem._stage_sad_s s JOIN geochem.samples x ON x.source_system = %s AND x.sample_number = s.k
             AND x.created_by <> %s""", (SRC, TAG)) == 0, "drill sample numbers already loaded in phase 1"
log("2 staging ok", want, "results")

# ---------------------------------------------------------------- 3 drill holes
if q1("SELECT count(*) FROM drilling.drillholes WHERE created_by = %s", (TAG,)) == 0:
    c.execute(f"""
    INSERT INTO drilling.drillholes (source_system, source_hole_id, hole_name, company, lat, lon, geom, geog, original_crs, position_method, comments,
      is_active, created_by, created_date)
    SELECT '{SRC}', h.hole_no, coalesce(h.name, 'SARIG ' || h.hole_no), h.collector, h.lat, h.lon, ST_SetSRID(ST_MakePoint(h.lon, h.lat), 4326),
      ST_SetSRID(ST_MakePoint(h.lon, h.lat), 4326)::geography, 'GDA2020 (position of the first sampled interval)', 'SARIG sample position',
      concat_ws('; ', 'SARIG drillhole no. ' || h.hole_no, CASE WHEN h.maxto > 0 THEN 'deepest sampled interval ends at ' || h.maxto || ' m' END,
        CASE WHEN h.d1 IS NOT NULL THEN 'samples collected ' || extract(year FROM h.d1)::int ||
          CASE WHEN extract(year FROM h.d2) <> extract(year FROM h.d1) THEN '-' || extract(year FROM h.d2)::int ELSE '' END END),
      true, '{TAG}', now()
    FROM geochem._stage_sad_h h WHERE EXISTS (SELECT 1 FROM geochem._stage_sad_s s WHERE s.hole_no = h.hole_no)""")
    log("drill holes inserted", c.rowcount); g.commit()
log("3 holes ok", q1("SELECT count(*) FROM drilling.drillholes WHERE created_by = %s", (TAG,)))

# ---------------------------------------------------------------- 4 samples
if q1("SELECT count(*) FROM geochem.samples WHERE created_by = %s", (TAG,)) == 0:
    c.execute("DROP TABLE IF EXISTS geochem._stage_sad_m")
    c.execute(f"""CREATE TABLE geochem._stage_sad_m AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id, h.drillhole_id
                  FROM geochem._stage_sad_s s JOIN drilling.drillholes h ON h.source_system = '{SRC}' AND h.source_hole_id = s.hole_no AND h.created_by = '{TAG}'
                  WHERE EXISTS (SELECT 1 FROM geochem._stage_sad_r r WHERE r.k = s.k)""")
    c.execute("CREATE UNIQUE INDEX ON geochem._stage_sad_m (k)"); c.execute("CREATE INDEX ON geochem._stage_sad_m (sample_id)")
    c.execute(f"""
    INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, depth_from_m, depth_to_m,
      comments, sample_date, is_active, created_by, created_date, source_system, drillhole_id)
    OVERRIDING SYSTEM VALUE
    SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.k, t.sample_type_id, s.slocal, 'DRILLHOLE_INTERVAL', s.dfrom, s.dto,
      s.comments, s.sdate, true, '{TAG}', now(), '{SRC}', m.drillhole_id
    FROM geochem._stage_sad_s s JOIN geochem._stage_sad_m m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
    log("samples inserted", c.rowcount)
    c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
                  SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM geochem._stage_sad_m""")
    g.commit()
log("4 samples ok", q1("SELECT count(*) FROM geochem.samples WHERE created_by = %s", (TAG,)))

# ---------------------------------------------------------------- 5 results
lo, hi = q1("SELECT min(sample_id) FROM geochem._stage_sad_m"), q1("SELECT max(sample_id) FROM geochem._stage_sad_m")
done = 0
for a in range(lo, hi + 1, BATCH):
    z = a + BATCH - 1
    if q1(f"SELECT EXISTS (SELECT 1 FROM geochem.analytical_results_{PART} WHERE sample_id BETWEEN %s AND %s AND created_by = %s)", (a, z, TAG)):
        continue
    c.execute(f"""
    INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
      unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
      value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
      source_result_id, fraction, result_comment)
    SELECT m.sample_id, NULL, '{SRC}', p.package_id, an.analyte_id, an.analyte_name, an.element_symbol, u.unit_id, u.unit_code, qq.qualifier_id, qq.qualifier_code,
      r.lab, meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, r.udl, NULL, NULL, false, true, '{TAG}', now(), r.st, NULL, r.comment
    FROM geochem._stage_sad_m m JOIN geochem._stage_sad_r r ON r.k = m.k
    JOIN geochem.analytes an ON an.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
    JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
    LEFT JOIN geochem.qualifiers qq ON qq.qualifier_code = r.qual
    WHERE m.sample_id BETWEEN %s AND %s""", (a, z))
    n = c.rowcount
    c.execute(f"""
    INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
    SELECT r.result_id, r.source_system, CASE r.source_result_id WHEN 'B' THEN 'BELOW_DL_QUALIFIED' WHEN 'A' THEN 'ABOVE_UDL' ELSE 'DETECTED' END,
      CASE WHEN r.source_result_id = 'B' THEN r.lower_detection_limit END, CASE WHEN r.source_result_id = 'B' THEN 'QUALIFIER_LDL' END, r.source_result_id = 'D'
    FROM geochem.analytical_results_{PART} r WHERE r.sample_id BETWEEN %s AND %s AND r.created_by = %s""", (a, z, TAG))
    c.execute(f"UPDATE geochem.analytical_results_{PART} SET source_result_id = NULL WHERE sample_id BETWEEN %s AND %s AND created_by = %s", (a, z, TAG))
    g.commit(); done += n
    log(f"5 batch {a}-{z}: {n:,} results (this run {done:,})")
tot = q1(f"SELECT count(*) FROM geochem.analytical_results_{PART} WHERE created_by = %s", (TAG,))
log("5 results total", tot, "expected", want); assert tot == want, (tot, want)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'SARIG drill: <x -> BELOW_DL_QUALIFIED (dl x), >x -> ABOVE_UDL, numbers DETECTED')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, tot))
g.commit()

# ---------------------------------------------------------------- 6 source text, verification
c.execute("""UPDATE core.data_sources SET
  dataset_name = 'SARIG rock-sample chemistry export (sarig_rs_chem_exp, July 2025) - surface samples (phase 1) and drill-hole intervals (phase 2) with laboratory assays',
  caveats = 'Mostly exploration-company data submitted to the state, 1960s-2020s, many laboratories and methods - compare one method family (package) at a time. '
    'Surface samples: soil, calcrete, rock, stream / lake sediment, lag, gravel, auger, channel, trench, vegetation (calcrete and lag stored as soil / sediment '
    'sample types with the medium in sample_type_local). Drill holes (loaded 2026-11-18): ~120,000 holes and ~2.7M downhole intervals in drilling.drillholes / '
    'samples with drillhole_id and depths; collar = position of the first sampled interval, hole depth = deepest sampled interval (comments), no surveys '
    '(holes treated as vertical). Portable / in-house XRF, calculated and SARIG log-derived values, duplicates and standards left out.'
  WHERE source_system = %s""", (SRC,))
g.commit()
empty = q1(f"""SELECT count(*) FROM geochem._stage_sad_m m WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_results_{PART} r WHERE r.sample_id = m.sample_id)""")
log("samples without results (must be 0)", empty); assert empty == 0
for t in ("_stage_sad_h", "_stage_sad_s", "_stage_sad_r", "_stage_sad_m"): c.execute(f"DROP TABLE IF EXISTS geochem.{t}")
g.commit(); log("DONE", TAG)
