"""South Australia SARIG rock-sample chemistry, SURFACE samples with laboratory assays (phase 1) -> interzona_cm gold, new source AUSTRALIA_SA_SARIG
(own partition; rollback = delete by created_by = TAG).
Licence: CC BY 4.0 (Government of South Australia, 'Disclaimer and CCBY.txt' in the public bucket; Licence_Evidence/SA_SARIG). Credit: "Contains
SARIG data (Geological Survey of South Australia, Department for Energy and Mining), Government of South Australia, licensed under CC BY 4.0".
Input: D:/CriticalMineralsDB/Australia/SA_SARIG/sarig_surface_lab.csv, written by fetch_sa_sarig_surface.py from sarig_rs_chem_exp.csv (July 2025
export): long format, one row per result with the sample's GDA2020 position, lithology, collector and date. Method dictionary:
_slices/chem_method_code_desc.csv (laboratory + method code -> description, digestion, determination).
Rules
  * one sample per SARIG SAMPLE_NO; sample type from SAMPLE_SOURCE (soil, calcrete, rock, stream / lake sediment, lag, gravel, auger, channel,
    trench, vegetation); company / collector, collector number, lithology, stratigraphy and SARIG site no. in comments.
  * portable / in-house XRF left out: XRFDelta and any XRF code reported as 'In-house determinations by originating exploration company'
    (the fetch already dropped Niton / Olympus / Innov-X / pXRF codes). 'XRF, lab unspecified' rows are kept at the lowest priority.
  * packages by method family from the dictionary text: SA-<digestion>-<finish> (aqua regia, four-acid, three-acid / perchloric, fusion,
    fire assay, partial / selective leaches - MMI, TerraLeach, BLEG, water, cyanide - and no digestion) x (ICP-MS, ICP-OES, AAS, XRF, INAA,
    gravimetric / LECO / ISE ...). Basis T for four-acid, fusion, fire assay, XRF, INAA; P otherwise. The laboratory name is kept per result.
  * values: number -> DETECTED; '<x' -> BELOW_DL_QUALIFIED (dl x); '>x' -> ABOVE_UDL; negative values only kept for LOI; units ppm / ppb / %
    (g/T -> ppm); other units (ug/L, uS/cm, none) and non-element codes (pH, EC, Pb isotopes, carbonate forms ...) left out.
Usage: python load_sa_sarig_surface.py [--check]
"""
import os, sys, io, csv, re, time, datetime, collections
import pandas as pd, psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_sa_sarig_surface_20261116"
SRC, PART, XID = "AUSTRALIA_SA_SARIG", "australia_sa_sarig", "SARIG_SAMPLE_NO"
F = "D:/CriticalMineralsDB/Australia/SA_SARIG/sarig_surface_lab.csv"
MD = "D:/CriticalMineralsDB/Australia/SA_SARIG/_slices/chem_method_code_desc.csv"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


STYPE = {"Soil": "SOIL_SAMPLE", "Loam": "SOIL_SAMPLE", "Sample specifically for bulk leach extractable gold analysis": "SOIL_SAMPLE",
         "Calcrete": "SOIL_SAMPLE", "Lag sample, surface sample consisting of gravelly material.": "SEDIMENT_SAMPLE",
         "Magnetic lag fraction": "SEDIMENT_SAMPLE", "Gravel": "SEDIMENT_SAMPLE", "Auger sample from near surface": "SOIL_AUG",
         "Rock outcrop / float": "ROCK_SAMPLE", "Rock outcrop sample": "ROCK_OUTCROP", "Rock float sample (not in situ)": "ROCK_FLOAT",
         "Rock subcrop sample (in situ, not attached to bedrock)": "ROCK_OUTCROP", "Channel (linear rock chip/outcrop sampling)": "CHANNEL_SAMPLE",
         "Costean (trench)": "TRENCH_SAMPLE", "Stream sediment": "SED_STREAM", "Lake floor sediment": "SED_LAKE", "Vegetation": "VEGETATION_SAMPLE"}
LOCAL = {"Calcrete": "SARIG calcrete (pedogenic carbonate) sample", "Lag sample, surface sample consisting of gravelly material.": "SARIG lag sample",
         "Magnetic lag fraction": "SARIG magnetic lag fraction", "Gravel": "SARIG gravel sample", "Loam": "SARIG loam sample",
         "Sample specifically for bulk leach extractable gold analysis": "SARIG soil sample for BLEG gold"}
ANALYTE = {"Total": "Sum", "FeTO3": "FETO3"}
SKIP_CODE = {"pH", "EC", "206Pb", "207Pb", "208Pb", "HMIN", "O2", "TGC", "Fe2", "Fe3", "CO3", "CaMg(CO3)2", "H2O_plus", "H2O_minus"}
UNIT = {"ppm": ("ppm", 1.0), "ppb": ("ppb", 1.0), "%": ("%", 1.0), "g/T": ("ppm", 1.0), "g/t": ("ppm", 1.0)}
TOTAL_DIG = {"4A", "FUS", "FA", "NONE"}


