"""USGS Alaska Geochemical Database v3.0 (AGDB3; Granitto et al. 2019, USGS Data Series 1117, doi 10.5066/P98NHRAD; Use_Constraints: None =
US public domain) -> interzona_cm gold, new source ALASKA_AGDB3 (own partition; rollback = delete by created_by = TAG).

Only samples NOT already in gold are loaded (user decision 2026-11-16): an AGDB3 sample is skipped when its LAB_ID or PREV_LAB_ID_1/2 is a USGS
NGDB lab id already in USA_USGS_NGDB (sample_number or external id USGS_NGDB_LAB_ID), or its NURE_REC_NO is already in USA_NURE_HSSR. What
remains (~99,000) is mainly Alaska DGGS, US Bureau of Mines, BLM and USGS samples missing from the NGDB release, plus 486 NURE records.
Input: D:/CriticalMineralsDB/USA/AGDB3/_x/AGDB3_DS_data_ASCII/ (Geol_DeDuped = one row per sample after USGS's de-duplication; Chem_A_Cs,
Chem_Cu_Ru, Chem_S_Zr = every determination, long format). Coordinates WGS84 (transformed by USGS, 2018).
Values (DataDictionary): QUALIFIED_VALUE < 0 = below the limit |v| (qualifiers <, N, L); qualifiers > / G = above the upper limit (value ends in
'111', handled as in load_usgs_ngdb_sedsoil.py). Stored as qualifier '<' / '>' with the limit; the USGS letter is in result_comment.
Methods: the NGDB method map (load_usgs_ngdb_sedsoil.M, NEW_METHODS) plus AGDB3-only methods below; one package per method 'AGDB3-<method>'.
Left out: mineral separates (7,515) and oxalic-acid leachates (3,619) and miscellaneous samples; gravimetric water / density / LOI, computed values,
carbon forms, units g / gcc / SI; species with no gold analyte (CCO3, Corg, Ash, H2O, oil ...); zero values.
Usage: python load_alaska_agdb3.py [--check]
"""
import os, sys, io, csv, re, time, collections, datetime
import pandas as pd, psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_alaska_agdb3_20261116"
SRC, PART, XID = "ALASKA_AGDB3", "alaska_agdb3", "AGDB3_ID"
D = "D:/CriticalMineralsDB/USA/AGDB3/_x/AGDB3_DS_data_ASCII/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# NGDB maps (same lab-method vocabulary)
_src = open(os.path.join(HERE, "load_usgs_ngdb_sedsoil.py"), encoding="utf-8").read()
_ns = {}
exec(_src[_src.index("M = {"):_src.index("SKIP_M")], _ns)
exec(_src[_src.index("NEW_METHODS = {"):_src.index("SPECIES = {")], _ns)
M, NEW_METHODS = dict(_ns["M"]), dict(_ns["NEW_METHODS"])
M.update({
    "MS_Fuse": ("LIBOR-ICPMS", "T", 1), "MS_Fuse_REE": ("LIBOR-ICPMS", "T", 1), "AA_F_AR_P": ("AR-AAS", "P", 4), "EDX_Slab": ("NONE-EDXRF", "T", 4),
    "FA_AES": ("FA-ICPOES", "T", 1), "FA_AES_AG": ("FA-ICPOES", "T", 1), "FA_AES_AR": ("FA-ICPOES", "T", 1), "FA_AES_AR_AS": ("FA-ICPOES", "T", 1),
    "WDX_Slab": ("NONE-XRF", "T", 3), "WDX_PP": ("NONE-XRF", "T", 3), "WDX_PP_AG": ("NONE-XRF", "T", 3), "AES_AZ_HF": ("4A-ICPOES", "T", 2),
    "AES_HF_AG": ("4A-ICPOES", "T", 2), "FA_AFS": ("FA-AFS", "T", 1), "AA_CV_AR": ("AR-CVAAS", "T", 2), "AA_F_AR": ("AR-AAS", "T", 3),
    "AFS_CV": ("AR-CVAFS", "T", 2), "MS_AR": ("AR-ICPMS", "P", 1), "TT_HF": ("MX-TITRATION", "T", 3), "TT_AR_P": ("MX-TITRATION", "P", 5),
    "FA_GV": ("FA-GRAV", "T", 2), "FA_DCP": ("FA-DCP", "T", 1), "DCP_Fuse": ("LIBOR-DCP", "T", 2), "DCP_HF": ("4A-DCP", "T", 2),
    "DCP_AR_P": ("AR-DCP", "P", 3), "DCP_ST": ("NAPEROX-DCP", "T", 2), "AA_HG_AR": ("MX-HGAAS", "T", 2), "CM_EL": ("MX-COLORIMETRY", "T", 5),
    "CM_HClO4_P": ("MX-COLORIMETRY", "P", 5), "AA_GF_AR_P": ("AR-GFAAS", "P", 3), "AA_F_Acid_P": ("ACIDP-AAS", "P", 4),
    "AA_F_KClO3_P": ("KCLO3-AAS", "P", 4), "AA_F_ST": ("SINTER-AAS", "T", 3), "GRC": ("NONE-GAMMA", "T", 4), "NA_REE": ("NONE-INAA", "T", 2),
    "NA_PG": ("NONE-INAA", "T", 2), "FA_NA": ("NONE-INAA", "T", 1), "GV_Acid": ("NONE-GRAV", "T", 4), "GV_CR": ("NONE-GRAV", "T", 4),
    "GV_Fuse": ("NONE-GRAV", "T", 4), "GV_HF": ("NONE-GRAV", "T", 4), "FA_MS_AG": ("FA-ICPMS", "T", 1),
})
NEW_METHODS.update({
    "LIBOR-ICPMS": ("LiBO2/Li2B4O7 fusion / ICP-MS", "LiBorate", "Lithium Borate Fusion", "ICP-MS", "Inductively Coupled Plasma Mass Spectrometry"),
    "AR-AAS": ("Aqua regia digestion / flame AAS", "AR", "Aqua Regia", "AAS", "Atomic Absorption Spectrometry"),
    "FA-AFS": ("PbO fire assay / atomic fluorescence spectrometry", "FireAssay", "Fire Assay", "AFS", "Atomic Fluorescence Spectrometry"),
    "AR-CVAAS": ("Aqua regia digestion / cold-vapour AAS (mercury)", "AR", "Aqua Regia", "CV-AAS", "Cold Vapour Atomic Absorption Spectrometry"),
    "AR-CVAFS": ("HNO3-HCl digestion / cold-vapour atomic fluorescence (mercury)", "AR", "Aqua Regia", "CV-AFS", "Cold Vapour Atomic Fluorescence Spectrometry"),
    "LIBOR-DCP": ("Fusion digestion / DC plasma emission", "LiBorate", "Fusion digestion", "DCP", "Direct Current Plasma Emission Spectrometry"),
    "4A-DCP": ("Multi-acid (HF) digestion / DC plasma emission", "4-Acid", "Four-Acid Digestion", "DCP", "Direct Current Plasma Emission Spectrometry"),
    "AR-DCP": ("Aqua regia partial digestion / DC plasma emission", "AR", "Aqua Regia", "DCP", "Direct Current Plasma Emission Spectrometry"),
    "NAPEROX-DCP": ("Na2O2 sinter / DC plasma emission", "Sinter", "Sodium peroxide sinter", "DCP", "Direct Current Plasma Emission Spectrometry"),
    "ACIDP-AAS": ("Unstated partial acid digestion / flame AAS", "AcidPartial", "Partial acid digestion (unstated)", "AAS", "Atomic Absorption Spectrometry"),
    "KCLO3-AAS": ("KClO3-HCl partial digestion / flame AAS", "KClO3", "Potassium chlorate partial digestion", "AAS", "Atomic Absorption Spectrometry"),
    "SINTER-AAS": ("Na2O2 sinter / flame AAS", "Sinter", "Sodium peroxide sinter", "AAS", "Atomic Absorption Spectrometry"),
    "NONE-GAMMA": ("No digestion / gamma-ray counting (uranium)", "None", "No Digestion", "GAMMA", "Gamma-ray Spectrometry"),
})
SKIP_M = {"CP", "GV", "GV_Flux", "TT_Flux", "VOL_HCl", "CB_HCl"}
SPECIES = {"C_tot": "C", "TI": "Ti", "s": "S"}
UNIT = {"ppm": "ppm", "pct": "%"}


