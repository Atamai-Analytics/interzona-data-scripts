"""Förster, H.-J. (2021, 2022) whole-rock geochemistry of late-Variscan granites of the Erzgebirge-Vogtland metallogenic province (Saxony,
Germany), GFZ Data Services, CC BY 4.0 -> interzona_cm source GERMANY_GFZ_ERZGEBIRGE (2026-11-10).
  Part 1 (doi:10.5880/GFZ.4.8.2021.005): P- and F-rich Li-mica granites (Eibenstock, Satzung, Pobershau, Geyer, Annaberg) - 134 samples
  Part 2 (doi:10.5880/GFZ.4.8.2022.002): F-poor biotite and two-mica granites (Kirchberg, Niederbobritzsch, Aue suite, Bergen, Lauter,
          Schwarzenberg ...) - 175 samples
Files: D:/CriticalMineralsDB/Germany/gfz_erzgebirge_20261110 (xlsx + description PDFs). Licence evidence: Licence_Evidence/GFZ_Erzgebirge.

Methods (data description, section 4; all at GFZ Potsdam) -> packages:
  GFZ-ERZ-XRF      majors SiO2..P2O5, Fe2O3tot (FETO3)    WD-XRF on lithium tetraborate fused discs   LIBOR-XRF   total, priority 1
  GFZ-ERZ-ICPMS-A  REE, Rb, Sr, Y, Zr, Cs, Ba, Hf, Pb, Th, U  ICP-MS (Dulski 1994), acid pressure digestion  MX-ICPMS   total, priority 1
  GFZ-ERZ-ICPMS-B  Li, Sc, Co, Ni, Zn, Ga, Nb, Mo, Sn, Sb, Ta, W, Tl, Bi  ICP-MS (Plessen et al. 1994)        MX-ICPMS   total, priority 1
                   (Sn may instead be XRF on pressed pellets - the data set does not say per sample)
  GFZ-ERZ-ICPAES   Be                                     ICP-AES                                      MX-ICPOES  total, priority 2
  GFZ-ERZ-ISE      F (wt %)                                ion-selective electrode                      ISE-F (new) total, priority 1
  GFZ-ERZ-COMB     H2O+ (as H2O), CO2 (wt %)              combustion - infrared detection              NONE-INDFUR total, priority 1
  GFZ-ERZ-NS       B, As, V, Cr, Cu, Cd                   method NOT stated in the description         UNKNOWN-UNKNOWN total, priority 5
Not loaded: the derived columns (sums, A/CNK, ratios, heat production) - recomputable; 'total'.
'<x' -> qualifier '<', value x, lower detection limit x; '>x' -> qualifier '>', value x. Blank / NA = not measured (no row).
Samples: 'surface' -> ROCK_SAMPLE, context SURFACE (quarry / locality in comments); 'subsurface' -> CORE_SAMPLE, context DRILLHOLE_POINT,
depth_from = depth_to = the sample depth, borehole number (mostly SDAG Wismut holes) in sample_number_alt and comments.
Lithology from the sub-intrusion code: A(...) aplite; E... enclave (stored as XENOLITH, category OTHER); otherwise granite; '/ EC' endocontact and 'cord'
cordierite-bearing facies noted; remarks 'alt' / 'alt/min' -> alteration_local 'altered' / 'altered, mineralised'.
Usage: python -P load_gfz_erzgebirge.py [--check]   (--check = everything, then ROLLBACK)
"""
import os, sys, io, csv, re, time, collections
import pandas as pd
import psycopg2

CHECK = "--check" in sys.argv
TAG = "migration_gfz_erzgebirge_20261110"
SRC, PART, XID = "GERMANY_GFZ_ERZGEBIRGE", "germany_gfz_erzgebirge", "GFZ_ERZGEBIRGE_FOERSTER"
D = "D:/CriticalMineralsDB/Germany/gfz_erzgebirge_20261110"
FILES = [("2021-005_Foerster-WR-Li-F-granite.xlsx", 0, "Part 1: P-F-rich Li-mica granites", "doi:10.5880/GFZ.4.8.2021.005"),
         ("2021-002_Foerster-WR-bt+tm-granite.xlsx", 4, "Part 2: F-poor biotite and two-mica granites", "doi:10.5880/GFZ.4.8.2022.002")]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


