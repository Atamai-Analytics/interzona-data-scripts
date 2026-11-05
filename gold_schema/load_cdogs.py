"""Canadian Database of Geochemical Surveys (CDoGS; Natural Resources Canada / Geological Survey of Canada; Open Government Licence - Canada)
-> interzona_cm gold, source CANADA_NRCAN_CDOGS.

Input: cdogs_values.csv (cdogs_flatten.py from the per-quantity qtyNNNNN.xlsx files), the catalogue tables exported from db_cdogs_metadata.accdb
(bulk/metadata/csv), bulk/Samples_DERIVED.csv and cdogs_overlap.csv (cdogs_overlap.py). All under D:/CriticalMineralsDB/Canada/NRCan_CDoGS.
What is loaded
  - federal surveys only (cdogs_types.FEDERAL_ORGS); provincial-agency, company and US surveys are left out
  - routine field samples only: lab duplicates, blanks, internal / external control references and field duplicates are left out (no lab QAQC)
  - solid media only (cdogs_types.KEEP): water, soil gas and vegetation are left out
  - samples already in gold through another source (same medium within 50 m; cdogs_overlap.csv) are left out
  - elements, oxides and LOI; mineral-grain counts, physical measurements and electron-microprobe grain analyses ('Grain Mount' preparations)
    are left out
  - each prepared fraction of a field sample is its own sample ('<field id> (<preparation>)') so fractions are never mixed; preparation = fraction
Values: negative = below detection at |value| ('<'); '>n' = above the upper limit; 'missing', 'insuff', trace and zero values left out.
Units from the CDoGS method (%, ppm, ppb; oz/ton -> ppm). Packages: CDOGS-<technique group>-<digestion>, basis and priority in source_package_rules.
Usage: python load_cdogs.py [--check]   (--check = stage, check codes, insert samples, ROLLBACK before the result rows)
"""
import os, sys, io, csv, re, time, html, collections
import pandas as pd, psycopg2
from cdogs_types import KEEP, FEDERAL_ORGS

CHECK = "--check" in sys.argv
TAG = "migration_cdogs_20261105"
SRC = "CANADA_NRCAN_CDOGS"
PART = "canada_nrcan_cdogs"
XID = "CDOGS"
R = "D:/CriticalMineralsDB/Canada/NRCan_CDoGS/"
M = R + "bulk/metadata/csv/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


# technique (last part of CDoGS 'Technique') -> group
GROUP = {"INAA": "INAA", "FA-NA": "FA-INAA", "INA/ICP-MS": "INAA", "ICP-MS": "ICPMS", "ICP-MS/ES": "ICPMS", "ICP-ES": "ICPES", "DCP-ES": "ICPES",
         "AAS-FLAME": "AAS", "AAS-FLAME-1": "AAS", "AAS-FLAME-6": "AAS", "AAS-FLAME-8": "AAS", "ABSORP": "AAS", "HYD": "HYD", "AAS-CV": "CVAAS",
         "FLUOR": "FLUOR", "FLUOROM": "FLUOR", "NADNC": "DNC", "XRAY_FLUOR": "XRF", "pXRF": "PXRF", "Powder D-C": "DCARC", "POTENT_ISE": "ISE",
         "COLOR": "COLOR", "Dithizone": "COLOR", "Dithiol": "COLOR", "Gutzeit": "COLOR", "BrillGreen": "COLOR", "LOI": "LOI", "LOI_500": "LOI",
         "LOI_900": "LOI", "LOI/FEO": "LOI", "GRAV": "GRAV", "INFRARED": "IR", "PIXE": "PIXE", "FA-AFS": "FA", "TITRATION": "WETCHEM"}
