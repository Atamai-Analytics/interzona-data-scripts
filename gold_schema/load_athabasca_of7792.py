"""Athabasca Basin Uranium Geochemistry Database v.2 (Geological Survey of Canada Open File 7792, Wright, Potter and Comeau 2015,
doi:10.4095/296461; Open Government Licence - Canada) -> interzona_cm gold, source CANADA_ATHABASCA_OF7792.

Input: AthBasinGeochem.csv exported from Ath_Basin_lithgeoch2015.mdb (PowerShell + ACE OLEDB; one row per sample, 180 columns, 144 of them
<Element>_<digest p|t>_<unit ppm|pct|ppb>), in D:/CriticalMineralsDB/Canada/Athabasca_OF7792.
What is loaded
  - every sample (the compilers already removed lab QAQC samples): drill-core intervals (DDH_FROM/DDH_TO present) as CORE_SAMPLE /
    DRILLHOLE_INTERVAL with depths and the sample elevation, outcrops as ROCK_OUTCROP / SURFACE
  - every value: negative = below detection at |value| ('<'; LOI may be negative and is kept as a value); zero is left out (some companies
    used 0 for 'below detection', so it cannot be read either way)
  - packages by laboratory and digestion: partial (SRC 9:1 HNO3:HCl, aqua regia, NTEL weak acid), total (3- or 4-acid), boron by Na2O2
    fusion, uranium by fluorimetry after the SRC partial digest
  - lead isotopes Pb204..Pb208 (ppm of each isotope) - four analytes added to the dictionary
Drill holes: a hole is REPORT_ID + DDH_SAMPID with its collar (UTM NAD83 zone 13, as compiled). It is linked to an existing CANADA_SK_SGS collar
when the normalised names agree (case, punctuation and leading zeros ignored), that collar lies within 1 km (nearest wins), AND it cites the same
assessment file or lies within 200 m; otherwise a new
drilling.drillholes row is made under this source with the compiled collar. hole_matches_of7792.csv records every decision.
Usage: python load_athabasca_of7792.py [--check]   (--check = stage, match, insert holes and samples, ROLLBACK before the result rows)
"""
import os, sys, io, csv, re, time, collections
import psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_athabasca_of7792_20261106"
SRC = "CANADA_ATHABASCA_OF7792"
PART = "canada_athabasca_of7792"
XID = "GSC_OF7792"
R = "D:/CriticalMineralsDB/Canada/Athabasca_OF7792/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
COL = re.compile(r"^(?P<el>[A-Za-z0-9]+)_(?P<dg>[pt])_(?P<u>ppm|pct|ppb)$")
UNIT = {"ppm": "ppm", "pct": "%", "ppb": "ppb"}
ISOTOPES = {"Pb204": "Lead-204", "Pb206": "Lead-206", "Pb207": "Lead-207", "Pb208": "Lead-208"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def num(s):
    try:
        return float(s) if s not in ("", None) else None
    except ValueError:
        return None


def lab_code(lab):
    return {"SRC": "SRC", "Loring": "LORING", "NTEL": "NTEL", "ACME Laboratories": "ACME"}.get(lab.strip(), "UNK")


def partial_code(txt):
    t = txt.strip().upper()
    if t == "HNO3/HCL": return "SRCP", "partial digest, 9:1 HNO3:HCl (SRC-type partial)", "AR-ICPOES"
    if t == "AQUA REGIA": return "AR", "aqua regia partial digest", "AR-ICPOES"
    if "2% HNO3" in t or "HCLO4" in t: return "WEAK", f"weak-acid partial digest ({txt.strip()})", "WEAKACID-ICPMS"
    return "PUNK", "partial digest (not stated)", "UNKNOWN-UNKNOWN"


def package(lab, el, dg, row):
    lc = lab_code(lab)
    if dg == "p":
        if el == "U" and "fluorimetry" in row["ALT_DIGESTION"].lower():
            return f"ATH-{lc}-UFLUOR", (f"OF7792 {lab.strip() or 'lab not stated'} - uranium by fluorimetry after partial digest", "AR-FLUOR", "P", 2)
        code, name, meth = partial_code(row["PARTIAL_DIGESTION"])
        return f"ATH-{lc}-{code}", (f"OF7792 {lab.strip() or 'lab not stated'} - {name}", meth, "P", 3)
    if el == "B" and "na2o2" in row["BORON_DIGESTION"].lower():
        return f"ATH-{lc}-BFUS", (f"OF7792 {lab.strip() or 'lab not stated'} - boron by Na2O2 fusion", "NAPEROX-ICPOES", "T", 1)
    tot = row["TOTAL_DIGESTION"].strip()
    if tot:
        return f"ATH-{lc}-TOT", (f"OF7792 {lab.strip() or 'lab not stated'} - total digest ({tot})", "4A-ICPOES", "T", 1)
    return f"ATH-{lc}-TUNK", (f"OF7792 {lab.strip() or 'lab not stated'} - total digest (not stated)", "UNKNOWN-UNKNOWN", "T", 2)


# ---------------------------------------------------------------- stage
stats = collections.Counter()
samples, holes, pk = [], {}, {}
res_path = os.path.join(HERE, "_of7792_results.csv")
with open(R + "AthBasinGeochem.csv", encoding="utf-8") as fh, open(res_path, "w", newline="", encoding="utf-8") as out:
    rd = csv.DictReader(fh); w = csv.writer(out)
    ecols = [(c, COL.match(c)) for c in rd.fieldnames if COL.match(c)]
    log("element columns", len(ecols))
    for row in rd:
        e, n = num(row["E_NAD83Z13"]), num(row["N_NAD83Z13"])
        if e is None or n is None:
            stats["no coordinates"] += 1; continue
        key = row["OBJECTID"]
        core = num(row["DDH_FROM"]) is not None
        hk = f"{row['REPORT_ID']}|{row['DDH_SAMPID']}" if core else None
        if core:
            h = holes.setdefault(hk, {"report": row["REPORT_ID"], "name": row["DDH_SAMPID"], "es": [], "ns": [], "az": num(row["AZIMUTH"]),
                                      "dip": num(row["DIP"]), "z": num(row["DDH_ELEV"]), "zdem": row["DDH_from_DEM"], "maxto": 0.0,
                                      "company": row["COMPANY"], "dataset": row["DATASET"], "dep": row["DEP_AREA"]})
            h["es"].append(e); h["ns"].append(n); h["maxto"] = max(h["maxto"], num(row["DDH_TO"]) or 0)
        lith = ", ".join(x for x in [row["LITHOLOGY_BASIC"] or "lithology not stated", row["FORMATION"], row["BASEMENT_CODES"]] if x)
        note = "; ".join(x for x in [f"GSC Open File 7792 ({row['DATASET']})", f"report {row['REPORT_ID']}" if row["REPORT_ID"] else "", row["COMPANY"],
                                     f"work {row['YEAR_FROM']}-{row['YEAR_TO']}" if row["YEAR_FROM"] else "", f"area {row['GEN_AREA']}" if row["GEN_AREA"] else "",
                                     f"deposit area {row['DEP_AREA']}" if row["DEP_AREA"] else "", f"lab {row['ANALYTICAL_LABORATORY']}" if row["ANALYTICAL_LABORATORY"] else "",
                                     f"OF7792 OBJECTID {key}"] if x)
        dfrom, dto = num(row["DDH_FROM"]), num(row["DDH_TO"])
        samples.append([key, "CORE_SAMPLE" if core else "ROCK_OUTCROP", f"OF7792: {'drill core' if core else 'outcrop'} - {lith}", e, n,
                        row["DDH_SAMPID"] or None, f"{row['DDH_SAMPID']} {dfrom:g}-{dto:g} m" if core and dto is not None else (row["DDH_SAMPID"] or key),
                        note, "DRILLHOLE_INTERVAL" if core else "SURFACE", hk, dfrom, dto, num(row["Sample_Elevation"])])
        stats["core samples" if core else "outcrop samples"] += 1
        for c, m in ecols:
            v = num(row[c])
            if v is None: continue
            el, dg, u = m["el"], m["dg"], m["u"]
            if v == 0: stats["zero value left out"] += 1; continue
            if v < 0 and el != "LOI": qual, val, ldl = "<", -v, -v; stats["below detection"] += 1
            else: qual, val, ldl = None, v, None
            pcode, pinfo = package(row["ANALYTICAL_LABORATORY"], el, dg, row)
            pk[pcode] = pinfo
            w.writerow([key, pcode, el, UNIT[u], qual or N, val, ldl if ldl is not None else N, c])
            stats["values"] += 1
log("staged", dict(stats), "| holes", len(holes), "| packages", len(pk))

# ---------------------------------------------------------------- gold load
p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
p0.autocommit = True
p0.cursor().execute("SET lock_timeout = '20s'")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_{PART} PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_{PART} PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
p0.close()
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"],
                     keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '256MB'")


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


hrows = [[k, h["report"], h["name"], sum(h["es"]) / len(h["es"]), sum(h["ns"]) / len(h["ns"]), h["az"], h["dip"], h["z"], h["zdem"], h["maxto"] or None,
          h["company"], h["dataset"], h["dep"]] for k, h in holes.items()]
copy("st_hole", "hk text, report text, name text, e float8, n float8, az float8, dip float8, z float8, zdem text, maxto float8, company text, dataset text, dep text", hrows)
copy("st_sample", "k text, stype text, stype_local text, e float8, n float8, field_no text, sample_no text, comments text, ctx text, hk text, dfrom float8, dto float8, zs float8", samples)
c.execute("""CREATE TEMP TABLE st_result (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, col text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); nres = c.fetchone()[0]
assert nres == stats["values"], (nres, stats["values"])
c.execute("ALTER TABLE st_hole ADD COLUMN pt geometry"); c.execute("UPDATE st_hole SET pt = ST_Transform(ST_SetSRID(ST_MakePoint(e, n), 26913), 4326)")
c.execute("ALTER TABLE st_sample ADD COLUMN pt geometry"); c.execute("UPDATE st_sample SET pt = ST_Transform(ST_SetSRID(ST_MakePoint(e, n), 26913), 4326)")
log("staged in db: holes", len(hrows), "samples", len(samples), "results", nres)

# lead isotopes: add to the analyte dictionary if missing
for code, name in ISOTOPES.items():
    c.execute("""INSERT INTO geochem.analytes (analyte_code, analyte_name, element_symbol, is_element, is_oxide, typical_reporting_unit, analysis_group,
                   notes, is_active, created_by, created_date)
                 SELECT %s, %s, 'Pb', false, false, 'ppm', 'Element', 'Lead isotope concentration (ppm of the isotope); added for GSC Open File 7792', true, %s, now()
                 WHERE NOT EXISTS (SELECT 1 FROM geochem.analytes WHERE analyte_code = %s)""", (code, name, TAG, code))

# ---- hole matching: same normalised name, existing CANADA_SK_SGS collar within 1 km, nearest wins
NORM = "regexp_replace(upper(regexp_replace({x}, '[^A-Za-z0-9]', '', 'g')), '([A-Z])0+([0-9])', '\\1\\2', 'g')"
c.execute(f"""CREATE TEMP TABLE st_match ON COMMIT DROP AS
  SELECT DISTINCT ON (s.hk) s.hk, d.drillhole_id, ST_Distance(s.pt::geography, d.geog) AS dist_m, d.hole_name AS sk_name,
         position(s.report IN coalesce(d.comments, '')) > 0 AS same_file
  FROM st_hole s JOIN drilling.drillholes d ON d.source_system = 'CANADA_SK_SGS' AND d.is_active
   AND ST_DWithin(d.geog, s.pt::geography, 1000) AND {NORM.format(x='d.hole_name')} = {NORM.format(x='s.name')}
  ORDER BY s.hk, ST_Distance(s.pt::geography, d.geog)""")
# high confidence only: the name match must also cite the same assessment file or lie within 200 m (a generic name such as 'W-1' 700 m away is not
# trusted); the others become holes of their own
c.execute("DELETE FROM st_match WHERE NOT same_file AND dist_m > 200")
log("name matches dropped (different file and more than 200 m apart)", c.rowcount)
c.execute("SELECT count(*), count(*) FILTER (WHERE same_file), count(*) FILTER (WHERE dist_m <= 100) FROM st_match"); m_all, m_file, m_100 = c.fetchone()
log(f"holes matched to Saskatchewan collars: {m_all} of {len(hrows)} (same assessment file {m_file}, within 100 m {m_100})")
c.execute("""SELECT s.hk, s.report, s.name, m.drillhole_id, m.sk_name, round(m.dist_m::numeric, 1), m.same_file FROM st_hole s LEFT JOIN st_match m USING (hk) ORDER BY 1""")
with open(os.path.join(HERE, "hole_matches_of7792.csv"), "w", newline="", encoding="utf-8") as f:
    wr = csv.writer(f); wr.writerow(["hole_key", "report_id", "of7792_name", "sk_drillhole_id", "sk_hole_name", "distance_m", "same_assessment_file"]); wr.writerows(c.fetchall())

# ---- new holes for the unmatched ones
c.execute(f"""
INSERT INTO drilling.drillholes (source_system, source_hole_id, hole_name, company, drill_type_id, drill_type_local, total_depth_m, azimuth_deg, dip_deg,
  collar_elevation_m, lat, lon, geom, geog, original_x, original_y, original_crs, position_method, elevation_method, comments, is_active, created_by, created_date)
SELECT '{SRC}', s.hk, s.name, nullif(s.company, ''), t.drill_type_id, 'diamond drill core (assessment report)', NULL,
  CASE WHEN s.az BETWEEN 0 AND 360 THEN s.az END, CASE WHEN s.dip BETWEEN 0 AND 90 THEN -s.dip END, s.z, ST_Y(s.pt), ST_X(s.pt), s.pt, s.pt::geography,
  s.e, s.n, 'NAD83 / UTM zone 13N (as compiled in GSC OF 7792)', 'compiled from the assessment report (GSC OF 7792)',
  CASE WHEN s.zdem = '1' THEN 'digital elevation model (OF 7792)' ELSE 'as reported' END,
  concat_ws('; ', 'GSC Open File 7792 (' || s.dataset || ')', 'assessment report ' || nullif(s.report, ''), 'deepest sample ' || round(s.maxto::numeric, 1) || ' m',
            'deposit area ' || nullif(s.dep, ''), 'no matching Saskatchewan GeoAtlas collar within 1 km under this name'), true, '{TAG}', now()
FROM st_hole s JOIN geochem.drill_types t ON t.drill_type_code = 'DIAMOND'
WHERE NOT EXISTS (SELECT 1 FROM st_match m WHERE m.hk = s.hk)""")
log("new drill holes (no matching collar)", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'DRILLHOLE', drillhole_id, '{XID}', 'HOLE:' || source_hole_id, '{TAG}', now() FROM drilling.drillholes WHERE created_by = '{TAG}'""")
c.execute(f"""CREATE TEMP TABLE st_holeid ON COMMIT DROP AS
  SELECT hk, drillhole_id FROM st_match
  UNION ALL SELECT source_hole_id, drillhole_id FROM drilling.drillholes WHERE created_by = '{TAG}'""")

# ---- packages and dictionary checks
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for code, (name, mcode, basis, prio) in pk.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "GSC Open File 7792 (Athabasca Basin uranium geochemistry) analyses grouped by laboratory and digestion", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'P', 5, 'placeholder; see source_package_rules' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (code,))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "OF 7792 laboratory/digestion mapping " + TAG, code))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL"),
                   ("core sample without a hole", "SELECT s.k FROM st_sample s WHERE s.hk IS NOT NULL AND NOT EXISTS (SELECT 1 FROM st_holeid h WHERE h.hk = s.hk) LIMIT 5")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
