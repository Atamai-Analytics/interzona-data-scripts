"""Build / refresh geochem.sample_chemistry_wide for one source_system (one row per sample, one column per analyte AND basis).

Columns:  <analyte_code>_t = value from a TOTAL / no-digestion method (XRF pressed pellet, fusion ICP, LECO ...),
          <analyte_code>_p = value from a PARTIAL / selective leach (aqua regia, GFAAS leach ...). Never mixed.
Units:    every non-oxide analyte in ppm, every oxide analyte (is_oxide) in wt%.  Carbon is kept as c_total_pct / c_noncarb_pct / c_carbonate_pct (wt%).
Values:   DETECTED results only (result_classifications.use_in_statistics); censored (below detection) analytes are listed in bdl_codes (text[]).
Choice:   if a sample has several results for the same analyte+basis, the lowest package_wide_rules.priority wins (ICP-MS 1, ICP-OES/AES 2, XRF 3, other 5); ties go to the lowest package_id (one package only; duplicates within that package are averaged).
Greenland (TECH_SOURCES) uses geochem.technique_rank: rank by technique family x element group (setup_greenland_priorities.py), total basis only.
Usage:    python build_chem_wide.py FINLAND_GTK_ROCK [--dry]
"""
import os, re, sys, time
import psycopg2

SRC = sys.argv[1]
DRY = "--dry" in sys.argv   # --dry = rebuild, report, ROLLBACK
# sources whose total-basis method choice follows geochem.technique_rank (technique x element group) instead of package priority
TECH_SOURCES = {"GREENLAND_GEUS", "USA_USGS_NGDB"}
TUNED = SRC in TECH_SOURCES
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


part = {"FINLAND_GTK_ROCK": ("analytical_results_finland_gtk_rock", "result_classifications_finland_gtk_rock"),
        "ARGENTINA_SEGEMAR": ("analytical_results_argentina_segemar", "result_classifications_argentina_segemar"),
        "GREENLAND_GEUS": ("analytical_results_greenland_geus", "result_classifications_greenland_geus"),
        "SWEDEN_SGU_LITHOGEOCHEMISTRY": ("analytical_results_sweden_sgu_lithogeochemistry", "result_classifications_sweden_sgu_lithogeochemistry"),
        "USA_USGS_NGDB": ("analytical_results_usa_usgs_ngdb", "result_classifications_usa_usgs_ngdb"),
        "AUSTRALIA_VIC_GSV_GEOCHEMISTRY": ("analytical_results_australia_vic_gsv_geochemistry", "result_classifications_australia_vic_gsv_geochemistry")}[SRC]

# ---- package rules (basis + priority) for every package
c.execute("""
CREATE TABLE IF NOT EXISTS geochem.package_wide_rules (
  package_id integer PRIMARY KEY, basis char(1) NOT NULL CHECK (basis IN ('T','P')), priority integer NOT NULL, note text)""")
c.execute("""
INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
SELECT p.package_id,
  CASE WHEN m.digest_completeness IN ('Total','No digestion','Near-total','Total (for Au, Ag, PGE)') THEN 'T' ELSE 'P' END,
  CASE WHEN p.package_name ILIKE '%ICP-MS%' THEN 1 WHEN p.package_name ILIKE '%ICP-AES%' OR p.package_name ILIKE '%ICP-OES%' THEN 2
       WHEN p.package_name ILIKE '%XRF%' THEN 3 WHEN p.package_name ILIKE '%LECO%' THEN 1 ELSE 5 END,
  'auto from digest_completeness and package_name'
FROM geochem.analytical_packages p LEFT JOIN geochem.analytical_methods m ON m.method_id = p.method_id
ON CONFLICT (package_id) DO NOTHING""")

# per-source overrides of a package's basis / priority (used where the same package means something different per source, e.g. USGS UNK-* packages)
c.execute("""
CREATE TABLE IF NOT EXISTS geochem.source_package_rules (
  source_system varchar(40) NOT NULL, package_id integer NOT NULL, basis char(1) NOT NULL CHECK (basis IN ('T','P')), priority integer NOT NULL, note text,
  PRIMARY KEY (source_system, package_id))""")

