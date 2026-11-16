"""Per-country coverage counts for the app's World coverage map (/tools/coverage).

core.country_boundaries: Natural Earth 1:50m admin-0 countries (public domain), keyed by ADM0_A3 (ISO_A3 is -99 for France, Norway, Kosovo...).
  Loaded once with --load-boundaries from D:/CriticalMineralsDB/GIS/NaturalEarth_20261115/ne_50m_admin_0_countries.geojson.
core.country_coverage: one row per country (adm0_a3) with samples, active analyses, occurrences, deposits, drill holes, documents tagged to the
  country, and the main sample sources; plus a row adm0_a3 = 'OFF' for points more than ~25 km outside every country polygon (offshore / unassigned).
  Points are assigned by point-in-polygon on subdivided boundaries; points just outside the coastline go to the nearest country within 0.25 degrees.
  Documents use docs.documents.jurisdiction_id (division -> parent country) matched to the boundary by ISO3 or name.
Re-run after data loads:  python build_country_coverage.py          (about 5-10 minutes; replaces core.country_coverage in one transaction)
Also writes the simplified boundary GeoJSON for the web page with --export <path>.
"""
import json, os, sys, time
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
NE = "D:/CriticalMineralsDB/GIS/NaturalEarth_20261115/ne_50m_admin_0_countries.geojson"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:7.0f}s", *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '256MB'")

if "--load-boundaries" in sys.argv:
    c.execute("""CREATE TABLE IF NOT EXISTS core.country_boundaries (adm0_a3 text PRIMARY KEY, iso_a3 text, name text NOT NULL, name_long text,
                 sovereignt text, continent text, geom geometry(MultiPolygon, 4326) NOT NULL, source text, created_date timestamptz DEFAULT now())""")
    c.execute("DELETE FROM core.country_boundaries")
    for f in json.load(open(NE, encoding="utf-8"))["features"]:
        p = f["properties"]
        c.execute("""INSERT INTO core.country_boundaries (adm0_a3, iso_a3, name, name_long, sovereignt, continent, geom, source)
                     VALUES (%s,%s,%s,%s,%s,%s, ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)))::geometry(MultiPolygon,4326), 'Natural Earth 1:50m admin-0 (public domain)')""",
                  (p["ADM0_A3"], None if p["ISO_A3"] == "-99" else p["ISO_A3"], p["NAME"], p["NAME_LONG"], p["SOVEREIGNT"], p["CONTINENT"], json.dumps(f["geometry"])))
    c.execute("CREATE INDEX IF NOT EXISTS country_boundaries_geom ON core.country_boundaries USING gist (geom)")
    g.commit(); c.execute("SELECT count(*) FROM core.country_boundaries"); log("boundaries", c.fetchone()[0])

if "--export" in sys.argv:
    path = sys.argv[sys.argv.index("--export") + 1]
    c.execute("""SELECT json_build_object('type','FeatureCollection','features', json_agg(json_build_object('type','Feature',
                   'properties', json_build_object('a3', adm0_a3, 'name', name),
                   'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.04), 3)::json)))
                 FROM core.country_boundaries""")
    open(path, "w", encoding="utf-8").write(json.dumps(c.fetchone()[0], separators=(",", ":")))
    log("exported", path, os.path.getsize(path), "bytes"); sys.exit(0)

# subdivided boundaries for fast point-in-polygon
c.execute("CREATE TEMP TABLE cb AS SELECT adm0_a3, ST_Subdivide(geom, 64) AS geom FROM core.country_boundaries")
c.execute("CREATE INDEX ON cb USING gist (geom)"); c.execute("ANALYZE cb")


def assign(table, idcol, where):
    """temp table <table>_c (id, a3) for the rows of a point table"""
    out = table.split(".")[-1] + "_c"
    c.execute(f"""CREATE TEMP TABLE {out} AS SELECT DISTINCT ON (t.{idcol}) t.{idcol} AS id, cb.adm0_a3 AS a3
                  FROM {table} t JOIN cb ON ST_Intersects(cb.geom, t.geom) WHERE {where} AND t.geom IS NOT NULL ORDER BY t.{idcol}""")
    n_in = c.rowcount
    c.execute(f"""INSERT INTO {out} SELECT t.{idcol}, coalesce((SELECT cb.adm0_a3 FROM cb WHERE ST_DWithin(cb.geom, t.geom, 0.25)
                     ORDER BY cb.geom <-> t.geom LIMIT 1), 'OFF')
                  FROM {table} t WHERE {where} AND t.geom IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {out} o WHERE o.id = t.{idcol})""")
    n_out = c.rowcount
    c.execute(f"CREATE INDEX ON {out} (id)"); c.execute(f"ANALYZE {out}")
    log(table, "inside", n_in, "| coastal/offshore", n_out)
    return out


