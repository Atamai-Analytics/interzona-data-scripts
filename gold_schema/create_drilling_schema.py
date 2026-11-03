"""Create the gold `drilling` schema (drill hole collars and downhole surveys) and link geochem samples to drill holes.

  drilling.drillholes  one row per hole: source + source hole id, name, prospect, company, tenement, drill type, purpose, date, total depth,
                       collar azimuth/dip/elevation, collar point (WGS84 lat/lon + geometry) plus the original coordinates and CRS, position
                       accuracy/method, wedge parent, core status/location, optional occurrence link. trace_geom is reserved for a desurveyed trace.
  drilling.surveys     downhole directional surveys (depth, azimuth, dip, azimuth reference).
  geochem.samples.drillhole_id               -> drilling.drillholes (drill samples keep depth_from_m / depth_to_m; sample_context 'DRILLHOLE_INTERVAL')
  geochem.sample_chemistry_wide gets sample_context, drillhole_id, depth_from_m, depth_to_m so the analysis tools can tell drill assays from surface samples.
  geochem.drill_types gets the drill types MRT uses that were missing.
Read access for cm_app_readonly. Idempotent (IF NOT EXISTS / ON CONFLICT).
Usage: python create_drilling_schema.py [--dry]   (--dry = create, report, ROLLBACK)
"""
import os, sys
import psycopg2

DRY = "--dry" in sys.argv
TAG = "create_drilling_schema_20261102"
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()

c.execute("CREATE SCHEMA IF NOT EXISTS drilling")
c.execute("""
CREATE TABLE IF NOT EXISTS drilling.drillholes (
  drillhole_id         bigserial PRIMARY KEY,
  source_system        varchar(40) NOT NULL,
  source_hole_id       varchar(60) NOT NULL,
  hole_name            text,
  prospect             text,
  company              text,
  tenement             text,
  occurrence_id        integer REFERENCES core.occurrences (occurrence_id),
  drill_type_id        integer REFERENCES geochem.drill_types (drill_type_id),
  drill_type_local     text,
  purpose              text,
  driller_category     text,
  date_drilled         date,
  total_depth_m        numeric CHECK (total_depth_m IS NULL OR total_depth_m >= 0),
  azimuth_deg          numeric CHECK (azimuth_deg IS NULL OR azimuth_deg BETWEEN 0 AND 360),
  dip_deg              numeric CHECK (dip_deg IS NULL OR dip_deg BETWEEN -90 AND 90),
  collar_elevation_m   numeric,
  elevation_datum      text,
  lat                  double precision,
  lon                  double precision,
  geom                 geometry(Point, 4326),
  geog                 geography(Point, 4326),
  original_x           numeric,
  original_y           numeric,
  original_crs         text,
  position_accuracy_m  numeric,
  position_method      text,
  elevation_accuracy_m numeric,
  elevation_method     text,
  collared_underground boolean,
  parent_drillhole_id  bigint REFERENCES drilling.drillholes (drillhole_id),
  wedge_depth_m        numeric,
  core_status          text,
  core_store_location  text,
  trace_geom           geometry(LineStringZ, 4326),
  comments             text,
  is_active            boolean NOT NULL DEFAULT true,
  created_by           varchar(60),
  created_date         timestamptz DEFAULT now(),
  modified_by          varchar(60),
  modified_date        timestamptz,
  UNIQUE (source_system, source_hole_id))""")
c.execute("CREATE INDEX IF NOT EXISTS idx_drillholes_geog ON drilling.drillholes USING gist (geog)")
c.execute("CREATE INDEX IF NOT EXISTS idx_drillholes_occ ON drilling.drillholes (occurrence_id)")
c.execute("CREATE INDEX IF NOT EXISTS idx_drillholes_name ON drilling.drillholes (lower(hole_name))")
c.execute("""
CREATE TABLE IF NOT EXISTS drilling.surveys (
  survey_id         bigserial PRIMARY KEY,
  drillhole_id      bigint NOT NULL REFERENCES drilling.drillholes (drillhole_id) ON DELETE CASCADE,
  depth_m           numeric NOT NULL CHECK (depth_m >= 0),
  azimuth_deg       numeric CHECK (azimuth_deg IS NULL OR azimuth_deg BETWEEN 0 AND 360),
  dip_deg           numeric CHECK (dip_deg IS NULL OR dip_deg BETWEEN -90 AND 90),
  azimuth_reference text,
  survey_method     text,
  created_by        varchar(60),
  created_date      timestamptz DEFAULT now())""")
c.execute("CREATE INDEX IF NOT EXISTS idx_surveys_hole ON drilling.surveys (drillhole_id, depth_m)")

c.execute("ALTER TABLE geochem.samples ADD COLUMN IF NOT EXISTS drillhole_id bigint REFERENCES drilling.drillholes (drillhole_id)")
c.execute("CREATE INDEX IF NOT EXISTS idx_samples_drillhole ON geochem.samples (drillhole_id) WHERE drillhole_id IS NOT NULL")
for col, typ in (("sample_context", "varchar(40)"), ("drillhole_id", "bigint"), ("depth_from_m", "numeric"), ("depth_to_m", "numeric")):
    c.execute(f"ALTER TABLE geochem.sample_chemistry_wide ADD COLUMN IF NOT EXISTS {col} {typ}")
