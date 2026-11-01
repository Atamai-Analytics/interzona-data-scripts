"""Load the 16 Finnish deposits of Table 1 (Jonsson et al., Critical metals and minerals in the Nordic countries of Europe; library doc 74) into
core.occurrences / core.occurrence_commodities / core.resource_estimates, add two newer cobalt figures from the Nordic Supply Potential report (doc 75),
then link the FINLAND_GTK_ROCK samples (and their results / wide-table rows) to the nearest of these deposits within 5 km.
Usage: python load_fi_deposits.py [--dry]  (--dry = everything then ROLLBACK)
"""
import os, sys, re, time
import psycopg2
from collections import OrderedDict
import nordic1_table1 as T1

DRY = "--dry" in sys.argv
TAG = "migration_fi_deposits_20261011"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

COMM = {"Co": 1105, "Ni": 1107, "Cu": 1106, "Zn": 1109, "PGE": 1126, "Graphite": 994, "Li": 1089, "Nb": 1092, "P": 1152, "REE": 1061, "Ta": 1099, "Ti": 1113, "V": 1114, "Fe": 1111}
# Table 1 commodity label -> (commodity key, unit text for contained metal)
T1COMM = {"Cobalt": ("Co", "t Co"), "Graphite": ("Graphite", "t graphite"), "Lithium": ("Li", "t Li"), "Niobium": ("Nb", "t Nb"), "PGM": ("PGE", "t PGM (as reported)"),
          "REE": ("REE", "t REE (as reported)"), "Tantalum": ("Ta", "t Ta"), "Titanium": ("Ti", "t Ti"), "Vanadium": ("V", "t V")}
SIZE = {"Small": "SMALL", "Medium": "MEDIUM", "Large": "LARGE", "Very large": "GIANT"}
STATUS = {"Active mine": "PRODUCER", "Closed mine": "PAST_PRODUCER", "Unexploited": "UNKNOWN"}

# per deposit: (name in Table 1, display name, occurrence_type_id or None, [(commodity key, role)], extra comment, size override)
DEP = OrderedDict([
    ("Talvivaara", ("Talvivaara (Terrafame)", 632, [("Ni", "PRIMARY"), ("Co", "SECONDARY"), ("Zn", "SECONDARY"), ("Cu", "SECONDARY")],
                    "Black schist-hosted Ni-Zn-Cu-Co deposit in eastern Finland (the doc 74 text describes Talvivaara-type black schist-hosted Ni-Zn-Cu-Co deposits and says cobalt is produced at the Terrafame (Talvivaara) mine). Table 1 lists only cobalt; the Ni, Zn and Cu commodity links come from that text and carry no resource figures here.", None)),
    ("Kevitsa", ("Kevitsa", 758, [("Ni", "PRIMARY"), ("Cu", "PRIMARY"), ("Co", "SECONDARY"), ("PGE", "SECONDARY")],
                 "Orthomagmatic Ni-Cu(-Co-PGM) deposit in the c. 2.06 Ga Kevitsa intrusion, central Lapland (doc 74 text). Table 1 lists only cobalt; the Ni, Cu and PGE links come from the text and Table 1's deposit-type string and carry no resource figures here.", None)),
    ("Sakatti", ("Sakatti", 758, [("Cu", "PRIMARY"), ("Ni", "PRIMARY"), ("Co", "SECONDARY"), ("PGE", "SECONDARY")],
                 "Orthomagmatic Ni-Cu-Co-PGE deposit (type string in Table 1). Table 1 lists only cobalt; the Cu, Ni and PGE links are implied by the type string and carry no resource figures here.", None)),
    ("Aitolampi", ("Aitolampi", 669, [("Graphite", "PRIMARY")], "Metasediment-hosted graphite (Table 1); the occurrence type is the closest gold-layer type (Metamorphic graphite).", None)),
    ("Rapasaaret", ("Rapasaaret", 744, [("Li", "PRIMARY")], "Granitic pegmatite-hosted lithium (Table 1 type 'Orthomagmatic, granitic pegmatite'); occurrence type LCT pegmatite is the closest gold-layer type.", None)),
    ("Sokli", ("Sokli", 748, [("Nb", "PRIMARY"), ("P", "SECONDARY")],
               "Carbonatite (Devonian, c. 365 Ma). The doc 74 text says Sokli contains a very large phosphate resource and has the potential to become a significant REE, Ta, Nb and Zr resource; only niobium is listed in Table 1, so phosphorus is linked as a secondary commodity without figures.", None)),
    ("Ahmavaara", ("Ahmavaara", 755, [("PGE", "PRIMARY")], "Orthomagmatic Ni-Cu-Co-PGE (Table 1 type string); the 187 t PGM figure is the total PGM metal in the listed resource.", None)),
    ("Siika-Kämä reef", ("Siika-Kämä reef", 755, [("PGE", "PRIMARY")], "Orthomagmatic Ni-Cu-Co-PGE reef (Table 1 type string).", None)),
    ("Kontioaho", ("Kontioaho", 749, [("REE", "PRIMARY")], "Orthomagmatic peralkaline/syenitic REE (Table 1).", None)),
    ("Rosendal", ("Rosendal", None, [("Ta", "PRIMARY")], "Granitic pegmatite tantalum (Table 1 type 'Orthomagmatic granitic pegmatite'); no gold-layer occurrence type assigned because LCT vs NYF is not stated.", None)),
    ("Lumikangas", ("Lumikangas", 757, [("Ti", "PRIMARY"), ("V", "SECONDARY"), ("Fe", "SECONDARY")], "Orthomagmatic Fe-Ti-V (Table 1 type); Table 1 lists only titanium, V and Fe links are implied by the type string and carry no figures here.", None)),
    ("Perämaa", ("Perämaa", 757, [("Ti", "PRIMARY"), ("V", "SECONDARY"), ("Fe", "SECONDARY")], "Orthomagmatic Fe-Ti-V (Table 1 type); Table 1 lists only titanium, V and Fe links are implied by the type string and carry no figures here.", None)),
    ("Koivusaarenneva", ("Koivusaarenneva", 757, [("Ti", "PRIMARY"), ("V", "PRIMARY"), ("Fe", "SECONDARY")], "Orthomagmatic Fe-Ti-V; Table 1 lists both titanium and vanadium on the same 62.15 Mt (the metal figures describe the same ore and must not be added).", None)),
    ("Mustavaara", ("Mustavaara", 757, [("V", "PRIMARY"), ("Ti", "PRIMARY"), ("Fe", "SECONDARY")], "Orthomagmatic Fe-Ti-V, closed mine; Table 1 lists Ti (Medium) and V (Large) on the same 145.90 Mt (the metal figures describe the same ore and must not be added); size category taken as the larger of the two.", "LARGE")),
    ("Koitelainen UC", ("Koitelainen UC", 757, [("V", "PRIMARY"), ("Ti", "SECONDARY"), ("Fe", "SECONDARY")], "Orthomagmatic Fe-Ti-V (name as printed in Table 1, 'UC' not explained); Table 1 lists only vanadium.", None)),
    ("Otanmäki", ("Otanmäki", 757, [("V", "PRIMARY"), ("Ti", "SECONDARY"), ("Fe", "SECONDARY")], "Orthomagmatic Fe-Ti-V; Table 1 lists only vanadium and gives status Unexploited (the table does not describe any past mining).", None)),
])