def family(code, desc, dig, det):
    t = " ".join([code, desc, dig, det]).lower()
    c = code.lower()
    if c in ("me-ms81", "me-icp06"): d = "FUS"
    elif "microwave" in t: d = "MW"
    elif "enzyme" in t or "ezyme" in t: d = "ENZ"
    elif re.search(r"\bmmi\b|mobile metal", t): d = "MMI"
    elif "terra" in t or c.startswith("tl"): d = "TL"
    elif "bleg" in t or "bulk leach" in t or "cyanide" in t: d = "CN"
    elif "water leach" in t or re.search(r"\bwl\b", c): d = "WATER"
    elif re.search(r"partial|selective|weak|buffered|ionic|enzyme|neutral", t): d = "LEACH"
    # 2026-11-18 fix (fix_sa_method_family.py): the method's own description wins over code patterns
    elif re.search(r"four acid|4 acid|four-acid|multi.?acid|mixed acid", t) and "aqua" not in t and "fire assay" not in t: d = "4A"
    elif re.search(r"aqua.?regia", t) and not re.search(r"fire.?assay|lead collection", t): d = "AR"
    elif "fire assay" in t or c.startswith(("fa", "pgm", "au-")) or "fa/" in c or c.startswith("au"): d = "FA"
    elif re.search(r"aqua regia|\bar\b|ar/|arm\d|b/oes|b/eoes|b/ms|bt/oes|bveg|me-icp41|me-ms41|aqua", t): d = "AR"
    elif re.search(r"four acid|4 acid|4a|four-acid|hf|multi.?acid|mixed acid|near total|me-icp61|me-ms61|ic3|ic4r", t): d = "4A"
    elif re.search(r"three.?acid|3 acid|two.?acid|2 acid|perchloric|hclo4|m/aas", t): d = "3A"
    elif "nitric" in t: d = "HNO3"
    elif re.search(r"fusion|fused|borate|peroxide|sinter|xf\d|xrf4b|fs/", t): d = "FUS"
    elif re.search(r"xrf|neutron|inaa|pressed|leco|combust|gravimet|loi", t): d = "NONE"
    else: d = "UNK"
    if re.search(r"mass spec|icp-?ms|/ms\b|-ms\d|\bms\b|elan|ims\d", t) or c.startswith("arm") or d in ("MW", "ENZ"): e = "ICPMS"
    elif re.search(r"oes|aes|optical|emission|icp\b|icp-|ic2e|ic3e", t): e = "ICPOES"
    elif re.search(r"atomic absorption|\baas\b|/aas|\baa\b|gfaas|graphite furnace|carbon rod", t) or d == "CN": e = "AAS"
    elif "xrf" in t or "x-ray fl" in t: e = "XRF"
    elif "neutron" in t or "inaa" in t: e = "INAA"
    elif "leco" in t or "combust" in t: e = "LECO"
    elif "gravimet" in t or "loi" in t or "loss on ignition" in t: e = "GRAV"
    elif "electrode" in t or "ise" in t: e = "ISE"
    elif "colori" in t: e = "COLOR"
    else: e = "OTHER"
    if e in ("XRF", "INAA", "LECO", "GRAV") and d == "UNK": d = "NONE"
    return d, e


METHOD = {("AR", "ICPMS"): "AR-ICPMS", ("AR", "ICPOES"): "AR-ICPOES", ("AR", "AAS"): "AR-AAS", ("4A", "ICPMS"): "4A-ICPMS", ("4A", "ICPOES"): "4A-ICPOES",
          ("4A", "AAS"): "4A-AAS", ("3A", "ICPMS"): "MX-ICPMS", ("3A", "ICPOES"): "MX-ICPOES", ("FUS", "ICPMS"): "LIBOR-ICPMS", ("FUS", "ICPOES"): "LIBOR-ICPOES",
          ("FUS", "XRF"): "LIBOR-XRF", ("FUS", "AAS"): "LIBOR-AAS", ("FA", "AAS"): "FA-AAS", ("FA", "ICPMS"): "FA-ICPMS", ("FA", "ICPOES"): "FA-ICPOES",
          ("FA", "OTHER"): "FA-AAS", ("MMI", "ICPMS"): "MMI-ICPMS", ("CN", "AAS"): "CN-AAS", ("CN", "ICPMS"): "CN-ICPMS", ("WATER", "ICPMS"): "WATER-ICPMS",
          ("LEACH", "ICPMS"): "WEAKACID-ICPMS", ("NONE", "XRF"): "NONE-XRF", ("NONE", "INAA"): "NONE-INAA", ("NONE", "LECO"): "NONE-LECO",
          ("NONE", "GRAV"): "NONE-GRAV", ("UNK", "ICPMS"): "UNK-ICPMS", ("MW", "ICPMS"): "MW-ICPMS", ("ENZ", "ICPMS"): "ENZYME-ICPMS",
          ("HNO3", "AAS"): "HNO3-AAS", ("HNO3", "ICPMS"): "HNO3-ICPMS", ("TL", "ICPMS"): "WEAKALK-ICPMS"}
