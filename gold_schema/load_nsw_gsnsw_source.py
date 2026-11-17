"""NSW (Geological Survey of NSW) statewide surface geochemistry -> interzona_cm gold, REBUILT FROM THE SOURCE (user decision 2026-11-17).
New source AUSTRALIA_NSW_GSNSW (own partition; rollback = delete by created_by = TAG).

Why a rebuild: the Dec-2025 bronze load joined results with FILE_ID = samples.fieldid, but bronze fieldid holds RPT_ID; FILE_ID is
samples.samplenumberalt. Only ~20 % of NSW samples got results in bronze. Here:
  SAMPLES  from bronze (criticialmineralsexp, datasource 'Geological Survey of NSW'): the user's cleaned sample records (sample type, local type,
           context, position, comments) + lithology observations; QC_SAMPLE left out; only samples that receive at least one result are loaded.
  RESULTS  from the source staging tables (criticalminerals: nsw_dd_sgc_data + nsw_dd_gch_meta + nsw_dd_rpt_code), joined to the samples on
           SAMPLEID = samplenumber AND FILE_ID = samplenumberalt.
  METHOD   key (ASSAYCODE, FIELD1, FIELD2) -> package: the user's mapping recovered exactly from bronze (nsw_mapping/nsw_mapping_exact.csv,
           2,882 keys) first, then nsw_mapping/nsw_auto_mapping.csv (4,838 keys; see build_nsw_auto_mapping.py). Portable / handheld XRF packages
           (ONSITE-XRF, UNK-pXRF, UNK-NITON, PXRF73) and XRF error-estimate rows are left out.
  ANALYTE  ELEMENT must be a gold analyte code (repeat columns such as 'Cu-2', 'Au-3' and non-element codes are left out, as in the old loader).
  UNITS    ppm / ppb / % (case variants, UNK_* and PCT folded in); ozt, ppt, '' and others left out.
  VALUES   numeric; negative = below the detection limit (limit = DETLIMIT when given and > 0, else |value|) -> BELOW_DL_QUALIFIED; 0 left out.
Licence: CC BY 4.0, "(c) State of New South Wales (Geological Survey of NSW)" (Rights_Assessment_Public_Datasets_March2026.xlsx).
Usage: python load_nsw_gsnsw_source.py [--check]   (--check = stage everything, insert samples, ROLLBACK)
"""
import csv, io, os, re, sys, time, collections
import psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_nsw_gsnsw_20261117"
SRC, PART, XID = "AUSTRALIA_NSW_GSNSW", "australia_nsw_gsnsw", "BRONZE_CRITICIALMINERALSEXP"
HERE = os.path.dirname(os.path.abspath(__file__))
MAPD = os.path.join(HERE, "nsw_mapping")
PORT_PKG = {"ONSITE-XRF", "UNK-pXRF", "UNK-NITON", "PXRF73", "(excluded)"}
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
    c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
    return g


def unit(u):
    u = (u or "").strip().lower().replace("unk_", "")
    return {"ppm": "ppm", "ppb": "ppb", "%": "%", "pct": "%"}.get(u)


# ---------------------------------------------------------------- method mapping
KEYPKG, SRCMAP = {}, collections.Counter()
for r in csv.DictReader(open(os.path.join(MAPD, "nsw_mapping_exact.csv"), encoding="utf-8")):
    KEYPKG[(r["ASSAYCODE"], r["FIELD1"], r["FIELD2"])] = (r["package_code"], "user")
for r in csv.DictReader(open(os.path.join(MAPD, "nsw_auto_mapping.csv"), encoding="utf-8")):
    k = (r["ASSAYCODE"], r["FIELD1"], r["FIELD2"])
    if k not in KEYPKG: KEYPKG[k] = (r["package_code"], "auto")
log("mapping keys", len(KEYPKG), collections.Counter(v[1] for v in KEYPKG.values()))

