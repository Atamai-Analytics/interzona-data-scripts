"""USGS Africa GIS compilation (DOI 10.5066/P97EQWXP) - overlap check vs core.occurrences, no writes (2026-11-10).
For each point in the three mineral layers: nearest active occurrence within 5 km and whether the names match."""
import os, sys, re, collections, warnings, difflib
import pyogrio, psycopg2
warnings.filterwarnings("ignore")
GDB = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__)); ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l: k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("mine", "").replace("deposit", ""))
for lay in ("AFR_Mineral_Facilities", "AFR_Mineral_Deposits", "AFR_Mineral_Exploration"):
    df = pyogrio.read_dataframe(GDB, layer=lay, read_geometry=False)
    if lay == "AFR_Mineral_Facilities": df = df[df.DsgAttr01 != "Fuel"]
    st = collections.Counter(); bysrc = collections.Counter()
    for r in df.itertuples():
        c.execute("""SELECT name, created_by, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                     WHERE is_active AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 5000) ORDER BY d LIMIT 5""",
                  (r.Longitude, r.Latitude, r.Longitude, r.Latitude))
        near = c.fetchall()
        nm = norm(r.FeatureNam)
        named = [x for x in near if nm and (difflib.SequenceMatcher(None, nm, norm(x[0])).ratio() > 0.8 or (len(nm) > 4 and nm in norm(x[0])))]
        if named: st["name match <5 km"] += 1; bysrc[named[0][1]] += 1
        elif near: st["something <5 km, other name"] += 1
        else: st["nothing <5 km"] += 1
    print(lay, len(df), dict(st), "| matched sources", bysrc.most_common(6), flush=True)