c.execute("CREATE INDEX IF NOT EXISTS idx_scw_drillhole ON geochem.sample_chemistry_wide (drillhole_id) WHERE drillhole_id IS NOT NULL")
# existing wide rows: fill sample_context / depths from samples (drillhole_id stays NULL for sources without drill holes)
c.execute("""UPDATE geochem.sample_chemistry_wide w SET sample_context = s.sample_context, depth_from_m = s.depth_from_m, depth_to_m = s.depth_to_m
             FROM geochem.samples s WHERE s.sample_id = w.sample_id AND w.sample_context IS NULL""")
print("wide rows given sample_context:", c.rowcount)

# downhole logs: lithology observations can sit on a drill hole (with depths) without belonging to an analysed sample
c.execute("ALTER TABLE geochem.lithology_observations ADD COLUMN IF NOT EXISTS drillhole_id bigint REFERENCES drilling.drillholes (drillhole_id)")
c.execute("CREATE INDEX IF NOT EXISTS idx_lithobs_drillhole ON geochem.lithology_observations (drillhole_id, depth_from_m) WHERE drillhole_id IS NOT NULL")
# an observation needs a parent: an occurrence, a sample, a sampling line, or (new) a drill hole
c.execute("ALTER TABLE geochem.lithology_observations DROP CONSTRAINT IF EXISTS chk_lithology_observations_parent")
c.execute("""ALTER TABLE geochem.lithology_observations ADD CONSTRAINT chk_lithology_observations_parent
             CHECK (occurrence_id IS NOT NULL OR sample_id IS NOT NULL OR sampling_line_id IS NOT NULL OR drillhole_id IS NOT NULL)""")

# provenance kept per result (all sources; NULL where a source has nothing): the source's own result/analysis id, the size fraction or
# medium analysed (e.g. '-80#', 'Panned Concentrate'), and free-text comments (element comment, analysis comment, repeat number)
for col, typ in (("source_result_id", "varchar(60)"), ("fraction", "text"), ("result_comment", "text")):
    c.execute(f"ALTER TABLE geochem.analytical_results ADD COLUMN IF NOT EXISTS {col} {typ}")

# interval QC: problems found in a drill hole's sample or log intervals, flagged (never deleted)
c.execute("""
CREATE TABLE IF NOT EXISTS drilling.interval_qc (
  interval_qc_id            bigserial PRIMARY KEY,
  drillhole_id              bigint NOT NULL REFERENCES drilling.drillholes (drillhole_id) ON DELETE CASCADE,
  sample_id                 bigint,
  lithology_observation_id  bigint,
  issue                     varchar(30) NOT NULL CHECK (issue IN ('FROM_GT_TO','ZERO_LENGTH','MISSING_DEPTH','BEYOND_EOH','OVERLAP')),
  detail                    text,
  created_by                varchar(60),
  created_date              timestamptz DEFAULT now())""")
c.execute("CREATE INDEX IF NOT EXISTS idx_interval_qc_hole ON drilling.interval_qc (drillhole_id)")
c.execute("CREATE INDEX IF NOT EXISTS idx_interval_qc_sample ON drilling.interval_qc (sample_id) WHERE sample_id IS NOT NULL")

# drill types used by MRT that geochem.drill_types lacks (Cable Tool -> existing PERCUSSION, Hollow Flight Auger -> AUGER, Rotary -> ROTARY)
c.execute("SELECT coalesce(max(display_order), 0) FROM geochem.drill_types")
nord = c.fetchone()[0]
for code, name, cat, desc in [
        ("PERCUSSION_DIAMOND", "Percussion pre-collar with diamond tail", "Core", "Percussion drilling converted to diamond core (percussion pre-collar, diamond tail)."),
        ("ROTARY_DIAMOND", "Rotary pre-collar with diamond tail", "Core", "Rotary drilling converted to diamond core (rotary pre-collar, diamond tail)."),
        ("ROTARY_PERCUSSION", "Rotary pre-collar with percussion tail", "Percussion", "Rotary drilling converted to percussion (rotary pre-collar, percussion tail)."),
        ("PUSH_TUBE", "Push tube", "Direct push", "Direct-push drilling with hydraulic cylinders and hammer advancing a hollow core sampler."),
        ("PIT", "Pit excavation", "Excavation", "Pit excavated and sampled like a hole (recorded as a drill hole by some surveys)."),
        ("UNKNOWN", "Unknown drill type", "Unknown", "Drill type not recorded.")]:
    c.execute("SELECT 1 FROM geochem.drill_types WHERE drill_type_code = %s", (code,))
    if not c.fetchone():
        nord += 1
        c.execute("""INSERT INTO geochem.drill_types (drill_type_code, drill_type_name, drill_type_category, description, display_order, is_active, created_by, created_date)
                     VALUES (%s,%s,%s,%s,%s,true,%s,now())""", (code, name, cat, desc, nord, TAG))

c.execute("GRANT USAGE ON SCHEMA drilling TO cm_app_readonly")
c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA drilling TO cm_app_readonly")
c.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA drilling GRANT SELECT ON TABLES TO cm_app_readonly")

c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'drilling' ORDER BY 1"); print("drilling tables:", [r[0] for r in c.fetchall()])
c.execute("SELECT drill_type_code FROM geochem.drill_types ORDER BY display_order"); print("drill types:", [r[0] for r in c.fetchall()])
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
g.close()