# ---------------------------------------------------------------- bronze samples
b = connect("criticialmineralsexp", readonly=True); bc = b.cursor()
bc.execute("""
SELECT s.sampleid, l.latitude, l.longitude, l.elevation, st.sample_type_code, s.sampletypelocal, s.sample_context,
       s.samplenumber, s.samplenumberalt, s.fieldid, s.comments
FROM samples s JOIN locations l ON l.locationid = s.locationid JOIN sample_types st ON st.sample_type_id = s.sample_type_id
WHERE s.isactive AND l.datasource = 'Geological Survey of NSW' AND st.sample_type_code <> 'QC_SAMPLE'""")
samples = {}
dupkey = 0
for r in bc.fetchall():
    k = (str(r[7]), str(r[8]))
    if k in samples: dupkey += 1; continue
    samples[k] = r
log("bronze samples", len(samples), "| duplicate (SAMPLEID, FILE_ID) keys skipped", dupkey)
bc.execute("""
SELECT lo.sampleid, lit.lithology_code, lo.lithologylocal, lo.observation_context, lo.depthfrom_m, lo.depthto_m, lo.logged_by, lo.logged_date,
       lo.stratgroup, lo.stratformation, lo.stratmember, lo.stratbed, lo.alterationlocal, lo.comments
FROM lithology_observations lo JOIN locations l ON l.locationid = lo.locationid LEFT JOIN lithology lit ON lit.lithology_id = lo.lithology_id
WHERE l.datasource = 'Geological Survey of NSW' AND lo.isactive AND lo.sampleid IS NOT NULL""")
litho = bc.fetchall(); b.close()
log("bronze lithology obs", len(litho))

g = connect("interzona_cm"); c = g.cursor()
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT analyte_code FROM geochem.analytes"); ANALYTES = {r[0] for r in c.fetchall()}
c.execute("SELECT package_code FROM geochem.analytical_packages"); PKGS = {r[0] for r in c.fetchall()}
missing_pk = {p for p, _ in KEYPKG.values() if p not in PKGS and p not in PORT_PKG and not p.startswith("AUTO-")}
assert not missing_pk, ("packages missing in gold", missing_pk)

# ---------------------------------------------------------------- source results -> CSV
stats = collections.Counter(); used_pk = collections.Counter(); with_res = set()
res_path = os.path.join(HERE, "_nsw_source_results.csv")
s = connect("criticalminerals", readonly=True)
sc = s.cursor(name="nsw_src"); sc.itersize = 200_000
sc.execute('''SELECT d."SAMPLEID"::text, d."FILE_ID"::text, m."ELEMENT"::text, d."RESULT"::text, m."UNITS"::text, m."DETLIMIT"::text,
                     m."ASSAYCODE"::text, c."FIELD1"::text, c."FIELD2"::text, m."LAB_CODE"::text
              FROM nsw_dd_sgc_data d JOIN nsw_dd_gch_meta m ON m."FILE_ID" = d."FILE_ID" AND m."ASS_ID" = d."ASS_ID"
              LEFT JOIN nsw_dd_rpt_code c ON c."FILE_ID"::text = m."FILE_ID"::text AND c."CODE"::text = m."ASSAYCODE"::text''')