def stype(cls, src, zone):
    cls, src, zone = (cls or "").lower(), (src or "").lower(), (zone or "").lower()
    if cls == "rock":
        if "drill" in src: return "ROCK_CORE"
        if src == "float": return "ROCK_FLOAT"
        if src == "outcrop": return "ROCK_OUTCROP"
        if "dump" in src or "tailing" in src: return "TAILINGS_GENERAL"
        return "ROCK_SAMPLE"
    if cls == "sediment":
        if src.startswith("stream"): return "SED_STREAM"
        if "lake" in src or "pond" in src: return "SED_LAKE"
        if "bog" in src or "wetland" in src: return "SED_BOG"
        if "glacial" in src: return "TILL_SAMPLE"
        return "SEDIMENT_SAMPLE"
    if cls == "concentrate": return "SED_HMC"
    if cls == "soil":
        if zone.startswith("a"): return "SOIL_A"
        if zone.startswith("b"): return "SOIL_B"
        if zone.startswith("c"): return "SOIL_C"
        return "SOIL_SAMPLE"
    return None


def date(s):
    try:
        d = datetime.datetime.strptime((s or "").strip().split(" ")[0], "%m/%d/%Y").date()
        return d.isoformat() if 1900 < d.year <= 2026 else None
    except ValueError:
        return None


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT sample_number FROM geochem.samples WHERE source_system = 'USA_USGS_NGDB' AND sample_number IS NOT NULL"); have = {r[0] for r in c.fetchall()}
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'SAMPLE' AND source_system = 'USGS_NGDB_LAB_ID'"); have |= {r[0] for r in c.fetchall()}
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'SAMPLE' AND source_system = 'NURE_HSSR_REC_NO'"); nure = {r[0] for r in c.fetchall()}
c.execute("SELECT analyte_code FROM geochem.analytes"); known = {r[0] for r in c.fetchall()}

