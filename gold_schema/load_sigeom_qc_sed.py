"""Québec SIGÉOM secondary-environment samples (lake and stream sediment, soil, till; Ministère des Ressources naturelles et des Forêts, CC BY 4.0)
-> interzona_cm gold, source CANADA_QC_SIGEOM_SED (rock samples and drill holes are CANADA_QC_SIGEOM, load_sigeom_qc.py).

Input: D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_geochem/sigeom.gpkg (31 Oct 2026): R1E02_ECHANTILLON_SEDIMENT, R1E03_RESULTAT_ANALYSE_ES.
What is loaded: every sediment / soil / till sample with results, typed from SIGÉOM's CODE_TYPE_ECHN_SEDM (the code and its meaning are kept in
sample_type_local); water samples (codes 01-07) are left out. The sieve mesh (MAILLE_TAMIS, µm) is the result fraction ('<177 µm').
Till heavy-mineral fractions (31, 48, 70-79) are typed Heavy Mineral Concentrate so they are never compared with bulk sediment or till.
Values and packages: as load_sigeom_qc.py (sigeom_dicts.py); '<' = detection limit, '>' = above upper limit, zero values left out.
Usage: python load_sigeom_qc_sed.py [--check]
  --check = stage, check every code against the dictionaries, insert the samples, then ROLLBACK before the result rows (a full trial insert of
  21M rows would leave as much dead space in the partition as the data itself).
"""
import os, sys, io, csv, time, collections, sqlite3
import psycopg2
from sigeom_dicts import sdate, METHOD, SKIP_METHODS, PACKAGES, ANALYTE, CONVERT, SKIP_ANALYTES, NEG_OK, MULT, PREC

CHECK = "--check" in sys.argv
TAG = "migration_sigeom_qc_sed_20261104"
SRC = "CANADA_QC_SIGEOM_SED"
PART = "canada_qc_sigeom_sed"
XID = "SIGEOM"
GEO = "D:/CriticalMineralsDB/Canada/Quebec_SIGEOM_geochem/sigeom.gpkg"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def out(v):
    return N if v is None or v == "" else v


# CODE_TYPE_ECHN_SEDM -> (gold sample type, SIGÉOM meaning); None = left out (water)
_T = {"00": ("SEDIMENT_SAMPLE", "undefined"), "20": ("SED_LAKE", "lake-bottom sediment"), "30": ("SED_STREAM", "stream sediment"),
      "31": ("SED_HMC", "stream sediment, heavy minerals"), "40": ("SOIL_SAMPLE", "soil, horizon not stated"), "41": ("SOIL_SAMPLE", "soil, O horizon"),
      "42": ("SOIL_A", "soil, AO horizon"), "43": ("SOIL_A", "soil, A horizon"), "44": ("SOIL_SAMPLE", "soil, AB horizon"), "45": ("SOIL_B", "soil, B horizon"),
      "46": ("SOIL_B", "soil, BC horizon"), "47": ("SOIL_C", "soil, C horizon"), "48": ("SED_HMC", "soil C horizon, heavy minerals"),
      "49": ("SOIL_C", "soil C horizon, clay from drilling"), "90": ("TILL_SAMPLE", "till, coarse fraction (>177 µm)")}
_TILL = {"0": "", "1": " (pionjar drilling)", "2": " (reverse-circulation drilling)", "3": " (rotosonic drilling)", "4": " (auger or shovel)",
         "5": ", basal", "6": ", basal (pionjar)", "7": ", basal (reverse circulation)", "8": ", basal (rotosonic)", "9": " (>177 µm)"}
for d, how in _TILL.items():
    basal = how.startswith(", basal")
    _T["6" + d] = ("TILL_BASAL" if basal else "TILL_SAMPLE", f"till fine fraction (<63 µm){how}")
    _T["7" + d] = ("SED_HMC", f"till heavy-mineral fraction{how}")
    _T["8" + d] = ("TILL_BASAL" if basal else "TILL_SAMPLE", f"till light fraction{how}")
STYPE = _T

geo = sqlite3.connect(f"file:{GEO}?mode=ro", uri=True)
docs = collections.defaultdict(list)
for s, rap in geo.execute("SELECT NUMR_ECHN_UNIQ, NUMR_RAPR FROM R1R17_ECHN_SEDIMENT_DOCUMENT"):
    if rap: docs[int(s)].append(rap)