nres = 0
with open(res_path, "w", newline="", encoding="utf-8") as out:
    w = csv.writer(out)
    for sid, fid, el, res, un, dl, ac, f1, f2, lab in sc:
        stats["source rows"] += 1
        k = (sid, fid)
        if k not in samples: stats["no matching sample (QC or not in bronze)"] += 1; continue
        pk = KEYPKG.get((ac or "", f1 or "", f2 or ""))
        if pk is None: stats["key not mapped"] += 1; continue
        if pk[0] in PORT_PKG: stats["portable XRF / error left out"] += 1; continue
        if el not in ANALYTES: stats["element code not an analyte"] += 1; continue
        u = unit(un)
        if u is None: stats["unit left out: " + (un or "(blank)")] += 1; continue
        try: v = float(res)
        except (TypeError, ValueError): stats["non-numeric"] += 1; continue
        if v == 0: stats["zero left out"] += 1; continue
        if v < 0:
            try: d = float(dl)
            except (TypeError, ValueError): d = 0
            lim = d if d and d > 0 else -v
            q, val, ldl = "<", lim, lim; stats["below detection"] += 1
        else:
            q, val, ldl = None, v, None
        labtxt = "; ".join(x for x in [(f2 or "").strip(), (lab or "").strip()] if x)[:100] or "Not recorded"
        cmt = f"NSW assay code {ac}" + (f"; {f1.strip()[:120]}" if f1 and f1.strip() else "") + f"; method mapping {pk[1]}"
        w.writerow([sid, fid, pk[0], el, u, q or N, val, N if ldl is None else ldl, labtxt, cmt])
        used_pk[pk[0]] += 1; with_res.add(k); nres += 1
        if stats["source rows"] % 5_000_000 == 0: log("source rows", stats["source rows"], "staged", nres)
s.close()
log("results staged", nres, "| samples with results", len(with_res))
for k in sorted(stats): log(f"  {k}: {stats[k]:,}")

# ---------------------------------------------------------------- gold
if not CHECK:
    g.commit(); g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
AUTO_METHOD = {}
for r in csv.DictReader(open(os.path.join(MAPD, "nsw_auto_mapping.csv"), encoding="utf-8")): pass
auto_new = sorted(p for p in used_pk if p.startswith("AUTO-") and p not in PKGS)
MTH = {"AR-ICPMS": "AR-ICPMS", "AR-ICPOES": "AR-ICPOES", "4A-ICPMS": "4A-ICPMS", "FA-ICPMS": "FA-ICPMS", "FA-ICPOES": "FA-ICPOES", "CN-ICPMS": "CN-ICPMS",
       "HNO3-AAS": "HNO3-AAS", "FUS-XRF": "LIBOR-XRF", "NONE-LECO": "NONE-LECO", "UNK-ICPMS": "UNK-ICPMS"}
DIG = {"AR": "aqua regia", "4A": "four-acid", "3A": "three/two-acid", "FUS": "fusion", "FA": "fire assay", "CN": "cyanide / BLEG", "LEACH": "partial leach",
       "HNO3": "nitric acid", "UNK": "digestion not recorded", "NONE": "no digestion", "TL": "Regoleach / TerraLeach", "ENZ": "enzyme leach", "MMI": "MMI"}