PRIO = {"ICPMS": 1, "ICPOES": 2, "XRF": 3, "INAA": 2, "AAS": 4, "LECO": 1, "GRAV": 3, "ISE": 4, "COLOR": 5, "OTHER": 6}


def pkg_rule(d, e):
    basis = "T" if d in TOTAL_DIG else "P"
    prio = PRIO[e] + (6 if d in ("MMI", "TL", "CN", "WATER", "LEACH", "ENZ") else 0) + (3 if d in ("UNK", "HNO3") else 0)
    return METHOD.get((d, e), "UNKNOWN-UNKNOWN"), basis, prio


md = pd.read_csv(MD, dtype=str, keep_default_na=False)
MDX = {(r.LABORATORY_NAME.strip(), r.CHEM_METHOD.strip()): (r.CHEM_METHOD_DESC, r.DIGESTION_DESC, r.DETERMINATION_DESC) for r in md.itertuples()}
MDC = {}
for r in md.itertuples(): MDC.setdefault(r.CHEM_METHOD.strip(), (r.CHEM_METHOD_DESC, r.DIGESTION_DESC, r.DETERMINATION_DESC))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT analyte_code FROM geochem.analytes"); known = {r[0] for r in c.fetchall()}


def date(s):
    try:
        d = datetime.datetime.strptime(s.strip(), "%d/%m/%Y").date()
        return d.isoformat() if 1900 < d.year <= 2026 else None
    except ValueError:
        return None


stats = collections.Counter()
samples, pkgs = {}, {}
res_path = os.path.join(HERE, "_sa_sarig_results.csv")
nres = 0
with open(res_path, "w", newline="", encoding="utf-8") as out:
    w = csv.writer(out)
    for ch in pd.read_csv(F, dtype=str, keep_default_na=False, chunksize=1_000_000):
        for r in ch.itertuples(index=False):
            lab, meth = r.LABORATORY.strip(), r.CHEM_METHOD_CODE.strip()
            if meth == "CALC": stats["calculated values left out"] += 1; continue
            if meth == "XRFDelta" or ("in-house" in lab.lower() and "xrf" in meth.lower()):
                stats["in-house / portable XRF left out"] += 1; continue
            code = ANALYTE.get(r.CHEM_CODE.strip(), r.CHEM_CODE.strip())
            if code in SKIP_CODE or code not in known: stats["analyte left out " + code] += 1; continue
            u = UNIT.get(r.UNIT.strip())
            if u is None: stats["unit left out " + r.UNIT] += 1; continue
            v = r.VALUE.strip()
            m = re.match(r"^([<>])\s*(-?[0-9.]+(?:[eE][-+]?\d+)?)$", v)
            try:
                if m:
                    x = float(m.group(2)) * u[1]
                    if x <= 0: stats["bad limit"] += 1; continue
                    q, val, ldl, udl, st = ("<", x, x, None, "B") if m.group(1) == "<" else (">", x, None, x, "A")
                else:
                    x = float(v) * u[1]
                    if x < 0 and code != "LOI": stats["negative value left out"] += 1; continue
                    if x == 0: stats["zero left out"] += 1; continue
                    q, val, ldl, udl, st = None, x, None, None, "D"
            except ValueError:
                stats["unparsed value"] += 1; continue
            k = r.SAMPLE_NO.strip()
            if k not in samples:
                try: lat, lon = float(r.LATITUDE_GDA2020), float(r.LONGITUDE_GDA2020)
                except ValueError: stats["no position"] += 1; continue
                src = r.SAMPLE_SOURCE
                note = "; ".join(x for x in [
                    f"SARIG sample {k}", f"source: {src}", f"collected by {r.COLLECTED_BY}" if r.COLLECTED_BY else "",
                    f"collector no. {r.COLLECTORS_NUMBER}" if r.COLLECTORS_NUMBER else "",
                    f"lithology {r.LITHOLOGY_NAME}{' ' + r.LITHOLOGY_MODIFIER if r.LITHOLOGY_MODIFIER else ''}" if r.LITHOLOGY_NAME else "",
                    f"rock group {r.ROCK_GROUP}" if r.ROCK_GROUP else "", f"stratigraphy {r.STRAT_NAME}" if r.STRAT_NAME else "",
                    f"SARIG site {r.SITE_NO}" if r.SITE_NO else ""] if x)
                samples[k] = [k, STYPE[src], (LOCAL.get(src) or f"SARIG {src.lower()}")[:100], lat, lon, r.COLLECTORS_NUMBER or None, k,
                              note[:1000], "SURFACE", date(r.COLLECTED_DATE)]
                stats["samples " + STYPE[src]] += 1
            desc = MDX.get((lab, meth)) or MDC.get(meth) or (r.CHEM_METHOD_DESC, "", "")
            d, e = family(meth, *desc)
            pk = f"SA-{d}-{e}"
            pkgs.setdefault(pk, (d, e)); stats["pkg " + pk] += 1
            w.writerow([k, pk, code, u[0], q or N, val, N if ldl is None else ldl, N if udl is None else udl,
                        lab[:100] or "Not recorded", f"SARIG method {meth}: {desc[0][:150]}", st])
            nres += 1
        log("rows read so far, results staged", nres, "samples", len(samples))
