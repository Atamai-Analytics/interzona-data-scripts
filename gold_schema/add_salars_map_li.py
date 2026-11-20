"""Lithium salars from the 'Main Lithium Salars' map (library doc 466, author not stated, read 20 Nov 2026) that the occurrence data lacked.

1. Five Chilean salars already in core.occurrences from USGS MRDS (salt/boron only) get lithium added (role SECONDARY, so the MRDS
   primary commodity is unchanged) and a comment: Salar De Punta Negra 576204 (Black Giant project), Salar De La Isla 576244,
   Salar De Aguilar 576206, Salar De Infieles 576208, Salar De Maricunga 576213. Map positions match the MRDS points within ~5 km.
2. Laguna Verde (Chile, map -26.88, -68.47) is not in the data: new occurrence, type Lacustrine brine lithium, status EXPLORATION
   (map: 'project'), position_accuracy AREA_CENTROID (salar centre from the map, two decimals).
Not added: 'Grande de Atacama' (-26.00, -68.70; name not matched to a known salar with confidence) and Hammerdown (gold, Canada map).
Tag claude_salars_map_20261120. Undo: python -P add_salars_map_li.py --undo
"""
import os, sys
import psycopg2

TAG = "claude_salars_map_20261120"
NOTE = "Lithium recorded 2026-11-20 from the 'Main Lithium Salars' map (Interzona library doc 466; author not stated; map status: project)."
EXISTING = {576204: "Salar De Punta Negra", 576244: "Salar De La Isla", 576206: "Salar De Aguilar", 576208: "Salar De Infieles", 576213: "Salar De Maricunga"}
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()

if "--undo" in sys.argv:
    c.execute("DELETE FROM core.occurrence_commodities WHERE created_by = %s", (TAG,)); print("commodity rows removed", c.rowcount)
    c.execute("UPDATE core.occurrences SET comments = nullif(trim(replace(coalesce(comments, ''), %s, '')), ''), modified_by = %s, modified_date = now() WHERE occurrence_id = ANY(%s)", (" " + NOTE, TAG + "_undo", list(EXISTING)))
    c.execute("UPDATE core.occurrences SET comments = nullif(trim(replace(coalesce(comments, ''), %s, '')), '') WHERE occurrence_id = ANY(%s)", (NOTE, list(EXISTING)))
    c.execute("DELETE FROM core.occurrences WHERE created_by = %s", (TAG,)); print("new occurrences removed", c.rowcount)
    g.commit(); sys.exit("UNDONE")

c.execute("SELECT commodity_id FROM core.commodities WHERE commodity_name = 'Li'"); LI = c.fetchone()[0]
for oid, name in EXISTING.items():
    c.execute("SELECT name, round(lat::numeric, 2), round(lon::numeric, 2), commodities, is_active FROM core.occurrences WHERE occurrence_id = %s", (oid,))
    r = c.fetchone()
    assert r and r[0] == name and r[4], f"unexpected row {oid}: {r}"
    if "Li" in (r[3] or []): print("already has Li:", name); continue
    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s, %s, 'SECONDARY', true, %s)", (oid, LI, TAG))
    c.execute("UPDATE core.occurrences SET comments = trim(coalesce(comments, '') || ' ' || %s), modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (NOTE, TAG, oid))
    print("Li added:", name, r[1], r[2])

# new: Laguna Verde (skip if any active occurrence of that name lies within 20 km)
c.execute("""SELECT occurrence_id, name FROM core.occurrences WHERE is_active AND name ILIKE '%%laguna verde%%'
             AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(-68.47, -26.88), 4326)::geography, 20000)""")
dup = c.fetchall()
if dup: print("Laguna Verde already present:", dup)
else:
    c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code3 = 'CHL'"); JUR = c.fetchone()[0]
    c.execute("SELECT occurrence_type_id FROM core.occurrence_types WHERE occurrence_type_id = 628"); TYPE = c.fetchone()[0]  # Lacustrine brine lithium (as on Salar de Pastos Grandes)
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, occurrence_type_id, jurisdiction_id, geom, status, comments, is_active, created_by, created_date, position_accuracy)
                 VALUES ('Laguna Verde (salar)', false, %s, %s, ST_SetSRID(ST_MakePoint(-68.47, -26.88), 4326), 'EXPLORATION', %s, true, %s, now(), 'AREA_CENTROID') RETURNING occurrence_id""",
              (TYPE, JUR, "Salt lake (salar) in the Atacama region of Chile, shown as a lithium project on the 'Main Lithium Salars' map (Interzona library doc 466; author not stated). "
               "Position is the approximate salar centre from that map (two decimals); status as drawn on the map, not checked against company filings.", TAG))
    nid = c.fetchone()[0]
    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s, %s, 'PRIMARY', true, %s)", (nid, LI, TAG))
    print("new occurrence Laguna Verde", nid)
if "--dry" in sys.argv: g.rollback(); sys.exit("DRY - rolled back")
g.commit(); print("COMMITTED")
