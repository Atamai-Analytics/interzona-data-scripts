"""RESUMABLE gold stage of the NSW rebuild (companion to load_nsw_gsnsw_source.py, which extracts and maps the source results to
_nsw_source_results.csv and was verified with --check). Written 2026-11-17 after a 42-minute single-transaction load was cut by a network drop
just before COMMIT. Every step commits on its own and is skipped when already done, so a re-run continues where it stopped.

Steps:  1 partitions, AUTO-* packages, priority rules            (idempotent)
        2 permanent staging tables geochem._stage_nsw_s / _r     (skipped when row counts already match)
        3 samples + external ids + geochem._stage_nsw_m map      (skipped when NSW samples exist)
        4 results + classifications in sample-id batches          (a batch is skipped when it already has results)
        5 lithology, data source, verification, drop staging     (lithology skipped when present)
Rollback: delete rows with created_by = TAG (samples, external ids, lithology), the AUTO-* packages, and the partition rows; drop geochem._stage_nsw_*.
Usage: python load_nsw_gsnsw_gold_stages.py
"""
import csv, io, os, sys, time, collections
import psycopg2

TAG = "migration_nsw_gsnsw_20261117"
SRC, PART, XID = "AUSTRALIA_NSW_GSNSW", "australia_nsw_gsnsw", "BRONZE_CRITICIALMINERALSEXP"
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "_nsw_source_results.csv")
BATCH = 150_000
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


def connect(db, readonly=False):
    g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db, user=ENV["LITHODAT_DB_USER"],
                         password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
    if readonly: g.set_session(readonly=True)
    return g


g = connect("interzona_cm"); c = g.cursor()
c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'"); g.commit()


def q1(sql, args=None):
    c.execute(sql, args); return c.fetchone()[0]


def exists(t):
    return q1("SELECT to_regclass(%s) IS NOT NULL", (t,))


# ---------------------------------------------------------------- 1
g.autocommit = True
for t in ("analytical_results", "result_classifications"):
    c.execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
g.autocommit = False
pk_used = collections.Counter(); keys = set()
with open(RES, encoding="utf-8") as f:
    for r in csv.reader(f):
        pk_used[r[2]] += 1; keys.add((r[0], r[1]))
nres = sum(pk_used.values())
log("results file rows", nres, "sample keys", len(keys))
MTH = {"AR-ICPMS": "AR-ICPMS", "AR-ICPOES": "AR-ICPOES", "4A-ICPMS": "4A-ICPMS", "FA-ICPMS": "FA-ICPMS", "FA-ICPOES": "FA-ICPOES", "CN-ICPMS": "CN-ICPMS",
       "HNO3-AAS": "HNO3-AAS", "FUS-XRF": "LIBOR-XRF", "NONE-LECO": "NONE-LECO", "UNK-ICPMS": "UNK-ICPMS"}
DIG = {"AR": "aqua regia", "4A": "four-acid", "3A": "three/two-acid", "FUS": "fusion", "FA": "fire assay", "CN": "cyanide / BLEG", "LEACH": "partial leach",
       "HNO3": "nitric acid", "UNK": "digestion not recorded", "NONE": "no digestion"}