MAJORS = {"SiO2": "SiO2", "TiO2": "TiO2", "Al2O3": "Al2O3", "Fe2O3tot": "FETO3", "MnO": "MnO", "MgO": "MgO", "CaO": "CaO", "Na2O": "Na2O",
          "K2O": "K2O", "P2O5": "P2O5"}
ICPA = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Rb", "Sr", "Y", "Zr", "Cs", "Ba", "Hf", "Pb", "Th", "U"]
ICPB = ["Li", "Sc", "Co", "Ni", "Zn", "Ga", "Nb", "Mo", "Sn", "Sb", "Ta", "W", "Tl", "Bi"]
NS = ["B", "As", "V", "Cr", "Cu", "Cd"]
COLMAP = {**{k: (v, "%", "GFZ-ERZ-XRF") for k, v in MAJORS.items()},
          **{e: (e, "ppm", "GFZ-ERZ-ICPMS-A") for e in ICPA}, **{e: (e, "ppm", "GFZ-ERZ-ICPMS-B") for e in ICPB},
          **{e: (e, "ppm", "GFZ-ERZ-NS") for e in NS}, "Be": ("Be", "ppm", "GFZ-ERZ-ICPAES"),
          "F": ("F", "%", "GFZ-ERZ-ISE"), "H2O+": ("H2O", "%", "GFZ-ERZ-COMB"), "CO2": ("CO2", "%", "GFZ-ERZ-COMB")}
PKG = {  # code: (name, method_code, priority)
    "GFZ-ERZ-XRF": ("GFZ Potsdam - WD-XRF, lithium tetraborate fused discs (Siemens SRS303AS)", "LIBOR-XRF", 1),
    "GFZ-ERZ-ICPMS-A": ("GFZ Potsdam - ICP-MS (Perkin-Elmer/Sciex Elan 500; Dulski 1994): REE, Rb, Sr, Y, Zr, Cs, Ba, Hf, Pb, Th, U", "MX-ICPMS", 1),
    "GFZ-ERZ-ICPMS-B": ("GFZ Potsdam - ICP-MS (VG PlasmaQuad PQ2+; Plessen et al. 1994): Li, Sc, Co, Ni, Zn, Ga, Nb, Mo, Sn, Sb, Ta, W, Tl, Bi", "MX-ICPMS", 1),
    "GFZ-ERZ-ICPAES": ("GFZ Potsdam - ICP-AES (Varian Liberty 200): Be", "MX-ICPOES", 2),
    "GFZ-ERZ-ISE": ("GFZ Potsdam - fluorine by ion-selective electrode", "ISE-F", 1),
    "GFZ-ERZ-COMB": ("GFZ Potsdam - total water (H2O+) and CO2 by combustion - infrared detection", "NONE-INDFUR", 1),
    "GFZ-ERZ-NS": ("GFZ Potsdam - B, As, V, Cr, Cu, Cd: analytical method not stated in the data description", "UNKNOWN-UNKNOWN", 5),
}
NUM = re.compile(r"^\s*([<>])?\s*(-?\d+(?:[.,]\d+)?)\s*$")


def lithology(code):
    s = (code or "").strip()
    notes = []
    if "/ EC" in s or s.endswith("EC"): notes.append("endocontact")
    if "cord" in s.lower(): notes.append("cordierite-bearing")
    if "qtz" in s.lower(): notes.append("quartz-rich")
    if s.startswith("A("): return "APLITE", "aplite" + (" (" + ", ".join(notes) + ")" if notes else ""), notes
    if re.match(r"^E[a-d]?(\(|\s*-|-)", s): return "XENOLITH", "enclave (" + s + ")", notes   # vocabulary has no 'enclave'; XENOLITH, category OTHER
    return "GRANITE", "granite" + (" (" + ", ".join(notes) + ")" if notes else ""), notes