stats = collections.Counter()
samples = {}
geo = pd.read_csv(D + "Geol_DeDuped.txt", dtype=str, encoding="latin-1", keep_default_na=False)
for r in geo.itertuples(index=False):
    r = r._asdict()
    nr = re.sub(r"\.0$", "", r["NURE_REC_NO"])
    if r["LAB_ID"] in have or r["PREV_LAB_ID_1"] in have or r["PREV_LAB_ID_2"] in have: stats["already in NGDB"] += 1; continue
    if nr and nr in nure: stats["already in NURE"] += 1; continue
    st = stype(r["PRIMARY_CLASS"], r["SAMPLE_SOURCE"], r["SAMPLE_ZONE"])
    if st is None: stats["left out class " + (r["PRIMARY_CLASS"] or "none")] += 1; continue
    try: lat, lon = float(r["LATITUDE"]), float(r["LONGITUDE"])
    except ValueError: stats["no position"] += 1; continue
    k = r["AGDB_ID"]
    ids = "; ".join(x for x in [f"lab id {r['LAB_ID']}" if r["LAB_ID"] else "", f"DGGS id {r['DGGS_ID']}" if r["DGGS_ID"] else "",
                                f"NURE record {nr}" if nr else ""] if x)
    note = "; ".join(x for x in [
        f"USGS Alaska Geochemical Database (AGDB3) id {k}", f"agency {r['AGENCY']}", ids, f"publication {r['PUBL_ID']}" if r["PUBL_ID"] else "",
        f"project {r['PROJECT_NAME']}" if r["PROJECT_NAME"] else "", f"submitter {r['SUBMITTER']}" if r["SUBMITTER"] else "",
        f"quadrangle {r['QUAD']}" if r["QUAD"] else "", f"mesh {r['MESH_PORE_SIZE']}" if r["MESH_PORE_SIZE"] else "",
        f"depth {r['DEPTH']}" if r["DEPTH"] else "", f"mineralization: {r['MINERALIZATION'][:150]}" if r["MINERALIZATION"] else "",
        r["LOCATE_DESC"][:200]] if x)
    local = "AGDB3 " + " / ".join(x for x in [r["PRIMARY_CLASS"], r["SAMPLE_SOURCE"], r["SECONDARY_CLASS"], r["SPECIFIC_NAME"]] if x)
    samples[k] = [k, st, local[:100], lat, lon, r["FIELD_ID"] or None, r["LAB_ID"] or r["DGGS_ID"] or k, note[:1000], "SURFACE",
                  date(r["DATE_COLLECT"]), r["MESH_PORE_SIZE"] or None]
    stats["samples " + st] += 1
