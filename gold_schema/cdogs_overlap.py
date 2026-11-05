"""Find CDoGS samples that are already in gold through another source (same broad medium within 50 m of a loaded sample from the Saskatchewan
GeoAtlas, Québec SIGÉOM, USGS NGDB or the GA deposit-geochemistry set). Read-only: temp tables only.
Output: <dir>/cdogs_overlap.csv (field_key, matched source_system) - the loader skips these samples.
Usage: python cdogs_overlap.py D:/CriticalMineralsDB/Canada/NRCan_CDoGS
"""
import io, os, sys, time
import pandas as pd, psycopg2
from cdogs_types import KEEP, GOLD_MEDIUM, FEDERAL_ORGS

root = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


d = pd.read_csv(os.path.join(root, "cdogs_values.csv"), dtype=str, keep_default_na=False, usecols=["sample_type", "lab_sample_type", "site_key", "field_key", "lat", "lon"])
d = d[d.lab_sample_type.isin(["", "0", "1"]) & d.sample_type.isin(KEEP) & (d.lat != "")].drop_duplicates("field_key")
d = d[d.site_key.str.split(":").str[0].astype(int).isin(FEDERAL_ORGS)]
d["medium"] = d.sample_type.map(lambda t: KEEP[t][1])
log("federal kept-type samples", len(d))
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60)
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("CREATE TEMP TABLE cd (fk text, medium text, lat float8, lon float8)")
buf = io.StringIO(); d[["field_key", "medium", "lat", "lon"]].to_csv(buf, index=False, header=False); buf.seek(0)
c.copy_expert("COPY cd FROM STDIN WITH (FORMAT csv)", buf)
c.execute("ALTER TABLE cd ADD COLUMN g geometry; UPDATE cd SET g = ST_SetSRID(ST_MakePoint(lon, lat), 4326)")
med = "CASE t.sample_type_code " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in GOLD_MEDIUM.items()) + " END"
c.execute(f"""CREATE TEMP TABLE ex AS SELECT s.source_system, s.geom AS g, {med} AS medium FROM geochem.samples s JOIN geochem.sample_types t USING (sample_type_id)
              WHERE s.source_system IN ('CANADA_SK_SGS', 'CANADA_QC_SIGEOM_SED', 'CANADA_QC_SIGEOM', 'USA_USGS_NGDB', 'GLOBAL_DEPOSIT_GEOCHEM_GA')
                AND s.lat > 41 AND s.lon < -52""")
c.execute("CREATE INDEX ON ex USING gist (g)")
c.execute("ANALYZE cd"); c.execute("ANALYZE ex")
log("staged; matching")
# geometry index with a degree box (~0.001 deg), then the exact 50 m test on geography
c.execute("""SELECT cd.fk, m.source_system FROM cd CROSS JOIN LATERAL (
               SELECT e.source_system FROM ex e WHERE e.medium = cd.medium AND e.g && ST_Expand(cd.g, 0.001)
                 AND ST_DWithin(e.g::geography, cd.g::geography, 50) LIMIT 1) m""")
rows = c.fetchall()
g.rollback()
out = pd.DataFrame(rows, columns=["field_key", "source_system"])
out.to_csv(os.path.join(root, "cdogs_overlap.csv"), index=False)
log("matched", len(out), out.source_system.value_counts().to_dict())