samples, results, liths, stats = {}, [], [], collections.Counter()
for fname, hdr, part, doi in FILES:
    raw = pd.read_excel(os.path.join(D, fname), header=None, dtype=str)
    head = [str(h).strip() if isinstance(h, str) else "" for h in raw.iloc[hdr]]
    data = raw.iloc[hdr + 4:].reset_index(drop=True)
    col = lambda name: head.index(name)
    i_sn = [i for i, h in enumerate(head) if h.lower().startswith("sample no")][0]
    i_mass = 1 if hdr else 0          # part 2 has a granite-group column first
    i_sub = i_mass + 1
    group = None
    for c in (i_mass, i_sub) + ((0,) if hdr else ()):
        data.iloc[:, c] = data.iloc[:, c].ffill()
    for _, r in data.iterrows():
        sid = str(r.iloc[i_sn]).strip() if isinstance(r.iloc[i_sn], str) else None
        if not sid or sid == "nan": continue
        if sid in samples: raise SystemExit(f"duplicate sample number {sid}")
        lat, lon = float(r.iloc[col("Latitude")]), float(r.iloc[col("Longitude")])
        origin = (r.iloc[col("origin")] or "").strip()
        hole = r.iloc[col("borehole No./quarry")] if isinstance(r.iloc[col("borehole No./quarry")], str) else None
        dtxt = r.iloc[col("sample depth")] if isinstance(r.iloc[col("sample depth")], str) else ""
        dnum = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", dtxt)]
        if dtxt.strip() and not dnum: raise SystemExit(f"unparsed depth {dtxt!r} for {r.iloc[i_sn]}")
        depth, depth_to = (dnum[0], dnum[-1]) if dnum else (None, None)
        remark = (r.iloc[col("remarks")] or "").replace(" ", "") if isinstance(r.iloc[col("remarks")], str) else ""
        massif, sub = r.iloc[i_mass], r.iloc[i_sub]
        ggroup = " ".join(str(x) for x in [r.iloc[0]] if hdr and isinstance(x, str)) if hdr else "P-F-rich Li-mica granite"
        lcode, llocal, lnotes = lithology(sub)
        sub_surface = origin.lower().startswith("sub")
        ref = r.iloc[len(head) - 1] if isinstance(r.iloc[len(head) - 1], str) else None
        com = "; ".join(x for x in [f"Förster (GFZ) Erzgebirge-Vogtland granite geochemistry {part}, {doi}",
                                    f"massif/suite {massif}", f"sub-intrusion/facies {sub}", f"granite group {ggroup}",
                                    f"{'borehole' if sub_surface else 'quarry/locality'} {hole}" if hole else None,
                                    f"sample depth {dtxt.strip()} m below surface" if depth is not None else None,
                                    {"alt": "altered (remark 'alt')", "alt/min": "altered and mineralised (remark 'alt/min')"}.get(remark),
                                    f"previously published in {ref}" if ref else None] if x)
        samples[sid] = [sid, "CORE_SAMPLE" if sub_surface else "ROCK_SAMPLE", f"{llocal} - {massif} {sub}".strip(), lon, lat, com,
                        "DRILLHOLE_POINT" if sub_surface else "SURFACE", depth if sub_surface else None,
                        depth_to if sub_surface else None, hole if sub_surface else None]
        liths.append([sid, lcode, f"{llocal}; {massif} {sub}", {"alt": "altered", "alt/min": "altered, mineralised"}.get(remark)])
        stats["subsurface" if sub_surface else "surface"] += 1
        for name, (an, unit, pkg) in COLMAP.items():
            v = r.iloc[col(name)]
            if not isinstance(v, str) or not v.strip() or v.strip().upper() == "NA": continue
            m = NUM.match(v.replace(",", "."))
            if not m: stats[f"unparsed {v[:10]}"] += 1; continue
            qual, val = m.group(1), float(m.group(2).replace(",", "."))
            if val < 0: stats["negative"] += 1; continue
            comment = "H2O+ (total water)" if name == "H2O+" else ("Sn: ICP-MS or XRF pressed pellet, not stated per sample" if name == "Sn" else N)
            results.append([sid, pkg, an, unit, qual or N, val, val if qual == "<" else N, N, comment])
            stats["values"] += 1; stats[f"qual {qual}"] += bool(qual)
log("samples", len(samples), "| results", len(results), "|", dict(stats))
lats = [s[4] for s in samples.values()]; lons = [s[3] for s in samples.values()]
log("lat range", min(lats), max(lats), "| lon range", min(lons), max(lons))
assert 49.9 < min(lats) and max(lats) < 51.3 and 11.8 < min(lons) and max(lons) < 14.6, "outside the Erzgebirge-Vogtland box"

p0 = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
p0.autocommit = True
if not CHECK:
    p0.cursor().execute("SET lock_timeout = '20s'")
    p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.analytical_results_{PART} PARTITION OF geochem.analytical_results FOR VALUES IN ('{SRC}')")
    p0.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.result_classifications_{PART} PARTITION OF geochem.result_classifications FOR VALUES IN ('{SRC}')")