for p in sorted(x for x in pk_used if x.startswith("AUTO-")):
    _, d, e = p.split("-", 2)
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (p, f"NSW auto-assigned - {DIG.get(d, d)}, {e}", MTH.get(f"{d}-{e}", "UNKNOWN-UNKNOWN"),
               "Assigned automatically during the 2026-11 NSW rebuild from the assay code and report description (not in the user's hand-made mapping); pending review", TAG))
    basis = "T" if d in ("4A", "FUS", "FA", "NONE") else "P"
    prio = {"ICPMS": 1, "ICPOES": 2, "XRF": 3, "LECO": 1, "AAS": 4}.get(e, 6) + (3 if d in ("UNK", "LEACH", "CN", "HNO3") else 0)
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'NSW auto-assigned package' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, p))
c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
             SELECT %s, package_id, 'T', 8, 'NSW: method unknown or XRF of unknown type - lowest priority' FROM geochem.analytical_packages
             WHERE package_code IN ('UNK-XRF', 'UNK-UNK-UNK', 'ONSITE-UNK', 'ONSITE-estimate')
             ON CONFLICT (source_system, package_id) DO UPDATE SET priority = excluded.priority, note = excluded.note""", (SRC,))
miss = q1("SELECT count(*) FROM unnest(%s::text[]) p WHERE p NOT IN (SELECT package_code FROM geochem.analytical_packages)", (list(pk_used),))
assert miss == 0, f"{miss} packages missing"
g.commit(); log("1 packages ok")

# ---------------------------------------------------------------- 2
if not (exists("geochem._stage_nsw_r") and q1("SELECT count(*) FROM geochem._stage_nsw_r") == nres):
    b = connect("criticialmineralsexp", readonly=True); bc = b.cursor(); bc.execute("SET statement_timeout = 0")
    bc.execute("""SELECT s.sampleid, l.latitude, l.longitude, l.elevation, st.sample_type_code, s.sampletypelocal, s.sample_context,
                  s.samplenumber, s.samplenumberalt, s.fieldid, s.comments
                  FROM samples s JOIN locations l ON l.locationid = s.locationid JOIN sample_types st ON st.sample_type_id = s.sample_type_id
                  WHERE s.isactive AND l.datasource = 'Geological Survey of NSW' AND st.sample_type_code <> 'QC_SAMPLE'""")
    samp = {}
    for r in bc.fetchall():
        k = (str(r[7]), str(r[8]))
        if k in keys and k not in samp: samp[k] = r
    b.close(); assert len(samp) == len(keys), (len(samp), len(keys))
    for t in ("_stage_nsw_s", "_stage_nsw_r", "_stage_nsw_m"): c.execute(f"DROP TABLE IF EXISTS geochem.{t}")
    c.execute("""CREATE TABLE geochem._stage_nsw_s (k1 text, k2 text, bronze_sampleid bigint, lat float8, lon float8, elev numeric, stype text, slocal text,
                 sctx text, sno text, fieldid text, comments text)""")
    buf = io.StringIO(); w = csv.writer(buf)
    for k, r in samp.items():
        w.writerow([k[0], k[1], r[0], r[1], r[2], N if r[3] is None else r[3], r[4], r[5] or N, r[6] or N, r[7], r[9] or N,
                    ("; ".join(x for x in [f"GSNSW report (RPT_ID) {r[9]}", f"file (FILE_ID) {r[8]}", r[10] or ""] if x))[:1000]])
    buf.seek(0); c.copy_expert("COPY geochem._stage_nsw_s FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
    c.execute("CREATE TABLE geochem._stage_nsw_r (k1 text, k2 text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, lab text, comment text)")
    g.commit()
    with open(RES, encoding="utf-8") as f:
        while True:
            chunk = [line for _, line in zip(range(500_000), f)]
            if not chunk: break
            c.copy_expert("COPY geochem._stage_nsw_r FROM STDIN WITH (FORMAT csv, NULL '\\N')", io.StringIO("".join(chunk))); g.commit()
    c.execute("CREATE INDEX ON geochem._stage_nsw_r (k1, k2)"); g.commit()
    assert q1("SELECT count(*) FROM geochem._stage_nsw_r") == nres
log("2 staging ok")

# ---------------------------------------------------------------- 3
if q1("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)) == 0:
    c.execute("DROP TABLE IF EXISTS geochem._stage_nsw_m")
    c.execute("CREATE TABLE geochem._stage_nsw_m AS SELECT k1, k2, bronze_sampleid, nextval('geochem.samples_sample_id_seq') AS sample_id FROM geochem._stage_nsw_s")
    c.execute("CREATE UNIQUE INDEX ON geochem._stage_nsw_m (k1, k2)"); c.execute("CREATE INDEX ON geochem._stage_nsw_m (sample_id)")
    c.execute(f"""
    INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_number_alt, sample_type_id, sample_type_local, sample_context, elevation_m,
      comments, is_active, created_by, created_date, source_system)
    OVERRIDING SYSTEM VALUE
    SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.fieldid, s.sno, s.k2, t.sample_type_id, s.slocal, coalesce(s.sctx, 'SURFACE'), s.elev,
      s.comments, true, '{TAG}', now(), '{SRC}'
    FROM geochem._stage_nsw_s s JOIN geochem._stage_nsw_m m ON m.k1 = s.k1 AND m.k2 = s.k2 JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
    log("samples inserted", c.rowcount)
    c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
                  SELECT 'SAMPLE', sample_id, '{XID}', bronze_sampleid::text, '{TAG}', now() FROM geochem._stage_nsw_m""")
    g.commit()
log("3 samples ok", q1("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)))

# ---------------------------------------------------------------- 4
lo, hi = q1("SELECT min(sample_id) FROM geochem._stage_nsw_m"), q1("SELECT max(sample_id) FROM geochem._stage_nsw_m")
done = 0
for a in range(lo, hi + 1, BATCH):
    z = a + BATCH - 1
    if q1(f"SELECT EXISTS (SELECT 1 FROM geochem.analytical_results_{PART} WHERE sample_id BETWEEN %s AND %s)", (a, z)):
        continue
    c.execute(f"""
    INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
      unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
      value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
      source_result_id, fraction, result_comment)
    SELECT m.sample_id, NULL, '{SRC}', p.package_id, an.analyte_id, an.analyte_name, an.element_symbol, u.unit_id, u.unit_code, qq.qualifier_id, qq.qualifier_code,
      r.lab, meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(), NULL, NULL, r.comment
    FROM geochem._stage_nsw_m m JOIN geochem._stage_nsw_r r ON r.k1 = m.k1 AND r.k2 = m.k2
    JOIN geochem.analytes an ON an.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
    JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
    LEFT JOIN geochem.qualifiers qq ON qq.qualifier_code = r.qual
    WHERE m.sample_id BETWEEN %s AND %s""", (a, z))
    n = c.rowcount
    c.execute(f"""
    INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
    SELECT r.result_id, r.source_system, CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' ELSE 'DETECTED' END,
      CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'NEGATIVE_CONVENTION' END,
      r.qualifier_code IS NULL
    FROM geochem.analytical_results_{PART} r WHERE r.sample_id BETWEEN %s AND %s""", (a, z))
    g.commit(); done += n
    log(f"4 batch {a}-{z}: {n:,} results (this run {done:,})")
tot = q1(f"SELECT count(*) FROM geochem.analytical_results_{PART}")
log("4 results total", tot, "expected", nres); assert tot == nres, (tot, nres)
assert q1(f"SELECT count(*) FROM geochem.result_classifications_{PART}") == nres
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'NSW source: negative value -> BELOW_DL_QUALIFIED (limit = DETLIMIT or |value|); positive DETECTED')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nres))
g.commit()

# ---------------------------------------------------------------- 5
if q1("SELECT count(*) FROM geochem.lithology_observations WHERE created_by = %s", (TAG,)) == 0:
    b = connect("criticialmineralsexp", readonly=True); bc = b.cursor(); bc.execute("SET statement_timeout = 0")
    bc.execute("""SELECT lo.sampleid, lit.lithology_code, lo.lithologylocal, lo.observation_context, lo.depthfrom_m, lo.depthto_m, lo.logged_by, lo.logged_date,
                  lo.stratgroup, lo.stratformation, lo.stratmember, lo.stratbed, lo.alterationlocal, lo.comments
                  FROM lithology_observations lo JOIN locations l ON l.locationid = lo.locationid LEFT JOIN lithology lit ON lit.lithology_id = lo.lithology_id
                  WHERE l.datasource = 'Geological Survey of NSW' AND lo.isactive AND lo.sampleid IS NOT NULL""")
    lit = bc.fetchall(); b.close()
    c.execute("""CREATE TEMP TABLE st_l (bronze_sampleid bigint, lithology_code text, lithology_local text, observation_context text, dfrom numeric, dto numeric,
                 logged_by text, logged_date timestamptz, sg text, sf text, sm text, sb text, alt text, comments text) ON COMMIT DROP""")
    buf = io.StringIO(); w = csv.writer(buf)
    for r in lit: w.writerow([N if x is None else x for x in r])
    buf.seek(0); c.copy_expert("COPY st_l FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
    c.execute(f"""
    INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sampling_line_id, sample_id, occurrence_id, depth_from_m, depth_to_m,
      logged_by, logged_date, strat_group, strat_formation, strat_member, strat_bed, alteration_id, alteration_local, comments, is_active, created_by, created_date)
    SELECT lt.lithology_id, l.lithology_local, l.observation_context, NULL, m.sample_id, NULL, l.dfrom, l.dto, l.logged_by, l.logged_date, l.sg, l.sf, l.sm, l.sb,
      NULL, l.alt, l.comments, true, '{TAG}', now()
    FROM st_l l JOIN geochem._stage_nsw_m m ON m.bronze_sampleid = l.bronze_sampleid LEFT JOIN geochem.lithology lt ON lt.lithology_code = l.lithology_code""")
    log("lithology obs", c.rowcount); g.commit()
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, 'Geological Survey of New South Wales (NSW Resources), State of New South Wales',
  'GSNSW statewide surface geochemistry (DIGS geochemistry tables DD_SGC_*): soil, stream sediment, rock and other surface samples - rebuilt from source',
  'CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/', true,
  '(c) State of New South Wales (Geological Survey of NSW). Licensed under CC BY 4.0. For current information go to www.nsw.gov.au.', true,
  'Cleared: MinView Use of data + NSW Government copyright notice (CC BY 4.0); Rights_Assessment_Public_Datasets_March2026.xlsx (low-medium risk: company-origin data).',
  'Surface samples, mostly exploration-company data released through GSNSW, no sample dates. Method packages: the curator''s hand-made mapping for about half of the lab results, automatic assignment (learned from that mapping, lab code names and report descriptions; result_comment says which) for the rest; generic / unknown methods have the lowest priority. Portable / handheld XRF, XRF error rows, repeat-column codes (Cu-2 ...) and QC samples left out.',
  'D:/CriticalMineralsDB/Documents/Rights_Assessment_Public_Datasets_March2026.xlsx', '2026-11-17', true, %s, now())
 ON CONFLICT (source_system) DO NOTHING""", (SRC, TAG))
g.commit()
empty = q1(f"""SELECT count(*) FROM geochem._stage_nsw_m m WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_results_{PART} r WHERE r.sample_id = m.sample_id)""")
log("samples without results (must be 0)", empty); assert empty == 0
for t in ("_stage_nsw_s", "_stage_nsw_r", "_stage_nsw_m"): c.execute(f"DROP TABLE IF EXISTS geochem.{t}")
g.commit(); log("DONE", TAG)