log("samples", len(samples), "results", nres)
for k in sorted(stats): log(f"  {k}: {stats[k]:,}")

if not CHECK:
    g.commit(); g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
DIGN = {"AR": "aqua regia", "4A": "four-acid (near total)", "3A": "three-acid / perchloric", "FUS": "fusion", "FA": "fire assay", "MMI": "MMI partial leach",
        "TL": "TerraLeach partial digest", "CN": "cyanide / BLEG leach", "WATER": "water leach", "LEACH": "other partial / selective leach",
        "NONE": "no digestion", "UNK": "digestion not recorded", "MW": "microwave acid digestion", "ENZ": "enzyme leach",
        "HNO3": "nitric acid leach"}
for pk, (d, e) in pkgs.items():
    mcode, basis, prio = pkg_rule(d, e)
    name = f"SARIG surface samples - {DIGN[d]}, {e}"
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pk, name, mid[mcode], name + " (method family assigned from the SARIG laboratory method dictionary; original method code in result_comment)", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'SARIG method family' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (basis, prio, pk))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "SARIG method family " + TAG, pk))
    log("package", pk, mcode, basis, prio)


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data: wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0); c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date", samples.values())
c.execute("""CREATE TEMP TABLE st_result (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric, lab text, comment text,
             st text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
for label, sql in [("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
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
log("samples inserted", c.rowcount)
c.execute(f"INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date) SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map")
c.execute("SELECT pkg, count(*) FROM st_result GROUP BY 1 ORDER BY 2 DESC"); log("results per package", c.fetchall())
if CHECK:
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  r.lab, meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, r.udl, NULL, NULL, false, true, '{TAG}', now(), r.st, NULL, r.comment
FROM st_result r JOIN st_map m ON m.k = r.k JOIN geochem.analytes a ON a.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("results inserted", nins, "of", nres); assert nins == nres
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE r.source_result_id WHEN 'B' THEN 'BELOW_DL_QUALIFIED' WHEN 'A' THEN 'ABOVE_UDL' ELSE 'DETECTED' END,
  CASE WHEN r.source_result_id = 'B' THEN r.lower_detection_limit END, CASE WHEN r.source_result_id = 'B' THEN 'QUALIFIER_LDL' END,
  r.source_result_id = 'D'
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute(f"UPDATE geochem.analytical_results_{PART} SET source_result_id = NULL")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'SARIG: <x -> BELOW_DL_QUALIFIED (dl x), >x -> ABOVE_UDL, numbers DETECTED')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, 'CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/', true, %s, true, %s, %s, %s, now(), true, %s, now())
 ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "Geological Survey of South Australia, Department for Energy and Mining, Government of South Australia (SARIG)",
           "SARIG rock-sample chemistry export (sarig_rs_chem_exp, July 2025) - surface samples with laboratory assays (phase 1)",
           "Contains SARIG data (Geological Survey of South Australia, Department for Energy and Mining), Government of South Australia, licensed under CC BY 4.0.",
           "Cleared: 'Disclaimer and CCBY.txt' in the SARIG data-package bucket states CC BY 4.0 Australia with attribution; checked 2026-11-16.",
           "Surface samples only (soil, calcrete, rock, stream / lake sediment, lag, gravel, auger, channel, trench, vegetation); drill-hole samples "
           "(~54M rows) not loaded yet. Mostly exploration-company data submitted to the state, 1960s-2020s, many laboratories and methods - compare "
           "one method family (package) at a time. Portable / in-house XRF left out. Calcrete and lag are stored as soil / sediment sample types "
           "with the medium in sample_type_local.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\SA_SARIG\Disclaimer_and_CCBY.txt", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG); g.close(); os.remove(res_path)