SKIP_TECH = {"ELECTR PRB", "BINMICRO", "Grain_Sep", "PHYS"}
GNAME = {"INAA": "neutron activation (INAA)", "FA-INAA": "fire assay with INAA", "ICPMS": "ICP-MS", "ICPES": "ICP emission (ES / DCP)", "AAS": "flame AAS",
         "HYD": "hydride AAS", "CVAAS": "cold-vapour AAS (Hg)", "FLUOR": "fluorimetry (U)", "DNC": "delayed neutron counting (U)", "XRF": "XRF",
         "PXRF": "portable XRF", "DCARC": "DC-arc emission spectrography (semi-quantitative)", "ISE": "ion-selective electrode (F)",
         "COLOR": "colorimetry", "LOI": "loss on ignition", "GRAV": "gravimetry", "IR": "infrared combustion (C, S)", "PIXE": "PIXE",
         "FA": "fire assay", "WETCHEM": "titration", "UNK": "other or unstated technique"}
PRIO = {"ICPMS": 1, "FA": 1, "FA-INAA": 1, "DNC": 1, "IR": 1, "INAA": 2, "ICPES": 2, "XRF": 2, "CVAAS": 2, "LOI": 2, "AAS": 3, "HYD": 3, "FLUOR": 3,
        "GRAV": 3, "ISE": 4, "PIXE": 4, "WETCHEM": 4, "COLOR": 5, "PXRF": 6, "DCARC": 7, "UNK": 9}
NO_DIGEST_TOTAL = {"INAA", "FA-INAA", "DNC", "XRF", "PXRF", "DCARC", "PIXE", "LOI", "GRAV", "IR"}
DIGEST = {"Total": "TOT", "None": "NONE"}
GOLD_METHOD = {("INAA", None): "NONE-INAA", ("FA-INAA", None): "NONE-INAA", ("DNC", None): "NONE-DNC", ("XRF", None): "NONE-XRF",
               ("PXRF", None): "NONE-XRF", ("DCARC", None): "NONE-DCARC", ("IR", None): "NONE-LECO", ("LOI", None): "NONE-GRAV",
               ("GRAV", None): "NONE-GRAV", ("ICPMS", "AR"): "AR-ICPMS", ("ICPES", "AR"): "AR-ICPOES", ("ICPMS", "TOT"): "4A-ICPMS",
               ("ICPES", "TOT"): "4A-ICPOES", ("COLOR", "NONE"): "NONE-COLORIMETRY"}


def digest(dec):
    d = plain(dec)
    if d.startswith("Partial") and "aqua regia" in d: return "AR"
    if d.startswith("Partial") and "fusion" in d: return "FUS"
    return DIGEST.get(d, "NONE")


def package(tech, dec):
    gp = GROUP.get(tech, "UNK"); dg = digest(dec)
    if gp in ("FA", "FA-INAA"):   # CDoGS files fire assay under 'Partial - fusion'; it is a total method for Au / PGE
        basis = "T"
    else:
        basis = "P" if dg in ("AR", "FUS") else "T" if dg == "TOT" or gp in NO_DIGEST_TOTAL else "P"
    code = f"CDOGS-{gp}-{dg}"
    mcode = GOLD_METHOD.get((gp, dg)) or GOLD_METHOD.get((gp, None)) or "UNKNOWN-UNKNOWN"
    dname = {"AR": "aqua regia (partial)", "FUS": "fusion (reported as partial)", "TOT": "total digestion", "NONE": "no digestion stated"}[dg]
    return code, (f"CDoGS - {GNAME[gp]}, {dname}", mcode, basis, PRIO[gp])


ANALYTE = {"Fe2O3T": "FETO3", "Total Oxides": "Sum", "H2O(+)": "H2O", "H2O(-)": "Moisture"}
CONVERT = {"Nb2O5": ("Nb", 0.69904e4), "Ta2O5": ("Ta", 0.81897e4), "CoO": ("Co", 0.78648e4), "As2O3": ("As", 0.75738e4)}   # % oxide -> ppm
SKIP_Q = {"FeOT", "CO2T", "H2OT", "Total exLOI", "Nb2O3", "Wt", "Wt %"}
UNIT = {5: ("ppm", 1.0), 1: ("%", 1.0), 4: ("ppb", 1.0), 19: ("%", 1.0), 13: ("%", 1.0), 11: ("ppm", 34.2857)}