p0.close()
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"


def copy(table, cols_sql, data):
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    buf = io.StringIO(); cw = csv.writer(buf)
    for r in data: cw.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0); c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


copy("st_sample", "skey text, stype text, stype_local text, lon double precision, lat double precision, comments text, ctx text, depth numeric, depth_to numeric, hole text",
     samples.values())
copy("st_result", "skey text, pkg text, analyte text, unit text, qual text, val numeric, ldl numeric, fraction text, comment text", results)
copy("st_lith", "skey text, lcode text, llocal text, alt text", liths)

c.execute("""INSERT INTO geochem.laboratories (lab_code, lab_name, contact_info, is_active, created_by, created_date)
             SELECT 'GFZ', 'GFZ German Research Centre for Geosciences, Potsdam (analytical facilities)', 'https://www.gfz.de', true, %s, now()
             WHERE NOT EXISTS (SELECT 1 FROM geochem.laboratories WHERE lab_code = 'GFZ')""", (TAG,))
c.execute("""INSERT INTO geochem.analytical_methods (method_code, method_name, digest_code, digest_name, digest_completeness, digest_description,
             instrument_code, instrument_name, application, notes, is_active, created_by, created_date)
             SELECT 'ISE-F', 'Fluorine / Ion-Selective Electrode (sample decomposition not stated)', 'UNK', 'Not stated', 'Total (as reported)',
                    'Fluorine determined with an ion-selective electrode; the decomposition (usually alkaline fusion) is not stated by the source.',
                    'ISE', 'Ion-Selective Electrode', 'Whole-rock fluorine', 'Added for GFZ Erzgebirge granite geochemistry (2026-11-10).', true, %s, now()
             WHERE NOT EXISTS (SELECT 1 FROM geochem.analytical_methods WHERE method_code = 'ISE-F')""", (TAG,))
c.execute("SELECT method_code, method_id FROM geochem.analytical_methods"); mid = dict(c.fetchall())
for code, (name, mcode, prio) in PKG.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = 'GFZ'),%s,%s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""",
              (code, name, mid[mcode], "Förster (2021, 2022) GFZ Erzgebirge-Vogtland granite geochemistry; methods per the data description section 4", TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, 'T', %s, 'GFZ Erzgebirge (Förster)' FROM geochem.analytical_packages WHERE package_code = %s ON CONFLICT DO NOTHING""", (prio, code))
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, 'T', %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (SRC, prio, "GFZ Erzgebirge mapping " + TAG, code))
for label, sql in [("analyte", "SELECT DISTINCT r.analyte FROM st_result r LEFT JOIN geochem.analytes a ON a.analyte_code = r.analyte WHERE a.analyte_id IS NULL"),
                   ("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                   ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                   ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL"),
                   ("lithology", "SELECT DISTINCT l.lcode FROM st_lith l LEFT JOIN geochem.lithology x ON x.lithology_code = l.lcode WHERE l.lcode IS NOT NULL AND x.lithology_id IS NULL")]:
    c.execute(sql); miss = [r[0] for r in c.fetchall()]; assert not miss, (label, miss)
log("dictionary checks passed")
c.execute("""CREATE TEMP TABLE st_map ON COMMIT DROP AS SELECT s.skey, nextval('geochem.samples_sample_id_seq') AS sample_id,
             ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326) AS pt FROM st_sample s""")
c.execute(f"""INSERT INTO geochem.samples (sample_id, geom, sample_number, sample_number_alt, sample_type_id, sample_type_local, sample_context,
  depth_from_m, depth_to_m, comments, is_active, created_by, created_date, source_system) OVERRIDING SYSTEM VALUE
  SELECT m.sample_id, m.pt, s.skey, s.hole, t.sample_type_id, s.stype_local, s.ctx, s.depth, s.depth_to, nullif(s.comments, ''), true, '{TAG}', now(), '{SRC}'
  FROM st_sample s JOIN st_map m USING (skey) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
log("samples inserted", c.rowcount)
c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
              SELECT 'SAMPLE', sample_id, '{XID}', skey, '{TAG}', now() FROM st_map""")
c.execute(f"""INSERT INTO geochem.lithology_observations (lithology_id, lithology_local, observation_context, sample_id, alteration_local, comments,
              is_active, created_by, created_date)
              SELECT x.lithology_id, l.llocal, 'POINT_LOCATION', m.sample_id, l.alt, 'Lithology from the source sub-intrusion code', true, '{TAG}', now()
              FROM st_lith l JOIN st_map m USING (skey) LEFT JOIN geochem.lithology x ON x.lithology_code = l.lcode""")