log("samples staged", len(samples), dict(stats))

res_path = os.path.join(HERE, "_agdb3_results.csv")
used = collections.Counter(); nres = 0
with open(res_path, "w", newline="", encoding="utf-8") as out:
    w = csv.writer(out)
    for f in ("Chem_A_Cs", "Chem_Cu_Ru", "Chem_S_Zr"):
        for ch in pd.read_csv(D + f + ".txt", dtype=str, encoding="latin-1", keep_default_na=False, chunksize=1_000_000,
                              usecols=["AGDB_ID", "ANALYTIC_METHOD", "QUALIFIED_VALUE", "QUALIFIER", "SPECIES", "UNITS", "BESTVALUE_RANK"]):
            ch = ch[ch.AGDB_ID.isin(samples)]
            for r in ch.itertuples(index=False):
                am = r.ANALYTIC_METHOD
                if am in SKIP_M: stats["method left out " + am] += 1; continue
                assert am in M, ("unmapped method", am)
                u = UNIT.get(r.UNITS)
                if u is None: stats["unit left out " + r.UNITS] += 1; continue
                sp = SPECIES.get(r.SPECIES, r.SPECIES)
                if sp not in known: stats["species left out " + sp] += 1; continue
                txt, q = r.QUALIFIED_VALUE.strip(), r.QUALIFIER.strip()
                try: v = float(txt)
                except ValueError: stats["bad value"] += 1; continue
                if v == 0: stats["zero value"] += 1; continue
                if q in ("G", ">"):
                    t = txt
                    if re.search(r"\.\d*\d1$", txt):
                        t = re.sub(r"1+$", "", txt)
                        if float(t.rstrip(".") or 0) == 0: t += "1"
                    try: v = float(t.rstrip(".")) if t.rstrip(".") else v
                    except ValueError: pass
                    qual, val, ldl, udl = ">", v, None, v; stats["above upper limit"] += 1
                elif v < 0 or q in ("L", "N", "<"):
                    qual, val, ldl, udl = "<", abs(v), abs(v), None; stats["below detection"] += 1
                else:
                    qual, val, ldl, udl = None, v, None, None
                used[am] += 1
                w.writerow([r.AGDB_ID, f"AGDB3-{am}", sp, u, qual or N, val, N if ldl is None else ldl, N if udl is None else udl,
                            f"USGS AGDB3 {am}; best-value rank {r.BESTVALUE_RANK}" + (f"; USGS qualifier {q}" if q else ""), samples[r.AGDB_ID][10] or N])
                nres += 1
        log("results staged after", f, nres)
log("results staged", nres, {k: v for k, v in stats.items() if not k.startswith("samples ")})

