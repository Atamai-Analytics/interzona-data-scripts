"""USGS National Geochemical Database: SEDIMENT and SOIL releases (ngdbsed, ngdbsoil; US public domain) -> interzona_cm gold, source USA_USGS_NGDB
(the same source and partition as the rock samples loaded by load_usgs_ngdb.py; rows of this load carry created_by = TAG).

Input: D:/CriticalMineralsDB/USA/<ngdbsed|ngdbsoil>/main.csv (one row per sample) and chemistry.csv (all analyses, long format), extracted from
ngdbsed-csv.zip / ngdbsoil-csv.zip. Field meanings from the release metadata (ngdbsed.met, datadxny.csv):
  qvalue < 0 = below the lower limit of determination (|value| = the limit; qualifiers L, N or <); qualifiers G / > = above the upper limit
  (the limit with a ".1111" suffix). Stored as qualifier '<' / '>' with the limit, the USGS letter kept in result_comment.
What is loaded
  - every sample with a position; lab ids already in gold as USA_USGS_NGDB samples (through the rock load) are skipped
  - each lab id is one sample (USGS gives separate lab ids to separate size fractions); mesh size = result fraction
  - one package per USGS analytical method (USGS-NGDB-<amethod>), mapped to a gold method; ES_SQ (semi-quantitative emission spectrography,
    1960s-80s) gets the lowest priority so modern ICP / INAA values win in the wide table
  - left out: computed values (CP), sample weights (GV, unit g), organic / carbonate carbon and nitrogen (no gold analyte), zero values
Sample types: stream/river + alluvium -> SED_STREAM, lake -> SED_LAKE, wetland/bog -> SED_BOG, glacial -> TILL_SAMPLE, other sediment contexts
(marine, surface, unknown...) -> SEDIMENT_SAMPLE; soils by recorded zone (A/Ap, B, C horizon) else SOIL_SAMPLE; mine waste / tailings -> TAILINGS_GENERAL.
Usage: python load_usgs_ngdb_sedsoil.py --dataset sed|soil [--check]   (--check = stage, insert samples, ROLLBACK before the result rows)
"""
import os, sys, io, csv, re, time, collections, datetime
import psycopg2

