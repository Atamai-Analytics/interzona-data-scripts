"""Curated lithium deposits (2026-11-08) -> core.occurrences, from curated_lithium_20261108_geocoded.csv.

21 lithium deposits named in library doc 444 that no loaded inventory holds (Africa, Ukraine, Americas, UK, and company-reported Brazilian
mines while SGB's own occurrence data awaits licence permission). Facts (name, status, operator, commodity) compiled by Interzona from the
cited public source on each row; positions are APPROXIMATE (locality geocoded with OpenStreetMap Nominatim plus the published offset),
position_accuracy AREA_CENTROID. external_ids source 'INTERZONA_CURATED_LITHIUM'. Skips a row if an active occurrence with the same
normalised name lies within 20 km.
Usage: python load_curated_lithium.py [--dry]
"""
import csv, os, re, sys, collections
import psycopg2

DRY = "--dry" in sys.argv
TAG = "claude_li_curated_20261108"
SRC = "INTERZONA_CURATED_LITHIUM"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
rows = list(csv.DictReader(open(os.path.join(HERE, "curated_lithium_20261108_geocoded.csv"), encoding="utf-8")))
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,)); assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT commodity_symbol, commodity_id FROM core.commodities WHERE commodity_symbol IS NOT NULL"); COM = dict(c.fetchall())
norm = lambda n: re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", n.lower()))
loaded = []
for r in rows:
    c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = %s", (r["country"],))
    j = c.fetchone(); assert j, r["country"]
    c.execute("""SELECT occurrence_id, name FROM core.occurrences WHERE is_active AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 20000)""",
              (float(r["lon"]), float(r["lat"])))
    dup = [x for x in c.fetchall() if norm(x[1]) and norm(x[1]) == norm(r["name"])]
    if dup: print("SKIP duplicate", r["name"], dup); continue
    comments = "; ".join(p for p in [
        f"Reference: {r['source_url']} (dated {r['source_date']})",
        f"Operator / owner: {r['operator']}" if r["operator"] else None, f"Status note: {r['status_note']}",
        f"APPROXIMATE position: locality '{r['locality_query']}'" + (f" plus {r['offset_km']} km at {r['bearing_deg']} deg" if float(r['offset_km'] or 0) else "")
        + " geocoded with OpenStreetMap Nominatim; not the mine site",
        "Compiled by Interzona from that public source (curated lithium table, 8 Nov 2026)"] if p)
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, comments, is_active, created_by, created_date, position_accuracy)
                 VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,true,%s,now(),'AREA_CENTROID') RETURNING occurrence_id""",
              (r["name"], r["is_deposit"] == "true", j[0], float(r["lon"]), float(r["lat"]), r["status"], comments, TAG))
    oid = c.fetchone()[0]
    c.execute("INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES ('OCCURRENCE',%s,%s,%s,%s)",
              (oid, SRC, norm(r["name"]), TAG))
    for k, sym in enumerate(r["commodities"].split(";")):
        c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                  (oid, COM[sym], "PRIMARY" if k == 0 else "SECONDARY", TAG))
    loaded.append((oid, r["name"], r["country"], r["status"]))
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,NULL,false,%s,true,%s,%s,%s,'2026-11-08',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Atamai Analytics (Interzona)", "Curated lithium deposits compiled from cited public sources, 8 Nov 2026",
           "Facts compiled by Interzona; each row cites its public source", "Cite the source named in each row's comments.",
           "Own compilation of facts (name, status, operator, commodity) from cited public sources; positions geocoded from OpenStreetMap Nominatim.",
           "Positions APPROXIMATE (locality level, about 5-15 km; several deposits share one town point). Status as of the cited source date.",
           "lithosurfer-work/gold_schema/curated_lithium_20261108.csv", TAG))
for x in loaded: print(x)
print("loaded", len(loaded))
c.execute("SELECT name, commodities, country_name FROM core.occurrences WHERE created_by = %s ORDER BY name LIMIT 3", (TAG,)); print(c.fetchall())
if DRY: g.rollback(); print("DRY RUN - rolled back")
else: g.commit(); print("COMMITTED")