# ---------------------------------------------------------------- catalogue
q = pd.read_csv(M + "Analytical_Quantities_SHARED.csv")
qname = dict(zip(q.Analytical_Quantity_ID, q.Analytical_Quantity_Abbreviation_en))
keepq = set(q[q.Analytical_Quantity_Type_ID.isin([1, 2])].Analytical_Quantity_ID) | {47}
munit = dict(zip(pd.read_csv(M + "Analytical_Methods_SHARED.csv").Analytical_Method_ID, pd.read_csv(M + "Analytical_Methods_SHARED.csv").Analytical_Unit_ID))
sv = pd.read_csv(M + "Surveys.csv")
svdesc = {(int(o), int(s)): (plain(d), y) for o, s, d, y in zip(sv.Organisation_ID, sv.Survey_ID, sv.Survey_Description_Short_en, sv.Survey_Year)}
org = pd.read_csv(M + "Organisations_SHARED.csv")
orgname = dict(zip(org.Organisation_ID, org.Organisation_Short_Name_en.map(plain)))
smp = pd.read_csv(R + "bulk/Samples_DERIVED.csv", dtype=str, keep_default_na=False, usecols=["Site_Key", "Site_Identifier"])
site_id = dict(zip(smp.Site_Key, smp.Site_Identifier))
overlap = set(pd.read_csv(R + "cdogs_overlap.csv").field_key)
log("catalogue read; overlap samples to skip", len(overlap))

# ---------------------------------------------------------------- values
stats = collections.Counter()
samples = {}   # key -> row
pk = {}
res_path = os.path.join(HERE, "_cdogs_results.csv")
cols = ["qty_id", "lat", "lon", "sample_type", "prep", "decomposition", "technique", "method_id", "lab_sample_type", "value_text", "value_negdl",
        "site_key", "field_key", "lab_sample_id"]
with open(res_path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    for chunk in pd.read_csv(R + "cdogs_values.csv", dtype=str, keep_default_na=False, usecols=cols, chunksize=1_000_000):
        for r in chunk.itertuples(index=False):
            if r.lab_sample_type not in ("", "0", "1"): stats["lab control / duplicate"] += 1; continue
            if r.sample_type not in KEEP: stats["medium left out"] += 1; continue
            o = r.site_key.split(":")[0]
            if not o.isdigit() or int(o) not in FEDERAL_ORGS: stats["non-federal survey"] += 1; continue
            if r.field_key in overlap: stats["already loaded via another source"] += 1; continue
            qid = int(r.qty_id)
            if qid not in keepq: stats["quantity left out (grains, physical)"] += 1; continue
            tech = r.technique.split("|")[-1].strip()
            prep = plain(r.prep)
            if tech in SKIP_TECH or prep.startswith("Grain Mount"): stats["microprobe / grain technique"] += 1; continue
            if not r.lat or not r.lon: stats["no location"] += 1; continue
            el = qname.get(qid)
            if el in SKIP_Q: stats["quantity left out: " + el] += 1; continue
            try: mid = int(r.method_id)
            except ValueError: stats["no method"] += 1; continue
            unit = UNIT.get(munit.get(mid))
            if unit is None: stats["unit left out"] += 1; continue
            u, fac = unit
            if el in CONVERT:
                if u != "%": stats["oxide not in %"] += 1; continue
                code, f2 = CONVERT[el]; u, fac = "ppm", fac * f2
            else:
                code = ANALYTE.get(el, el)
            t = r.value_text.strip()
            if t.startswith(">"):
                try: v = float(t[1:])
                except ValueError: stats["bad value"] += 1; continue
                qual, val, ldl, udl = ">", v * fac, None, v * fac; stats["above upper limit"] += 1
            else:
                try: v = float(r.value_negdl)
                except ValueError: stats["value missing / insufficient / trace"] += 1; continue
                if v == 0: stats["zero value"] += 1; continue
                if v < 0 and code not in ("LOI", "Sum"): qual, val, ldl, udl = "<", -v * fac, -v * fac, None; stats["below detection"] += 1
                else: qual, val, ldl, udl = None, v * fac, None, None
            pcode, pinfo = package(tech, r.decomposition)
            pk[pcode] = pinfo
            key = f"{r.field_key}|{prep}"
            if key not in samples:
                st, _ = KEEP[r.sample_type]
                s_parts = r.site_key.split(":")
                svk = (int(s_parts[0]), int(s_parts[1]))
                desc, yr = svdesc.get(svk, ("", None))
                sid = site_id.get(r.site_key, "") or r.lab_sample_id
                note = "; ".join(x for x in [f"CDoGS survey {s_parts[0]}:{s_parts[1]} ({orgname.get(svk[0], '')})", desc,
                                             f"survey year {int(yr)}" if yr == yr and yr else "", f"preparation: {prep}", f"CDoGS field key {r.field_key}"] if x)
                samples[key] = [key, st, f"CDoGS: {r.sample_type}", float(r.lat), float(r.lon), sid or None,
                                f"{sid} ({prep})" if sid and prep not in ("Unknown", "") else (sid or r.field_key), note,
                                "DRILLHOLE_POINT" if st == "CORE_SAMPLE" else "SURFACE"]
            w.writerow([key, pcode, code, u, qual or N, val, ldl if ldl is not None else N, udl if udl is not None else N,
                        f"{r.technique.strip()} ({plain(r.decomposition)})", prep or N, f"CDoGS method {mid}"])
            stats["values"] += 1
        log("chunk done", stats["values"], "values", len(samples), "samples")
log("staged", dict(stats))
srows = list(samples.values())

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
c.execute("SET work_mem = '512MB'")


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); w = csv.writer(buf)
    for r in data:
        w.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text", srows)