rows = [d for d in T1.parse() if d["country"] == "Finland"]
by = OrderedDict()
for d in rows:
    by.setdefault(d["deposit"].replace("–", "-"), []).append(d)
assert set(by) == set(DEP), (set(by) ^ set(DEP))
assert len(rows) == 18 and len(by) == 16, (len(rows), len(by))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT occurrence_type_id, type_name FROM core.occurrence_types")
TYPENAME = dict(c.fetchall())

new_ids = {}
for key, (display, typ, comms, extra, size_override) in DEP.items():
    items = by[key]
    d0 = items[0]
    status = STATUS[d0["status"]]
    size = size_override or max((SIZE[i["size"]] for i in items), key=["SMALL", "MEDIUM", "LARGE", "GIANT"].index)
    lines = []
    for i in items:
        cl = T1COMM[i["commodity"]]
        lines.append(f"{i['commodity']}: resource {i['resource']} Mt, total {i['tonnage']} {cl[1]}, size category {i['size']}")
    comment = (f"{display}, Finland. Source: Table 1 of Jonsson et al., Critical metals and minerals in the Nordic countries of Europe (library doc 74), a regional compilation from national "
               f"databases and Eilu et al. (2021). Table 1 gives: age {d0['age']}; type {d0['type']}; latitude {d0['lat']}, longitude {d0['lon']} (2 decimals, deposit-level, about +/-1 km); "
               f"status {d0['status']}; " + "; ".join(lines) + ". " + extra +
               " The resource figures are unclassified compilation numbers (category, reporting standard, grade and effective date are not stated), commodity figures that describe the same ore must not be added, "
               "and the 2-decimal coordinates are as printed. Load tag migration_fi_deposits_20261011.")
    c.execute("""INSERT INTO core.occurrences (name, is_deposit, occurrence_type_id, occurrence_type_name, jurisdiction_id, geom, status, size_category, comments, is_active, created_by, created_date)
                 VALUES (%s, true, %s, %s, 828, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, true, %s, now()) RETURNING occurrence_id""",
              (display, typ, TYPENAME.get(typ) if typ else None, float(d0["lon"]), float(d0["lat"]), status, size, comment, TAG))
    oid = c.fetchone()[0]
    new_ids[key] = oid
    for ck, role in comms:
        c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s, %s, %s, true, %s)", (oid, COMM[ck], role, TAG))
    for i in items:
        ck, unit = T1COMM[i["commodity"]]
        c.execute("""INSERT INTO core.resource_estimates (occurrence_id, commodity_id, classification, reporting_standard, tonnage, tonnage_unit, contained_metal, contained_metal_unit, source_document_id, is_active, created_by)
                     VALUES (%s, %s, 'Resource, category not stated', 'Not stated', %s, 'Mt', %s, %s, 74, true, %s)""",
                  (oid, COMM[ck], float(i["resource"].split()[0]), float(i["tonnage"].replace(" ", "")), unit, TAG))
