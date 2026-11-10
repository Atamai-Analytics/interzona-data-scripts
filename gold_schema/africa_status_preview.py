"""Preview: occurrences ATTACHED by the USGS Africa load (2026-11-10) whose current status differs from the USGS status.
Facilities: status from core.facility_capacity.facility_status (Minerals Yearbook 2018 / Zambia 2017).
Exploration: stage as last verified 2004-2018 (from the gdb). Read-only."""
import os, collections
import psycopg2, pyogrio

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm",
                     user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='core' AND table_name='occurrences' ORDER BY ordinal_position""")
print("occurrences columns:", [r[0] for r in c.fetchall()])
c.execute("SELECT status, count(*) FROM core.occurrences GROUP BY 1 ORDER BY 2 DESC")
print("status values:", c.fetchall())

c.execute("""SELECT o.occurrence_id, o.name, o.status, o.created_by, e.source_id,
                    (SELECT string_agg(DISTINCT fc.facility_status || ' (' || fc.data_year || ')', '; ') FROM core.facility_capacity fc
                      WHERE fc.occurrence_id = o.occurrence_id AND fc.source_system = 'USGS_AFRICA_GIS') fstat,
                    j.name
             FROM core.external_ids e JOIN core.occurrences o ON o.occurrence_id = e.entity_id
             LEFT JOIN core.jurisdictions j ON j.jurisdiction_id = o.jurisdiction_id
             WHERE e.source_system = 'USGS_AFRICA_GIS' AND e.entity_type = 'OCCURRENCE' AND e.match_confidence = 'HIGH'
               AND o.created_by <> 'migration_usgs_africa_20261110'""")
rows = c.fetchall()
print("attached rows:", len(rows))
fac = [r for r in rows if r[4].startswith("fac:")]
print("attached facilities:", len(fac))
print("facility: (current status, usgs status) counts")
cnt = collections.Counter((r[2], r[5]) for r in fac)
for k, v in cnt.most_common(40): print(f"  {v:5} {k}")
print("\nsample: Zambia/DRC attached facilities")
for r in fac:
    if r[6] in ("Zambia", "Democratic Republic of the Congo", "Congo, The Democratic Republic of the") or (r[6] or "").startswith("Congo"):
        print("  ", r[0], r[1][:40], "|", r[2], "|", r[5], "|", r[3], "|", r[6])

x = pyogrio.read_dataframe("D:/CriticalMineralsDB/Africa/download_20261110/gdb/Africa_GIS.gdb", layer="AFR_Mineral_Exploration", read_geometry=False)
st = {("exp:" + u): (s, y) for u, s, y in zip(x.FeatureUID, x.LocOpStat, x.DsgAttr11)}
exp = [r for r in rows if r[4].startswith("exp:")]
print("\nattached exploration:", len(exp))
cnt = collections.Counter((r[2], st.get(r[4], (None,))[0]) for r in exp)
for k, v in cnt.most_common(30): print(f"  {v:5} {k}")
dep = [r for r in rows if r[4].startswith("dep:")]
print("\nattached deposits (no status in source):", len(dep))