log("lithology observations", c.rowcount)
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"""
INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
  unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
  value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
  source_result_id, fraction, result_comment)
SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, q.qualifier_id, q.qualifier_code,
  'GFZ Potsdam', meth.method_code, p.package_name, meth.digest_name, r.val, r.ldl, NULL, NULL, NULL, false, true, '{TAG}', now(), NULL, r.fraction, r.comment
FROM st_result r JOIN st_map m ON m.skey = r.skey JOIN geochem.analytes a ON a.analyte_code = r.analyte JOIN geochem.units u ON u.unit_code = r.unit
JOIN geochem.analytical_packages p ON p.package_code = r.pkg LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id
LEFT JOIN geochem.qualifiers q ON q.qualifier_code = r.qual""")
nins = c.rowcount
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("results inserted", nins, "of", len(results)); assert nins == len(results)
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT r.result_id, r.source_system,
  CASE WHEN r.qualifier_code = '<' THEN 'BELOW_DL_QUALIFIED' WHEN r.qualifier_code = '>' THEN 'ABOVE_UL_QUALIFIED' WHEN r.value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END,
  CASE WHEN r.qualifier_code = '<' THEN r.lower_detection_limit END, CASE WHEN r.qualifier_code = '<' THEN 'QUALIFIER_LDL' END,
  r.qualifier_code IS NULL AND r.value IS NOT NULL
FROM geochem.analytical_results r WHERE r.source_system = '{SRC}'""")
c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
 SELECT source_system, 'rule_gfz_erzgebirge_20261110', now(), now(), count(*), 'rule-based at load: < = below DL, > = above upper limit, else detected'
 FROM geochem.result_classifications WHERE source_system = %s GROUP BY 1
 ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""", (SRC,))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-10',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "GFZ German Research Centre for Geosciences (GFZ Data Services); author H.-J. Förster",
           "Geochemistry of late-Variscan felsic igneous rocks of the Erzgebirge-Vogtland metallogenic province, Parts 1 (P-F-rich Li-mica granites) and 2 "
           "(F-poor biotite and two-mica granites) - 309 whole-rock analyses",
           "Creative Commons Attribution 4.0 International (CC BY 4.0)", "https://creativecommons.org/licenses/by/4.0/",
           "Förster, H.-J. (2021): Geochemistry of late-Variscan felsic igneous rocks of the Erzgebirge-Vogtland metallogenic province - Part 1. GFZ Data "
           "Services, https://doi.org/10.5880/GFZ.4.8.2021.005; Förster, H.-J. (2022): ... Part 2. GFZ Data Services, https://doi.org/10.5880/GFZ.4.8.2022.002. CC BY 4.0.",
           "Cleared: CC BY 4.0 on the GFZ landing pages and in the spreadsheet header (checked 2026-11-10). Loaded 2026-11-10.",
           "Academic compilation of granite, aplite, endocontact and enclave samples, not an exploration survey; 103 samples are drill core from (mostly "
           "SDAG Wismut) boreholes at the stated depth, the rest outcrop/quarry. Several samples share a quarry coordinate. Altered and mineralised "
           "samples are flagged in comments and alteration_local. B, As, V, Cr, Cu, Cd method not stated; Sn by ICP-MS or XRF.",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/GFZ_Erzgebirge", TAG))
c.execute(f"""SELECT a.analyte_code, count(*), count(*) FILTER (WHERE r.qualifier_code = '<'), round(min(r.value)::numeric, 3), round(max(r.value)::numeric, 3)
              FROM geochem.analytical_results r JOIN geochem.analytes a USING (analyte_id) WHERE r.source_system = '{SRC}'
              AND a.analyte_code IN ('SiO2','Li','Sn','W','Ta','Rb','Cs','F','FETO3','Be') GROUP BY 1 ORDER BY 1""")
log("key analytes (n, <DL, min, max)", c.fetchall())
c.execute(f"SELECT sample_context, count(*), min(depth_from_m), max(depth_from_m) FROM geochem.samples WHERE source_system = '{SRC}' GROUP BY 1")
log("contexts", c.fetchall())
if CHECK:
    g.rollback(); log("CHECK RUN - rolled back"); sys.exit(0)
g.commit(); log("COMMITTED")