if not CHECK:
    g.commit(); g.autocommit = True
    for t in ("analytical_results", "result_classifications"):
        g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART} PARTITION OF geochem.{t} FOR VALUES IN ('{SRC}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '512MB'")
for code, (name, dcode, dname, icode, iname) in NEW_METHODS.items():
    c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, instrument_code, instrument_name,
                   notes, is_active, created_by, created_date)
                 SELECT %s, %s, %s, %s, %s, %s, %s, true, %s, now() WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = %s)""",
              (code, name, dcode, dname, icode, iname, "Added for USGS NGDB / Alaska AGDB3 loads (USGS method families)", TAG, code))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
desc = {r["ANALYTIC_METHOD"]: r["ANALYTIC_METHOD_DESC"] for r in csv.DictReader(open(D + "AnalyticMethod.txt", encoding="latin-1"))}
for am in used:
    mcode, basis, prio = M[am]; pcode = f"AGDB3-{am}"
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pcode, f"USGS AGDB3 {am}", mid[mcode], desc.get(am, "USGS AGDB3 analytical method " + am)[:1000], TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'USGS AGDB3 method mapping' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""",
              (basis, prio, pcode))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "USGS AGDB3 method mapping " + TAG, pcode))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data: wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0); c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date, frac text",
     samples.values())
c.execute("CREATE TEMP TABLE st_result (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric, comment text, fraction text) ON COMMIT DROP")
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
log("samples inserted", c.rowcount, "| without any result (not loaded)", len(samples) - c.rowcount)
c.execute(f"INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date) SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map")
c.execute(f"""SELECT t.sample_type_code, count(*) FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id) WHERE s.created_by = '{TAG}' GROUP BY 1 ORDER BY 2 DESC""")
log("sample types", c.fetchall())
if CHECK:
    c.execute("SELECT pkg, count(*) FROM st_result GROUP BY 1 ORDER BY 2 DESC LIMIT 20"); log("values per package", c.fetchall())
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  'USGS / DGGS / USBM / BLM laboratories or contractors', meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, r.udl, NULL, NULL, false, true,
  '{TAG}', now(), NULL, r.fraction, r.comment
FROM st_result r JOIN st_map m ON m.k = r.k JOIN geochem.analytes a ON a.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("results inserted", nins, "of", nres); assert nins == nres
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UDL' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'rule-based classification at load (USGS negative / L N < = below detection, G > = above range)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
  licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
 VALUES (%s, %s, %s, %s, NULL, false, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
          (SRC, "U.S. Geological Survey (with Alaska Division of Geological & Geophysical Surveys, U.S. Bureau of Mines, U.S. Bureau of Land Management)",
           "Alaska Geochemical Database Version 3.0 (AGDB3), USGS Data Series 1117 / doi 10.5066/P98NHRAD (2019) - samples not already in the NGDB / NURE loads",
           "US public domain (USGS data release; Use_Constraints: None)",
           "Granitto, M., Shew, N.B., Karl, S.M., Wang, B., Labay, K.A., Werdon, M.B., Seitz, S.S., and Hoppe, J.E., 2019, Alaska Geochemical Database Version 3.0 (AGDB3): U.S. Geological Survey data release, https://doi.org/10.5066/P98NHRAD",
           "Cleared: ScienceBase metadata Access_Constraints None, Use_Constraints None (USGS data release); checked 2026-11-16.",
           "Only AGDB3 samples not already loaded through USA_USGS_NGDB or USA_NURE_HSSR (about 99,000: Alaska DGGS, US Bureau of Mines, BLM and USGS samples "
           "missing from the NGDB release). Many methods and decades (1938-2017) - compare one method / one survey at a time. Mineral separates and "
           "oxalic-acid leachates left out.",
           r"D:\CriticalMineralsDB\Documents\Licence_Evidence\USGS_AGDB3\ (AGDB3_MD.txt, AGDB3_DS_ReadMe.txt)", TAG))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG); g.close(); os.remove(res_path)