sc = assign("geochem.samples", "sample_id", "is_active")  # superseded copies (e.g. CDoGS Yukon) are inactive
oc = assign("core.occurrences", "occurrence_id", "is_active")
dc = assign("drilling.drillholes", "drillhole_id", "coalesce(is_active, true)")
# active analyses per country: each results partition joined to the sample assignment
c.execute("""SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent
             JOIN pg_namespace n ON n.oid = p.relnamespace WHERE n.nspname = 'geochem' AND p.relname = 'analytical_results'""")
parts = [r[0] for r in c.fetchall()]
c.execute("CREATE TEMP TABLE ac (a3 text, n bigint)")
for p in parts:
    c.execute(f"INSERT INTO ac SELECT s.a3, count(*) FROM geochem.{p} r JOIN {sc} s ON s.id = r.sample_id WHERE r.is_active GROUP BY 1")
    log("analyses", p)
c.execute("""CREATE TEMP TABLE dc_docs AS
             SELECT b.adm0_a3 AS a3, count(DISTINCT d.document_id) n FROM docs.documents d
             JOIN core.jurisdictions j ON j.jurisdiction_id = d.jurisdiction_id
             LEFT JOIN core.jurisdictions pj ON pj.jurisdiction_id = j.parent_jurisdiction_id
             JOIN LATERAL (SELECT CASE WHEN j.level = 'COUNTRY' THEN j ELSE pj END AS cj) x ON true
             JOIN core.country_boundaries b ON b.iso_a3 = (x.cj).iso_code3 OR lower(b.name) = lower((x.cj).name) OR lower(b.name_long) = lower((x.cj).name)
             WHERE d.is_active GROUP BY 1""")
c.execute("""CREATE TABLE IF NOT EXISTS core.country_coverage (adm0_a3 text PRIMARY KEY, name text, samples bigint, analyses bigint, occurrences bigint,
             deposits bigint, drill_holes bigint, documents bigint, sample_sources text, updated_at timestamptz)""")
c.execute("DELETE FROM core.country_coverage")
c.execute(f"""
INSERT INTO core.country_coverage
SELECT k.a3, coalesce(b.name, 'Offshore / outside country boundaries'),
  coalesce(s.n, 0), coalesce(a.n, 0), coalesce(o.n, 0), coalesce(o.dep, 0), coalesce(h.n, 0), coalesce(dd.n, 0), src.list, now()
FROM (SELECT a3 FROM {sc} UNION SELECT a3 FROM {oc} UNION SELECT a3 FROM {dc} UNION SELECT a3 FROM dc_docs UNION SELECT adm0_a3 FROM core.country_boundaries) k
LEFT JOIN core.country_boundaries b ON b.adm0_a3 = k.a3
LEFT JOIN (SELECT a3, count(*) n FROM {sc} GROUP BY 1) s ON s.a3 = k.a3
LEFT JOIN (SELECT a3, sum(n) n FROM ac GROUP BY 1) a ON a.a3 = k.a3
LEFT JOIN (SELECT x.a3, count(*) n, count(*) FILTER (WHERE o2.is_deposit) dep FROM {oc} x JOIN core.occurrences o2 ON o2.occurrence_id = x.id GROUP BY 1) o ON o.a3 = k.a3
LEFT JOIN (SELECT a3, count(*) n FROM {dc} GROUP BY 1) h ON h.a3 = k.a3
LEFT JOIN dc_docs dd ON dd.a3 = k.a3
LEFT JOIN (SELECT a3, string_agg(source_system || ' ' || n, ', ' ORDER BY n DESC) list FROM
             (SELECT x.a3, sm.source_system, count(*) n FROM {sc} x JOIN geochem.samples sm ON sm.sample_id = x.id GROUP BY 1, 2) z GROUP BY 1) src ON src.a3 = k.a3""")
log("coverage rows", c.rowcount)
g.commit()
c.execute("SELECT sum(samples), sum(analyses), sum(occurrences), sum(drill_holes) FROM core.country_coverage"); log("totals", c.fetchone())
c.execute("SELECT name, samples, analyses, occurrences, deposits, drill_holes, documents FROM core.country_coverage ORDER BY samples DESC LIMIT 12")
for r in c.fetchall(): log(r)