for p in auto_new:
    _, d, e = p.split("-", 2)
    mcode = MTH.get(f"{d}-{e}", "UNKNOWN-UNKNOWN")
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (p, f"NSW auto-assigned - {DIG.get(d, d)}, {e}", mcode,
               "Assigned automatically during the 2026-11 NSW rebuild from the assay code and report description (not in the user's hand-made mapping); pending review", TAG))
    basis = "T" if d in ("4A", "FUS", "FA", "NONE") else "P"
    prio = {"ICPMS": 1, "ICPOES": 2, "XRF": 3, "LECO": 1, "AAS": 4}.get(e, 6) + (3 if d in ("UNK", "LEACH", "CN", "HNO3") else 0)
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'NSW auto-assigned package' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, p))
log("new AUTO packages", auto_new)
c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
             SELECT %s, package_id, 'T', 8, 'NSW: method unknown or XRF of unknown type - lowest priority' FROM geochem.analytical_packages
             WHERE package_code IN ('UNK-XRF', 'UNK-UNK-UNK', 'ONSITE-UNK', 'ONSITE-estimate')
             ON CONFLICT (source_system, package_id) DO UPDATE SET priority = excluded.priority, note = excluded.note""", (SRC,))

c.execute("""CREATE TEMP TABLE st_s (k1 text, k2 text, bronze_sampleid bigint, lat float8, lon float8, elev numeric, stype text, slocal text, sctx text,
             sno text, fieldid text, comments text) ON COMMIT DROP""")
buf = io.StringIO(); w = csv.writer(buf)
for k in with_res:
    r = samples[k]
    w.writerow([k[0], k[1], r[0], r[1], r[2], N if r[3] is None else r[3], r[4], r[5] or N, r[6] or N, r[7], r[9] or N,
                ("; ".join(x for x in [f"GSNSW report (RPT_ID) {r[9]}", f"file (FILE_ID) {r[8]}", r[10] or ""] if x))[:1000]])
buf.seek(0); c.copy_expert("COPY st_s FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
c.execute("""CREATE TEMP TABLE st_r (k1 text, k2 text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, lab text, comment text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as f:
    while True:
        chunk = [line for _, line in zip(range(500_000), f)]
        if not chunk: break
        c.copy_expert("COPY st_r FROM STDIN WITH (FORMAT csv, NULL '\\N')", io.StringIO("".join(chunk)))
log("staged in gold")
for label, sql in [("unit", "SELECT DISTINCT r.unit FROM st_r r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_r r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_s s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [x[0] for x in c.fetchall()]
    assert not miss or (CHECK and label == "package"), (label, miss)
c.execute("CREATE TEMP TABLE st_m ON COMMIT DROP AS SELECT k1, k2, bronze_sampleid, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_s")
c.execute("CREATE UNIQUE INDEX ON st_m (k1, k2)")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_number_alt, sample_type_id, sample_type_local, sample_context, elevation_m,
  comments, is_active, created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.fieldid, s.sno, s.k2, t.sample_type_id, s.slocal, coalesce(s.sctx, 'SURFACE'), s.elev,
  s.comments, true, '{TAG}', now(), '{SRC}'
FROM st_s s JOIN st_m m ON m.k1 = s.k1 AND m.k2 = s.k2 JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', bronze_sampleid::text, '{TAG}', now() FROM st_m""")
c.execute("SELECT pkg, count(*) FROM st_r GROUP BY 1 ORDER BY 2 DESC LIMIT 25"); log("top packages", c.fetchall())
if CHECK:
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  r.lab, meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(), NULL, NULL, r.comment
FROM st_r r JOIN st_m m ON m.k1 = r.k1 AND m.k2 = r.k2 JOIN geochem.analytes a ON a.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("results inserted", nins, "of", nres); assert nins == nres
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system, CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'NEGATIVE_CONVENTION' END,
  r.qualifier_code IS NULL
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'NSW source: negative value -> BELOW_DL_QUALIFIED (limit = DETLIMIT or |value|); positive DETECTED')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
# lithology (bronze)
c.execute("""CREATE TEMP TABLE st_l (bronze_sampleid bigint, lithology_code text, lithology_local text, observation_context text, dfrom numeric, dto numeric,
             logged_by text, logged_date timestamptz, sg text, sf text, sm text, sb text, alt text, comments text) ON COMMIT DROP""")
buf = io.StringIO(); w = csv.writer(buf)
for r in litho: w.writerow([N if x is None else x for x in r])
buf.seek(0); c.copy_expert("COPY st_l FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
c.execute(f"""
INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sampling_line_id, sample_id, occurrence_id, depth_from_m, depth_to_m,
  logged_by, logged_date, strat_group, strat_formation, strat_member, strat_bed, alteration_id, alteration_local, comments, is_active, created_by, created_date)
SELECT lt.lithology_id, l.lithology_local, l.observation_context, NULL, m.sample_id, NULL, l.dfrom, l.dto, l.logged_by, l.logged_date, l.sg, l.sf, l.sm, l.sb,
  NULL, l.alt, l.comments, true, '{TAG}', now()
FROM st_l l JOIN st_m m ON m.bronze_sampleid = l.bronze_sampleid LEFT JOIN geochem.lithology lt ON lt.lithology_code = l.lithology_code""")
log("lithology obs", c.rowcount)
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
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG); g.close(); os.remove(res_path)
