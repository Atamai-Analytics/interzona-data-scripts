"""Adds the deposits from the China synthesis (library doc 450) that are not yet in core.occurrences: Gangdese, Yulong and Sanjiang belt
deposits with the coordinates, ore tonnage and grades as reported in the literature behind that synthesis.

Provenance is weak (an AI-assisted synthesis of GeoScienceWorld papers; citation markers lost), so: positions are kept as published
(position_accuracy NULL, unchecked), tonnage and grade go ONLY into comments (not resource tables), status UNKNOWN, and each record says so.
Existing occurrences within 5 km with a matching name are left alone (10 of the 23 deposits already exist from the USGS China load / MRDS).

Usage: python load_china_deposits_doc450.py [--dry]
"""
import re, sys, difflib, psycopg2

DRY = "--dry" in sys.argv
TAG = "migration_doc450_china_deposits_20261111"
ENV = {}
for line in open(r"C:\Users\dean\claude_lithosurfer\lithosurfer-work\.env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v.strip().strip('"')

SRC = ("Literature compiled in library doc 450 (Internal summary - Mineral deposits of China; AI-assisted synthesis of GeoScienceWorld "
       "papers, see its reference list). Position and figures as reported there, NOT checked; not a code-compliant resource.")
# name, lat, lon, belt, style, commodities (first = primary), reported figures
D = [
    ("Tinggong", 29.5892, 90.0478, "Gangdese belt, southern Tibet", "Porphyry Cu-Mo", ["Copper", "Molybdenum"], "ore 412 Mt at 0.362% Cu"),
    ("Zhunuo", 29.6564, 87.4745, "Gangdese belt, southern Tibet", "Porphyry Cu-Mo", ["Copper", "Molybdenum"], "ore 403 Mt at 0.57% Cu"),
    ("Gangjiang", 29.5911, 89.9413, "Gangdese belt, southern Tibet", "Porphyry Cu-Mo", ["Copper", "Molybdenum"], "ore 365 Mt at 0.28% Cu"),
    ("Nanmu", 29.5256, 90.8094, "Gangdese belt, southern Tibet", "Porphyry Cu-Mo", ["Copper", "Molybdenum"], "ore 250 Mt at 0.20% Cu"),
    ("Tangbula", 29.9167, 93.0667, "Gangdese belt, southern Tibet", "Porphyry Mo-Cu", ["Molybdenum", "Copper"], "ore 221 Mt (grade not reported)"),
    ("Chongjiang", 29.6167, 89.9744, "Gangdese belt, southern Tibet", "Porphyry Cu-Mo-Au", ["Copper", "Molybdenum", "Gold"], "ore 45 Mt at 0.40% Cu"),
    ("Jiru", 29.6561, 88.8883, "Gangdese belt, southern Tibet", "Porphyry Cu", ["Copper"], "ore 42 Mt at 0.43% Cu"),
    ("Bairong", 29.6139, 89.9265, "Gangdese belt, southern Tibet", "Porphyry Cu", ["Copper"], "ore 35 Mt at 0.49% Cu"),
    ("Zhanaga", 31.2161, 97.7853, "Yulong porphyry Cu belt, eastern Tibet (Eocene, ~40 Ma)", "Porphyry Cu-Mo", ["Copper", "Molybdenum"], "no tonnage or grade reported"),
    ("Narigongma", 33.5308, 94.7856, "Yulong porphyry Cu belt, Qinghai", "Porphyry Cu-Mo", ["Copper", "Molybdenum"], "no tonnage or grade reported"),
    ("Yao'an", 25.3787, 101.2511, "Sanjiang / West Yunnan porphyry-skarn belt (~32-37 Ma)", "Porphyry-related Au (monzonite / quartz monzonite porphyry)", ["Gold"], "2.2 Mt at 4.5 g/t Au"),
    ("Xifanping", 25.1545, 100.2870, "Sanjiang / West Yunnan porphyry-skarn belt (~32-37 Ma)", "Porphyry Cu-Au (quartz monzonite porphyry)", ["Copper", "Gold"], "Cu 0.33-0.49%, Au 0.1 g/t (tonnage not reported)"),
    ("Tongchang", 22.94, 103.16, "Sanjiang / West Yunnan porphyry-skarn belt (~32-37 Ma)", "Porphyry Cu-Mo (lamprophyres in deposit)", ["Copper", "Molybdenum"], "Cu 0.008 Mt at 1.24%, Mo 0.017 Mt at 0.218% (contained metal as reported)"),
]

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s", (TAG,))
c.execute("SELECT source_id FROM core.external_ids WHERE source_system = 'LIBRARY_DOC_450'"); DONE = {x[0] for x in c.fetchall()}
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code = 'CN'"); CN = c.fetchone()[0]
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
SYM = {"Copper": "cu", "Molybdenum": "mo", "Gold": "au"}  # core.commodities names metals by symbol
norm = lambda x: re.sub(r"[^a-z0-9]", "", re.sub(r"\b(mine|deposit|copper|cu|mo|porphyry|project)\b", "", (x or "").lower()))

# Exists under another name: USGS China exploration project "Nimu" lists "Bairong" as an other name (1.5 km apart).
ATTACH = {"Bairong": 1208025}
added = 0
for name, lat, lon, belt, style, comms, figs in D:
    if name in DONE:
        print(f"{name:12} already loaded"); continue
    c.execute("""SELECT occurrence_id, name, round(ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)) FROM core.occurrences
                 WHERE is_active AND created_by <> %s AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 5000) ORDER BY 3""",
              (lon, lat, TAG, lon, lat))  # own records excluded: Gangjiang and Chongjiang are 3 km apart with similar names
    near = c.fetchall()
    dup = [n for n in near if difflib.SequenceMatcher(None, norm(name), norm(n[1])).ratio() > 0.7 or norm(name) in norm(n[1])]
    if name in ATTACH:  # exists under another name (its comments list this name as an other name): add the reported figures there
        oid = ATTACH[name]
        print(f"{name:12} -> ATTACH to existing occurrence {oid}")
        if not DRY:
            c.execute("UPDATE core.occurrences SET comments = comments || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s AND comments NOT LIKE %s",
                      (f" | Literature (library doc 450, as {name}): {style}; reported {figs}; not checked.", TAG, oid, "%library doc 450%"))
            c.execute("""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by)
                         VALUES ('OCCURRENCE', %s, 'LIBRARY_DOC_450', %s, 'LOW', %s)""", (oid, name, TAG))
        continue
    print(f"{name:12} nearby: {[(n[1][:30], int(n[2])) for n in near][:3]}  -> {'SKIP (exists)' if dup else 'ADD'}")
    if dup or DRY:
        continue
    comment = f"{belt}. {style}. Reported: {figs}. {SRC}"
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, mineralization_style, geological_district,
                 comments, is_active, created_by, created_date) VALUES (%s,true,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),'UNKNOWN','UNKNOWN',%s,%s,%s,true,%s,now())
                 RETURNING occurrence_id""", (name, CN, lon, lat, style, belt, comment, TAG))
    oid = c.fetchone()[0]
    for i, cm in enumerate(comms):
        c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                  (oid, GN[SYM[cm]], "PRIMARY" if i == 0 else "SECONDARY", TAG))
    c.execute("""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by)
                 VALUES ('OCCURRENCE', %s, 'LIBRARY_DOC_450', %s, 'LOW', %s)""", (oid, name, TAG))
    added += 1
if DRY:
    g.rollback(); print("DRY RUN - nothing written")
else:
    g.commit()
    c.execute("SELECT name, country_name, commodities, status FROM core.occurrences WHERE created_by = %s ORDER BY name", (TAG,))
    for r in c.fetchall(): print(r)
    print("added", added)