log("deposits inserted", len(new_ids))

# newer cobalt figures from the Nordic Supply Potential report (doc 75, Table of commodity summaries, cobalt)
c.execute("""INSERT INTO core.resource_estimates (occurrence_id, commodity_id, classification, reporting_standard, effective_date, tonnage, tonnage_unit, grade, grade_unit, source_document_id, is_active, created_by)
             VALUES (%s, 1105, 'Resource, category not stated', 'Not stated', '2020-01-01', 1458, 'Mt', 0.019, '%% Co', 75, true, %s)""", (new_ids["Talvivaara"], TAG))
c.execute("""INSERT INTO core.resource_estimates (occurrence_id, commodity_id, classification, reporting_standard, effective_date, tonnage, tonnage_unit, contained_metal, contained_metal_unit, source_document_id, is_active, created_by)
             VALUES (%s, 1105, 'Resources+reserves combined', 'Not stated', '2025-12-31', 274.6, 'Mt', 28718, 't Co', 75, true, %s)""", (new_ids["Kevitsa"], TAG))
c.execute("""UPDATE core.occurrences SET comments = comments || E'\\nNEWER FIGURE (doc 75, Nordic Supply Potential report, cobalt summary): mineral resources at Terrafame 1,458 Mt at 0.019%% Co as of 1 January 2020 (loaded as a second resource row; Table 1 gives 1,499 Mt and 277,000 t Co).' WHERE occurrence_id = %s""", (new_ids["Talvivaara"],))
c.execute("""UPDATE core.occurrences SET comments = comments || E'\\nNEWER FIGURE (doc 75, Nordic Supply Potential report, cobalt summary): Kevitsa combined resources and reserves 274.6 Mt containing about 28,718 t Co as of 31 December 2025 (loaded as a second resource row; Table 1 gives 307 Mt and 30,750 t Co).' WHERE occurrence_id = %s""", (new_ids["Kevitsa"],))

# link GTK rock samples to the nearest of the new deposits within 5 km
c.execute("""CREATE TEMP TABLE _fi_match ON COMMIT DROP AS
SELECT DISTINCT ON (s.sample_id) s.sample_id, o.occurrence_id, ST_Distance(s.geog, o.geog) AS dist_m
FROM geochem.samples s JOIN core.occurrences o ON o.created_by = %s AND ST_DWithin(s.geog, o.geog, 5000)
WHERE s.source_system = 'FINLAND_GTK_ROCK' ORDER BY s.sample_id, dist_m""", (TAG,))
c.execute("SELECT count(*), count(DISTINCT occurrence_id) FROM _fi_match"); n_link, n_dep = c.fetchone()
log("GTK rock samples within 5 km of a loaded deposit", n_link, "deposits hit", n_dep)
c.execute("UPDATE geochem.samples s SET occurrence_id = m.occurrence_id FROM _fi_match m WHERE s.sample_id = m.sample_id AND s.occurrence_id IS NULL")
log("samples linked", c.rowcount)
c.execute("UPDATE geochem.analytical_results r SET occurrence_id = m.occurrence_id FROM _fi_match m WHERE r.sample_id = m.sample_id AND r.source_system = 'FINLAND_GTK_ROCK'")
log("results linked", c.rowcount)
c.execute("UPDATE geochem.sample_chemistry_wide w SET occurrence_id = m.occurrence_id FROM _fi_match m WHERE w.sample_id = m.sample_id")
log("wide rows linked", c.rowcount)
c.execute("""SELECT o.name, count(*) FROM _fi_match m JOIN core.occurrences o ON o.occurrence_id = m.occurrence_id GROUP BY 1 ORDER BY 2 DESC""")
log("links per deposit", c.fetchall())

c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)); assert c.fetchone()[0] == 16
c.execute("SELECT count(*) FROM core.occurrence_commodities WHERE created_by = %s", (TAG,)); log("commodity links", c.fetchone()[0])
c.execute("SELECT count(*) FROM core.resource_estimates WHERE created_by = %s", (TAG,)); log("resource rows", c.fetchone()[0])
c.execute("SELECT name, status, size_category, occurrence_type_name, round(lat::numeric,2), round(lon::numeric,2), country_name, commodities FROM core.occurrences WHERE created_by = %s ORDER BY occurrence_id", (TAG,))
for r in c.fetchall(): log("  ", r)
if DRY:
    g.rollback(); log("DRY - rolled back")
else:
    g.commit(); log("COMMITTED")