c.execute("""CREATE TEMP TABLE st_result (k text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, udl numeric, meth_name text,
  fraction text, comment text) ON COMMIT DROP""")
with open(res_path, encoding="utf-8") as fh:
    c.copy_expert("COPY st_result FROM STDIN WITH (FORMAT csv, NULL '\\N')", fh)
c.execute("SELECT count(*) FROM st_result"); nres = c.fetchone()[0]
assert nres == stats["values"], (nres, stats["values"])
log("staged in db: samples", len(srows), "results", nres, "packages", len(pk))

c.execute("SELECT method_code, method_id FROM geochem.analytical_methods")
mid = dict(c.fetchall())
for code, (name, mcode, basis, prio) in pk.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'UNK'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "CDoGS (NRCan / GSC) analyses grouped by technique and digestion; the CDoGS technique and method id are on each result", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'P', 5, 'placeholder; see source_package_rules' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (code,))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, basis, prio, "CDoGS technique/digestion mapping " + TAG, code))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]
    assert not miss, (label, miss)
log("dictionary checks passed")

c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
             WHERE s.lat BETWEEN 40 AND 85 AND s.lon BETWEEN -145 AND -50""")
c.execute("CREATE UNIQUE INDEX ON st_map (k)")
c.execute(f"""
INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments, is_active,
  created_by, created_date, source_system)
OVERRIDING SYSTEM VALUE
SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, true,
  '{TAG}', now(), '{SRC}'
FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples", c.rowcount, "| left out (position outside Canada)", len(srows) - c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', k, '{TAG}', now() FROM st_map""")
c.execute(f"""SELECT t.sample_type_code, count(*) FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id)
              WHERE s.source_system = '{SRC}' GROUP BY 1 ORDER BY 2 DESC"""); log("sample types", c.fetchall())
if CHECK:
    c.execute("SELECT pkg, count(*) FROM st_result GROUP BY 1 ORDER BY 2 DESC"); log("values per package", c.fetchall())
    g.rollback(); g.close(); os.remove(res_path); log("CHECK RUN - rolled back before the result rows"); sys.exit(0)

c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
t0 = time.time()
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  NULL, meth.method_code, r.meth_name, NULL, r.val, r.ldl, r.udl, NULL, NULL, false, true, '{TAG}', now(),
  NULL, r.fraction, r.comment
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
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UDL' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results_{PART} r""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_cdogs_20261105', now(), now(), count(*), 'rule-based classification at load (CDoGS negative = below detection, > = above range)'
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