srows, mesh, skipped = [], {}, collections.Counter()
for (s, typ, dt, fus, e, nn, prec, prof, maille, cont, ph, proj, comn) in geo.execute(
        """SELECT NUMR_ECHN_UNIQ, CODE_TYPE_ECHN_SEDM, DATE_ECHN, FUS, ESTN, NORD, CODE_PREC_LOCL, PROF_SEDM, MAILLE_TAMIS, CODE_CONTAMINATION, PH,
                  NUMR_PROJ_SEDM, COMN_ECHN_SEDM FROM R1E02_ECHANTILLON_SEDIMENT"""):
    sid = int(s)
    if typ not in STYPE: skipped["water or unknown type " + (typ or "")] += 1; continue
    st, meaning = STYPE[typ]
    if maille and maille not in (999,): mesh[sid] = f"<{int(maille)} µm"
    reps = sorted(set(docs.get(sid, ())))
    note = "; ".join(x for x in [(comn or "").strip(), f"depth {prof} m" if prof else "", f"pH {ph}" if ph else "",
                                 f"contamination code {cont}" if cont else "", f"project {proj}" if proj else "",
                                 f"reports {', '.join(reps[:5])}" + (" ..." if len(reps) > 5 else "") if reps else "", PREC.get(str(prec), "")] if x)
    srows.append([sid, st, f"SIGÉOM {typ}: {meaning}", e, nn, int(fus), sdate(dt), str(sid), note])
log("samples", len(srows), "| left out", dict(skipped))
keep = {r[0] for r in srows}

stats = collections.Counter()
res_path = os.path.join(HERE, "_sigeom_sed_results.csv")
with open(res_path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    for (s, nres, el, unit, tenr, mult, adate, flag, meth) in geo.execute(
            """SELECT NUMR_ECHN_UNIQ, NUMR_RESL_ANLS, CODE_ELMN_CHIM, CODE_UNITE_TENR, TENR, CODE_ANLS_MULT, DATE_RESL_ANLS, CODE_INDC_PLUS_PETT_QUE,
                      CODE_METH_ANLS FROM R1E03_RESULTAT_ANALYSE_ES"""):
        sid = int(s)
        if sid not in keep: stats["result of a water / unknown-type sample"] += 1; continue
        meth = meth or ""
        if meth in SKIP_METHODS: stats["method left out: " + meth] += 1; continue
        if el in SKIP_ANALYTES: stats["analyte left out: " + el] += 1; continue
        if tenr is None or tenr == 0: stats["zero or empty value"] += 1; continue
        pkg, mdesc = METHOD[meth]
        fac = 1.0
        if el in CONVERT:
            code, fac = CONVERT[el]
            unit = "ppm"
        else:
            code = ANALYTE.get(el, el)
        flag = (flag or "").strip()
        if flag == ">": q, val, ldl, udl = ">", tenr * fac, None, tenr * fac; stats["above upper limit"] += 1
        elif flag == "<" or (tenr < 0 and code not in NEG_OK): q, val, ldl, udl = "<", abs(tenr) * fac, abs(tenr) * fac, None; stats["below detection"] += 1
        else: q, val, ldl, udl = None, tenr * fac, None, None
        comment = "; ".join(x for x in [MULT.get(mult or "A", "code " + str(mult)), f"SIGÉOM element {el}" if el != code else ""] if x) or None
        w.writerow([sid, int(nres), pkg, code, unit, out(q), val, out(ldl), out(udl), out(sdate(adate)), f"{meth or 'not recorded'}: {mdesc}",
                    out(mesh.get(sid)), out(comment)])
        stats["values"] += 1
log("results staged", dict(stats))

# ---------------------------------------------------------------- gold load
# partitions first, in their own short transaction (CREATE ... PARTITION OF locks the parent table); empty partitions are harmless
p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
p0.autocommit = True
p0.cursor().execute("SET lock_timeout = '20s'")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_{PART} PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_{PART} PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
p0.close()
# keepalives: a dropped connection (network blip, sleeping laptop) then fails within minutes instead of hanging the load forever
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"],
                     keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '512MB'")


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); w = csv.writer(buf)
    for r in data:
        w.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