DATASET = sys.argv[sys.argv.index("--dataset") + 1]
assert DATASET in ("sed", "soil")
CHECK = "--check" in sys.argv
TAG = f"migration_usgs_ngdb_{DATASET}_20261113"
SRC = "USA_USGS_NGDB"
PART = "usa_usgs_ngdb"
XID = "USGS_NGDB_LAB_ID"
R = f"D:/CriticalMineralsDB/USA/ngdb{DATASET}/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# USGS amethod -> (gold method code, basis, priority). Lower priority number wins in the wide table. Basis follows the rule agreed for the rock
# load (setup_usgs_priorities.py, Option A): partial only when the USGS code ends in _P. For total-basis elements the wide table ranks by technique
# (geochem.technique_rank), set for these packages by setup_usgs_priorities.py - run it after this load.
M = {
    "MS_HF": ("4A-ICPMS", "T", 1), "AES_HF": ("4A-ICPOES", "T", 2), "AES_HF_REE": ("4A-ICPOES", "T", 2), "AES_IE": ("4A-ICPOES", "T", 2),
    "MS_AR_P": ("AR-ICPMS", "P", 1), "AES_AR_P": ("AR-ICPOES", "P", 2), "AES_AZ_P": ("AZ-ICPOES", "P", 3), "AES_Acid_P": ("ACIDP-ICPOES", "P", 3),
    "AES_Fuse": ("LIBOR-ICPOES", "T", 2), "AES_ST": ("NAPEROX-ICPOES", "T", 2), "MS_ST": ("NAPEROX-ICPMS", "T", 1), "MS_ST_REE": ("NAPEROX-ICPMS", "T", 1),
    "NA_SC": ("NONE-INAA", "T", 2), "NA_LC": ("NONE-INAA", "T", 2), "DN": ("NONE-DNC", "T", 1),
    "WDX_Fuse": ("LIBOR-XRF", "T", 2), "WDX_Raw": ("NONE-XRF", "T", 3), "EDX": ("NONE-EDXRF", "T", 4),
    "ES_SQ": ("NONE-DCARC", "T", 7), "ES_Q": ("NONE-ESQ", "T", 4),
    "AA_F_HNO3_P": ("HNO3-AAS", "P", 4), "AA_F_HBr": ("HBR-AAS", "T", 3), "AA_GF_HBr": ("HBR-GFAAS", "T", 2), "AA_F_HF": ("4A-AAS", "T", 3),
    "AA_GF_HF": ("4A-GFAAS", "T", 2), "AA_F_AZ_H2O2_P": ("AZ-AAS", "P", 4), "AA_F_AZ_Fuse_P": ("AZ-AAS", "P", 4), "AA_F_AZ_HCl_P": ("HCL-AAS", "P", 4),
    "AA_F_HCl_P": ("HCL-AAS", "P", 4), "AA_F_HCl_OE_P": ("NH4I-AAS", "P", 4), "AA_F_Fuse_P": ("NH4I-AAS", "P", 4), "AA_F_Fuse": ("LIBOR-AAS", "T", 3),
    "AA_FE": ("MX-FES", "T", 3), "AA_TR": ("NONE-TRAAS", "T", 3), "AA_TR_W": ("NONE-TRAAS", "T", 3), "AA_CV": ("MX-CVAAS", "T", 2),
    "AA_CV_WO": ("MX-CVAAS", "T", 2), "AA_HG_HF": ("MX-HGAAS", "T", 2), "AA_HG_Acid": ("MX-HGAAS", "T", 2), "AA_HG_ST": ("SINTER-HGAAS", "T", 3),
    "AA_GF_ST": ("SINTER-GFAAS", "T", 3), "TC_Jrm": ("NONE-JEROME", "T", 4),
    "FA_MS": ("FA-ICPMS", "T", 1), "FA_DC": ("FA-DCP", "T", 1), "FA_AA": ("FA-AAS", "T", 1), "FA_ES": ("FA-ES", "T", 2),
    "FL_HF": ("4A-FLUOR", "T", 3), "FL_HNO3": ("HNO3-FLUOR", "T", 4), "FL_Acid_P": ("HNO3-FLUOR", "P", 4),
    "CM_Fuse": ("FUS-COLORIMETRY", "T", 5), "CM_Fuse_P": ("FUSP-COLORIMETRY", "P", 5), "CM_Acid_P": ("MX-COLORIMETRY", "P", 5),
    "CM_Acid": ("MX-COLORIMETRY", "T", 5), "CM_HSF": ("MX-COLORIMETRY", "T", 4), "CM_HF": ("MX-COLORIMETRY", "T", 5), "CM_SDDC": ("MX-COLORIMETRY", "T", 4),
    "CM_HNO3_P": ("HNO3-COLORIMETRY", "P", 5), "CM_PC_P": ("HNO3-COLORIMETRY", "P", 6), "CM_ST_P": ("SINTER-COLORIMETRY", "P", 5),
    "CM_ST": ("SINTER-COLORIMETRY", "T", 5), "ISE_Fuse": ("FUS-ISE", "T", 3), "ISE_HF": ("ISE-F", "T", 4), "IC_ST": ("KOH-IC", "T", 4),
    "CB_IRC": ("NONE-LECO", "T", 1), "CB_TC": ("NONE-INDFUR", "T", 2), "CB_TT": ("NONE-INDFUR", "T", 3), "CB_CHN": ("NONE-INDFUR", "T", 3),
    "TT_HCl": ("MX-TITRATION", "T", 3), "TT_Fuse": ("MX-TITRATION", "T", 4), "VOL": ("MX-TITRATION", "T", 4), "GV_WO": ("NONE-GRAV", "T", 5),
}
SKIP_M = {"CP", "GV"}
# New gold methods: code -> (name, digest code, digest name, instrument code, instrument name)
NEW_METHODS = {
    "AZ-ICPOES": ("HCl-H2O2 partial digestion, Aliquat 336-MIBK extraction / ICP-OES", "HCl-H2O2", "HCl-H2O2 partial digestion with organic extraction", "ICP-OES", "Inductively Coupled Plasma Optical Emission Spectrometry"),
    "AZ-AAS": ("Partial digestion, Aliquat 336-MIBK extraction / flame AAS", "HCl-H2O2", "Partial digestion with organic extraction", "AAS", "Atomic Absorption Spectrometry"),
    "ACIDP-ICPOES": ("Unstated partial acid digestion / ICP-OES", "AcidPartial", "Partial acid digestion (unstated)", "ICP-OES", "Inductively Coupled Plasma Optical Emission Spectrometry"),
    "4A-AAS": ("Multi-acid (HF) digestion / flame AAS", "4-Acid", "Four-Acid Digestion", "AAS", "Atomic Absorption Spectrometry"),
    "4A-GFAAS": ("Multi-acid (HF) digestion / graphite furnace AAS", "4-Acid", "Four-Acid Digestion", "GF-AAS", "Graphite Furnace Atomic Absorption Spectrometry"),
    "4A-FLUOR": ("Multi-acid (HF) digestion / fluorometry", "4-Acid", "Four-Acid Digestion", "FLUOR", "Fluorometry"),
    "HBR-GFAAS": ("HBr-Br2 digestion, Aliquat 336-MIBK extraction / graphite furnace AAS", "HBr", "Hydrobromic acid-bromine digestion", "GF-AAS", "Graphite Furnace Atomic Absorption Spectrometry"),
    "HCL-AAS": ("HCl partial digestion / flame AAS", "HCl", "Hydrochloric acid partial digestion", "AAS", "Atomic Absorption Spectrometry"),
    "NH4I-AAS": ("NH4I or K2S2O7 fusion, partial digestion, organic extraction / flame AAS", "FusionPartial", "Partial fusion digestion", "AAS", "Atomic Absorption Spectrometry"),
    "MX-FES": ("HF-HClO4 dissolution or LiBO2 fusion / flame emission (photometry)", "MixedAcid", "Mixed Acid Digest", "FES", "Flame Emission Spectrometry"),
    "NONE-TRAAS": ("Thermal release / AAS (mercury)", "None", "No digestion (thermal release)", "TR-AAS", "Thermal Release Atomic Absorption Spectrometry"),
    "SINTER-HGAAS": ("Na2O2 sinter / hydride generation AAS", "Sinter", "Sodium peroxide sinter", "HG-AAS", "Hydride Generation Atomic Absorption Spectrometry"),
    "SINTER-GFAAS": ("Na2O2 sinter / graphite furnace AAS", "Sinter", "Sodium peroxide sinter", "GF-AAS", "Graphite Furnace Atomic Absorption Spectrometry"),
    "SINTER-COLORIMETRY": ("Carbonate or Na2CO3-ZnO sinter / colorimetry", "Sinter", "Carbonate sinter", "COLOR", "Colorimetry"),
    "FUS-COLORIMETRY": ("Fusion digestion / colorimetric spectrophotometry", "Fusion", "Fusion digestion", "COLOR", "Colorimetry"),
    "FUSP-COLORIMETRY": ("Partial fusion digestion (K2S2O7 / NaHSO4) / colorimetry", "FusionPartial", "Partial fusion digestion", "COLOR", "Colorimetry"),
    "FUS-ISE": ("Fusion digestion / ion-selective electrode", "Fusion", "Fusion digestion", "ISE", "Ion-Selective Electrode"),
    "HNO3-COLORIMETRY": ("HNO3 partial digestion / colorimetry or paper chromatography", "HNO3", "Nitric Acid", "COLOR", "Colorimetry"),
    "HNO3-FLUOR": ("HNO3 digestion / fluorometry", "HNO3", "Nitric Acid", "FLUOR", "Fluorometry"),
    "FA-ES": ("PbO fire assay / DC-arc quantitative emission spectrography", "FireAssay", "Fire Assay", "DC-ARC", "DC Arc Atomic Emission Spectrometry"),
    "NONE-EDXRF": ("No digestion / energy-dispersive XRF", "None", "No Digestion", "ED-XRF", "Energy-Dispersive X-Ray Fluorescence"),
    "NONE-ESQ": ("No digestion / quantitative emission spectrography", "None", "No Digestion", "DC-ARC", "DC Arc Atomic Emission Spectrometry"),
}
SPECIES = {"C_tot": "C"}
SKIP_SPECIES = {"C_org", "C_crb", "N", "SplWtAu", "SplWtFA"}
UNIT = {"ppm": "ppm", "pct": "%"}