# ---- table
c.execute("""
CREATE TABLE IF NOT EXISTS geochem.sample_chemistry_wide (
  sample_id bigint PRIMARY KEY, source_system varchar(40) NOT NULL, occurrence_id integer,
  sample_type_name text, lithology_code text, lithology_name text, lithology_category text, lithology_local text,
  sample_date timestamptz, lat double precision, lon double precision, geog geography(Point, 4326),
  n_values integer, bdl_codes text[], built_at timestamptz DEFAULT now())""")
c.execute("CREATE INDEX IF NOT EXISTS idx_scw_geog ON geochem.sample_chemistry_wide USING gist (geog)")
c.execute("CREATE INDEX IF NOT EXISTS idx_scw_source ON geochem.sample_chemistry_wide (source_system)")
c.execute("CREATE INDEX IF NOT EXISTS idx_scw_lith ON geochem.sample_chemistry_wide (lithology_code)")
c.execute("CREATE INDEX IF NOT EXISTS idx_scw_occ ON geochem.sample_chemistry_wide (occurrence_id)")

# ---- which analyte/basis columns does this source need?
if TUNED:
    PRIO = ("CASE WHEN coalesce(so.basis, w.basis) = 'T' AND a.analyte_code <> 'C' AND (a.is_oxide OR ag.analyte_group IS NOT NULL) "
            "THEN coalesce(tr.rank, 9) ELSE coalesce(so.priority, w.priority) END")
    TJOIN = ("LEFT JOIN geochem.analyte_groups ag ON ag.analyte_symbol = a.element_symbol AND NOT a.is_oxide "
             "LEFT JOIN geochem.package_technique pt ON pt.package_id = r.package_id "
             "LEFT JOIN geochem.technique_rank tr ON tr.analyte_group = CASE WHEN a.is_oxide THEN 'MAJOR' ELSE ag.analyte_group END AND tr.technique = pt.technique")
else:
    PRIO, TJOIN = "coalesce(so.priority, w.priority)", ""
ROWS = f"""
SELECT r.sample_id, r.result_id, r.package_id,
  CASE WHEN a.analyte_code = 'C' AND p.package_name ILIKE 'Non-Carbonate%' THEN 'C_NONCARB'
       WHEN a.analyte_code = 'C' THEN 'C_TOTAL' ELSE a.analyte_code END AS code,
  CASE WHEN a.analyte_code = 'C' THEN 'T' ELSE coalesce(so.basis, w.basis) END AS basis, {PRIO} AS priority,
  CASE WHEN a.analyte_code = 'C' THEN
         CASE r.unit_code WHEN '%' THEN r.value WHEN 'ppm' THEN r.value / 10000.0 WHEN 'mg/kg' THEN r.value / 10000.0 WHEN 'ppb' THEN r.value / 10000000.0 END
       WHEN a.is_oxide OR (NOT a.is_element AND NOT a.is_oxide) THEN
         CASE r.unit_code WHEN '%' THEN r.value WHEN 'ppm' THEN r.value / 10000.0 WHEN 'mg/kg' THEN r.value / 10000.0 WHEN 'ppb' THEN r.value / 10000000.0 END
       ELSE
         CASE r.unit_code WHEN 'ppm' THEN r.value WHEN 'mg/kg' THEN r.value WHEN '%' THEN r.value * 10000.0 WHEN 'ppb' THEN r.value / 1000.0 END
  END AS v,
  coalesce(k.use_in_statistics, true) AS det, r.unit_code AS u, coalesce(k.result_status, 'DETECTED') AS st
FROM geochem.{part[0]} r
JOIN geochem.analytes a ON a.analyte_id = r.analyte_id
JOIN geochem.analytical_packages p ON p.package_id = r.package_id
JOIN geochem.package_wide_rules w ON w.package_id = r.package_id
LEFT JOIN geochem.source_package_rules so ON so.source_system = '{SRC}' AND so.package_id = r.package_id
{TJOIN}
LEFT JOIN geochem.{part[1]} k ON k.result_id = r.result_id
WHERE r.is_active AND r.value IS NOT NULL"""
c.execute(f"SELECT DISTINCT code, basis FROM ({ROWS}) x ORDER BY 1, 2")
pairs = c.fetchall()
c.execute(f"SELECT u, count(*) FROM ({ROWS}) x WHERE v IS NULL GROUP BY u")
_skipped = c.fetchall()
SKIP_UNITS = {"unitless", "Mole%", "pH", "g/m³"}   # not concentrations: left out of the wide table (still in analytical_results)
assert all(u in SKIP_UNITS for u, _ in _skipped), ("unit not handled", _skipped)
log("rows left out (non-concentration units)", _skipped)