def utm(x, y, z):
    return f"CASE WHEN {z} BETWEEN 17 AND 22 AND {x} IS NOT NULL AND {y} IS NOT NULL THEN ST_Transform(ST_SetSRID(ST_MakePoint({x}, {y}), 26900 + {z}), 4326) END"


copy("st_sample", "sid bigint, stype text, stype_local text, x numeric, y numeric, zone int, sdate date, sample_no text, comments text", srows)
c.execute("""CREATE TEMP TABLE st_result (sid bigint, nres int, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric,
  adate date, meth_name text, fraction text, comment text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); nres = c.fetchone()[0]
assert nres == stats["values"], (nres, stats["values"])
log("staged: samples", len(srows), "results", nres)

c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for code, (name, mcode, basis, prio) in PACKAGES.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "Québec SIGÉOM geochemistry, grouped by SIGÉOM method code (labs vary and are not recorded)", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'P', 5, 'placeholder; see source_package_rules' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (code,))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "SIGÉOM method mapping " + TAG, code))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
log("dictionary checks passed")

# samples: ids drawn from the table's identity sequence (no temporary column on the live table)
c.execute(f"""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.sid, nextval('geochem.samples_sample_id_seq') AS sample_id, p.pt FROM st_sample s
  CROSS JOIN LATERAL (SELECT {utm('s.x', 's.y', 's.zone')} AS pt) p
  WHERE p.pt IS NOT NULL AND EXISTS (SELECT 1 FROM st_result r WHERE r.sid = s.sid)""")
c.execute("CREATE UNIQUE INDEX ON st_map (sid)")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, sample_number, sample_type_id, sample_type_local, sample_context, sample_date, comments, is_active,
  created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, m.pt, s.sample_no, t.sample_type_id, s.stype_local, 'SURFACE', s.sdate, nullif(s.comments, ''), true, '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (sid) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', 'SED:' || sid, '{TAG}', now() FROM st_map   -- SED: rock and sediment numbers can coincide""")
c.execute("SELECT count(*) FROM st_sample s WHERE NOT EXISTS (SELECT 1 FROM st_map m WHERE m.sid = s.sid)")
log("samples left out (no usable location or no results)", c.fetchone()[0])
c.execute(f"""SELECT t.sample_type_code, count(*) FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id)
              WHERE s.source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC"""); log("sample types", c.fetchall())
c.execute(f"""SELECT count(*) FROM geochem.samples WHERE source_system = '{SRC}' AND (lat NOT BETWEEN 44.5 AND 63 OR lon NOT BETWEEN -80 AND -57)""")
log("samples outside Québec box", c.fetchone()[0])
if CHECK:
    c.execute("SELECT count(*) FROM st_result r WHERE NOT EXISTS (SELECT 1 FROM st_map m WHERE m.sid = r.sid)")
    log("results that would be left out (sample without location)", c.fetchone()[0])
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back before the result rows"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, r.meth_name, NULL, r.val, r.ldl, r.udl, NULL, r.adate, false, true, '{TAG}', now(),
  'SIGEOM:' || r.sid || ':' || r.nres, r.fraction, r.comment
FROM st_result r
JOIN st_map m ON m.sid = r.sid
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results_{PART}"); ngr = c.fetchone()[0]
c.execute("SELECT count(*) FROM st_result r WHERE EXISTS (SELECT 1 FROM st_map m WHERE m.sid = r.sid)"); want = c.fetchone()[0]
log("gold results", ngr, "of", want, "in", round(time.time() - t0), "s")
assert ngr == want, (ngr, want)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UDL' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_sigeom_sed_20261104', now(), now(), count(*), 'rule-based classification at load (SIGÉOM < / > flag)'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute(f"SELECT result_status, count(*) FROM geochem.result_classifications_{PART} GROUP BY 1 ORDER BY 2 DESC"); log("classification", c.fetchall())
c.execute(f"""SELECT p.package_code, count(*) FROM geochem.analytical_results_{PART} r JOIN geochem.analytical_packages p USING (package_id)
              GROUP BY 1 ORDER BY 2 DESC"""); log("per package", c.fetchall())
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.source_system = '{SRC}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
log("samples without results (must be 0)", c.fetchone()[0])
g.commit(); log("COMMITTED")
g.close()
os.remove(res_path)