log("dictionary checks passed")

# ---- samples
c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE ST_Y(s.pt) BETWEEN 55 AND 61 AND ST_X(s.pt) BETWEEN -115 AND -100 AND EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
c.execute("CREATE UNIQUE INDEX ON st_map (k)")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments, is_active,
  created_by, created_date, source_system, drillhole_id, depth_from_m, depth_to_m, elevation_m)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, s.pt, s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, true, '{TAG}', now(), '{SRC}',
  h.drillhole_id, s.dfrom, s.dto, s.zs
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype LEFT JOIN st_holeid h ON h.hk = s.hk""")
log("samples", c.rowcount, "| left out (no results or position outside the basin area)", len(samples) - c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', 'OBJECTID:' || k, '{TAG}', now() FROM st_map""")
c.execute(f"""SELECT t.sample_type_code, s.sample_context, count(*), count(s.drillhole_id), count(DISTINCT s.drillhole_id) FROM geochem.samples s
              JOIN geochem.sample_types t USING (sample_type_id) WHERE s.source_system = '{SRC}' GROUP BY 1, 2 ORDER BY 3 DESC""")
log("samples by type (n, with hole, distinct holes)", c.fetchall())
if CHECK:
    c.execute("SELECT pkg, count(*) FROM st_result GROUP BY 1 ORDER BY 2 DESC"); log("values per package", c.fetchall())
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back before the result rows"); sys.exit(0)

# ---- results
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, p.package_name, NULL, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(),
  NULL, NULL, 'OF7792 column ' || r.col
FROM st_result r
JOIN st_map m ON m.k = r.k
JOIN geochem.analytes a ON a.analyte_code = r.analyte
JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg
LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"SELECT count(*) FROM geochem.analytical_results_{PART}"); ngr = c.fetchone()[0]
c.execute("SELECT count(*) FROM st_result r WHERE EXISTS (SELECT 1 FROM st_map m WHERE m.k = r.k)"); want = c.fetchone()[0]
log("gold results", ngr, "of", want, "in", round(time.time() - t0), "s")
assert ngr == want, (ngr, want)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_of7792_20261106', now(), now(), count(*), 'rule-based classification at load (OF 7792 negative = below detection at |value|)'
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