def stype(r):
    if DATASET == "sed":
        src = r["sample_source"]
        if src in ("stream/river", "alluvium"): return "SED_STREAM"
        if src == "lake": return "SED_LAKE"
        if src.startswith("wetland"): return "SED_BOG"
        if src.startswith("glacial"): return "TILL_SAMPLE"
        return "SEDIMENT_SAMPLE"
    src, z = r["sample_source"], r["sample_zone"]
    if src in ("mine dump/waste rock", "mine/mill tailings"): return "TAILINGS_GENERAL"
    if z in ("A horizon", "Ap horizon"): return "SOIL_A"
    if z == "B horizon": return "SOIL_B"
    if z == "C horizon": return "SOIL_C"
    return "SOIL_SAMPLE"


def date(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            d = datetime.datetime.strptime(s.strip().split(" ")[0], fmt).date()
            return d.isoformat() if 1900 < d.year <= 2026 else None
        except ValueError:
            pass
    return None


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
g.autocommit = False
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '512MB'")
c.execute("SELECT DISTINCT sample_number FROM geochem.samples WHERE source_system = %s AND sample_number IS NOT NULL", (SRC,))
in_gold = {r[0] for r in c.fetchall()}
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'SAMPLE' AND source_system = %s", (XID,))
in_gold |= {r[0] for r in c.fetchall()}
log("lab ids already in gold for", SRC, len(in_gold))

# ---------------------------------------------------------------- samples
stats = collections.Counter()
samples = {}
with open(R + "main.csv", encoding="utf-8-sig", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        lab = r["lab_id"].strip()
        if not lab: stats["no lab id"] += 1; continue
        if lab in in_gold: stats["sample already in gold"] += 1; continue
        if lab in samples: stats["duplicate lab id in file"] += 1; continue
        try: lat, lon = float(r["lat_wgs84"]), float(r["long_wgs84"])
        except ValueError: stats["no position"] += 1; continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0): stats["bad position"] += 1; continue
        st = stype(r)
        frac = r["mesh_size"].strip() or None
        local = f"USGS NGDB {'sediment' if DATASET == 'sed' else 'soil'}: " + " / ".join(x for x in [r["sample_source"], r["primary_class"], r["specific_name"],
                                                                                                    r.get("sample_zone", "")] if x)
        note = "; ".join(x for x in [
            f"USGS NGDB lab id {lab}", f"job {r['job_id']}" if r["job_id"] else "", f"project {r['project_name']}" if r["project_name"] else "",
            f"submitter {r['submitter']}" if r["submitter"] else "", f"{r['state']}, {r['country']}".strip(", "),
            f"coordinate precision {r['coord_prec_est']}" if r["coord_prec_est"] else "", f"depth {r['depth']}" if r["depth"] else "",
            f"mesh {frac}" if frac else "", f"preparation {r['prep']}" if r["prep"] else "", r["locate_desc"][:200]] if x)
        samples[lab] = [lab, st, local[:250], lat, lon, r["field_id"] or None, lab, note, "SURFACE", date(r["date_collect"]), frac]
        stats["samples " + st] += 1
log("samples staged", len(samples), dict(stats))

# ---------------------------------------------------------------- results
res_path = os.path.join(HERE, f"_ngdb_{DATASET}_results.csv")
used_methods = collections.Counter()
nres = 0
with open(R + "chemistry.csv", encoding="utf-8-sig", errors="replace", newline="") as f, open(res_path, "w", newline="", encoding="utf-8") as out:
    w = csv.writer(out)
    for r in csv.DictReader(f):
        lab = r["lab_id"].strip()
        if lab not in samples: stats["result of a skipped sample"] += 1; continue
        am = r["amethod"].strip()
        if am in SKIP_M: stats["method left out " + am] += 1; continue
        assert am in M, ("unmapped method", am)
        sp = r["species"].strip()
        if sp in SKIP_SPECIES: stats["species left out " + sp] += 1; continue
        u = UNIT.get(r["unit"].strip())
        if u is None: stats["unit left out " + r["unit"]] += 1; continue
        txt, q = r["qvalue"].strip(), r["qualifier"].strip()
        try: v = float(txt)
        except ValueError: stats["bad value"] += 1; continue
        if q in ("G", ">"):
            t = txt[:-4] if txt.endswith("1111") else txt
            try: v = float(t.rstrip(".")) if t.rstrip(".") else v
            except ValueError: pass
            qual, val, ldl, udl = ">", v, None, v; stats["above upper limit"] += 1
        elif v < 0 or q in ("L", "N", "<"):
            if v == 0: stats["zero value"] += 1; continue
            qual, val, ldl, udl = "<", abs(v), abs(v), None; stats["below detection"] += 1
        else:
            if v == 0: stats["zero value"] += 1; continue
            qual, val, ldl, udl = None, v, None, None
        used_methods[am] += 1
        w.writerow([lab, f"USGS-NGDB-{am}", SPECIES.get(sp, sp), u, qual or N, val, N if ldl is None else ldl, N if udl is None else udl,
                    f"USGS {am}" + (f"; USGS qualifier {q}" if q else ""), samples[lab][10] or N])
        nres += 1
        if nres % 2_000_000 == 0: log("results staged", nres)
log("results staged", nres, {k: v for k, v in stats.items() if not k.startswith("samples ")})

# ---------------------------------------------------------------- gold load
METHOD_DEF = {}
for ds in ("ngdbsed", "ngdbsoil"):
    t = open(f"D:/CriticalMineralsDB/USA/{ds}/{ds}.met", encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"Enumerated_Domain_Value:\s*(\S+)\s+Enumerated_Domain_Value_Definition:\s*(.*?)\s+Enumerated_Domain_Value_Definition_Source", t, re.S):
        METHOD_DEF.setdefault(m.group(1), re.sub(r"\s+", " ", m.group(2)))

for code, (name, dcode, dname, icode, iname) in NEW_METHODS.items():
    c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, instrument_code, instrument_name,
                   notes, is_active, created_by, created_date)
                 SELECT %s, %s, %s, %s, %s, %s, %s, true, %s, now()
                 WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = %s)""",
              (code, name, dcode, dname, icode, iname, "Added for the USGS NGDB sediment/soil load (USGS method families)", TAG, code))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for am in used_methods:
    mcode, basis, prio = M[am]
    pcode = f"USGS-NGDB-{am}"
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (pcode, f"USGS NGDB {am}", mid[mcode], METHOD_DEF.get(am, "USGS NGDB analytical method " + am)[:1000], TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'USGS NGDB method mapping' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""",
              (basis, prio, pcode))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "USGS NGDB method mapping " + TAG, pcode))


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date, frac text",
     samples.values())
c.execute("""CREATE TEMP TABLE st_result (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric, comment text,
  fraction text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); assert c.fetchone()[0] == nres
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
log("dictionary checks passed; staged", len(samples), "samples,", nres, "results")

# only samples that have at least one result
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
    c.execute("SELECT pkg, count(*) FROM st_result GROUP BY 1 ORDER BY 2 DESC LIMIT 25"); log("values per package", c.fetchall())
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back before the result rows"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  'USGS', meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, r.udl, NULL, NULL, false, true, '{TAG}', now(),
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
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UDL' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r WHERE r.created_by = '{TAG}'""")
log("classified", c.rowcount)
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 VALUES (%s, %s, now(), now(), %s, 'rule-based classification at load (USGS NGDB negative / L N < = below detection, G > = above range)')
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC, "rule_" + TAG, nins))
c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}'
              AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{SRC}')""")
nores = c.fetchone()[0]
log("samples without results (must be 0)", nores)
assert nores == 0
g.commit(); log("COMMITTED", TAG)
g.close()
os.remove(res_path)