def colname(code, basis):
    if code == "C_TOTAL": return "c_total_pct"
    if code == "C_NONCARB": return "c_noncarb_pct"
    base = re.sub(r"[^a-z0-9]+", "_", code.lower())
    return f"{base}_{basis.lower()}"


cols = {}
for code, basis in pairs:
    cn = colname(code, basis)
    assert cn not in cols, ("collision", cn)
    cols[cn] = (code, basis)
log("analyte columns for", SRC, len(cols))
for cn in cols:
    c.execute(f"ALTER TABLE geochem.sample_chemistry_wide ADD COLUMN IF NOT EXISTS {cn} double precision")
c.execute("ALTER TABLE geochem.sample_chemistry_wide ADD COLUMN IF NOT EXISTS c_carbonate_pct double precision")

# ---- rebuild rows for this source
c.execute("DELETE FROM geochem.sample_chemistry_wide WHERE source_system = %s", (SRC,))
sel = ",\n  ".join(f"max(b.v) FILTER (WHERE b.code = '{code}' AND b.basis = '{basis}') AS {cn}" for cn, (code, basis) in cols.items())
insert_cols = ", ".join(cols.keys())
sql = f"""
WITH r AS ({ROWS}),
d AS (SELECT sample_id, code, basis, priority, package_id, avg(v) AS v FROM r WHERE det AND v IS NOT NULL GROUP BY 1, 2, 3, 4, 5),
b AS (SELECT DISTINCT ON (sample_id, code, basis) sample_id, code, basis, v FROM d ORDER BY sample_id, code, basis, priority, package_id),
piv AS (SELECT b.sample_id, count(*) AS n_values,
  {sel}
  FROM b GROUP BY b.sample_id),
cen AS (SELECT x.sample_id, array_agg(DISTINCT lower(x.code) || '_' || lower(x.basis) ORDER BY lower(x.code) || '_' || lower(x.basis)) AS bdl
  FROM r x WHERE NOT x.det AND x.v IS NOT NULL AND x.st <> 'ABOVE_UDL' AND NOT EXISTS (SELECT 1 FROM b WHERE b.sample_id = x.sample_id AND b.code = x.code AND b.basis = x.basis) GROUP BY x.sample_id)
INSERT INTO geochem.sample_chemistry_wide (sample_id, source_system, occurrence_id, sample_type_name, lithology_code, lithology_name, lithology_category, lithology_local,
  sample_date, lat, lon, geog, n_values, bdl_codes, {insert_cols})
SELECT s.sample_id, s.source_system, s.occurrence_id, st.sample_type_name, lit.lithology_code, lit.lithology_name, lit.category_code, lo.lithology_local,
  s.sample_date, s.lat, s.lon, s.geog, coalesce(piv.n_values, 0), cen.bdl, {", ".join("piv." + cn for cn in cols)}
FROM geochem.samples s
LEFT JOIN geochem.sample_types st ON st.sample_type_id = s.sample_type_id
LEFT JOIN LATERAL (SELECT * FROM geochem.lithology_observations o WHERE o.sample_id = s.sample_id AND o.is_active ORDER BY o.lithology_observation_id LIMIT 1) lo ON true
LEFT JOIN geochem.lithology lit ON lit.lithology_id = lo.lithology_id
LEFT JOIN piv ON piv.sample_id = s.sample_id
LEFT JOIN cen ON cen.sample_id = s.sample_id
WHERE s.source_system = '{SRC}' AND s.is_active"""
t0 = time.time()
c.execute(sql)
log("inserted", c.rowcount, "rows in", round(time.time() - t0), "s")
c.execute("UPDATE geochem.sample_chemistry_wide SET c_carbonate_pct = c_total_pct - c_noncarb_pct WHERE source_system = %s AND c_total_pct IS NOT NULL AND c_noncarb_pct IS NOT NULL", (SRC,))
c.execute("ANALYZE geochem.sample_chemistry_wide")
c.execute("SELECT count(*), sum(n_values), avg(n_values)::int, count(lithology_code), count(bdl_codes) FROM geochem.sample_chemistry_wide WHERE source_system = %s", (SRC,))
log("rows, sum values, avg values/sample, with lithology, with bdl", c.fetchone())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
