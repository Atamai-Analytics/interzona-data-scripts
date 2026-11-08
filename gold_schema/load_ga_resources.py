"""Geoscience Australia OZMIN ore reserves and mineral resources (CC BY 4.0) -> interzona_cm core.resource_estimates.

Source: GA WFS ama:ReservesAndResources, downloaded 2026-11-08 (browser pane) to
D:/CriticalMineralsDB/Australia/download_20261108/ga_ozmin_reserves_resources_20261108.csv (19,835 rows = 12,545 resource statements x
commodity grades, 2,858 deposits, 4,840 deposit zones). Evidence: Documents/Licence_Evidence/GA_OZMIN/EVIDENCE.md.
Rules
  * LATEST statement per deposit zone only (RECORD_DATE max per ENO + ZONE_ENO); older statements are not loaded. Zones whose latest
    statement is ZEROED = 'Y' (GA: resource zeroed, e.g. mined out or withdrawn) are skipped.
  * one row per category with a tonnage or grade: Proven, Probable, Proven+Probable, Measured, Indicated, Measured+Indicated, Inferred,
    Other - per commodity grade. tonnage_unit normalised (Kt/Kton -> kt, Mton -> Mt, ton -> t); grade_unit = '<unit> <commodity code>'.
  * contained_metal CALCULATED here (tonnage x grade) for %, ppm, kg/t (-> t) and g/t (-> koz) when the tonnage is in t/kt/Mt/Gt;
    the comment says so.
  * occurrence_id via core.external_ids source AUSTRALIA_GA_OZMIN (the OZMIN row, or the MINEDEX site it was attached to).
  * new columns (added here if missing, nullable): source_system, zone_name, comments.
Usage: python load_ga_resources.py [--dry]
"""
import csv, os, re, sys, time, collections
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_ga_resources_20261108"
SRC = "AUSTRALIA_GA_OZMIN_RESOURCES"
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = "D:/CriticalMineralsDB/Australia/download_20261108/ga_ozmin_reserves_resources_20261108.csv"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
CODES = {}
src = open(os.path.join(HERE, "load_minedex_occurrences.py"), encoding="utf-8").read()
exec(re.search(r"^CODES = \{.*?\}\n", src, re.S | re.M).group(0))
CODES.update({"U3O8": "U", "Grfl": "Graphite", "Cbl": "Black Coal", "Cbr": "Brown Coal", "MnOre": "Manganese Ore", "MgO": "Magnesia",
              "Sic": "SiO2", "P2O5": "P4O10", "Mns": "Mineral Sand", "Cy": "Clay", "Opl": "Opal",
              "La2O3": "La", "CeO2": "Ce", "Sm2O3": "Sm", "Gd2O3": "Gd", "Er2O3": "Er", "Tm2O3": "Tm", "Yb2O3": "Yb", "Pr6O11": "Pr", "Ho2O3": "Ho",
              "Lu2O3": "Lu", "Sc2O3": "Sc", "Cr2O3": "Cr", "MoS2": "Molybdenite", "Mgs": "MgCO3", "Osh": "Oil Shale", "Feox": "Iron Oxide"})


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def num(s):
    s = (s or "").strip()
    try: return float(s)
    except ValueError: return None


TU = {"Kt": "kt", "Kton": "kt", "Mton": "Mt", "ton": "t", "Kg": "kg"}
TONNES = {"t": 1, "kt": 1e3, "Mt": 1e6, "Gt": 1e9}
CATS = [("Proven", "PROVEN_RESERVES", "PROVEN_GRADE"), ("Probable", "PROBABLE_RESERVES", "PROBABLE_GRADE"),
        ("Proven+Probable", "PROVEN_PROBABLE_RESERVES", "PROVEN_PROBABLE_GRADE"), ("Measured", "MEASURED_RESOURCES", "MEASURED_GRADE"),
        ("Indicated", "INDICATED_RESOURCES", "INDICATED_GRADE"), ("Measured+Indicated", "MEASURED_INDICATED_RESOURCES", "MEASURED_INDICATED_GRADE"),
        ("Inferred", "INFERRED_RESOURCES", "INFERRED_GRADE"), ("Other", "OTHER_RESOURCES", "OTHER_GRADE")]

rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
latest = {}
for x in rows:
    k = (x["ENO"], x["ZONE_ENO"])
    if x["RECORD_DATE"] > latest.get(k, ""): latest[k] = x["RECORD_DATE"]
lr = [x for x in rows if x["RECORD_DATE"] == latest[(x["ENO"], x["ZONE_ENO"])]]
zeroed = {(x["ENO"], x["ZONE_ENO"]) for x in lr if x["ZEROED"] == "Y"}
lr = [x for x in lr if (x["ENO"], x["ZONE_ENO"]) not in zeroed]
log("rows", len(rows), "| latest-statement rows", len(lr), "| zeroed zones skipped", len(zeroed))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
for col, typ in (("source_system", "varchar(64)"), ("zone_name", "text"), ("comments", "text")):
    c.execute(f"ALTER TABLE core.resource_estimates ADD COLUMN IF NOT EXISTS {col} {typ}")
c.execute("SELECT count(*) FROM core.resource_estimates WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT source_id, entity_id FROM core.external_ids WHERE source_system = 'AUSTRALIA_GA_OZMIN' AND entity_type = 'OCCURRENCE'")
OCC = dict(c.fetchall())
c.execute("SELECT commodity_name, commodity_id, commodity_symbol FROM core.commodities")
COM = {}
for nm, cid, sym in c.fetchall():
    COM[nm.lower()] = cid
    if sym: COM[sym.lower()] = cid

# deposits in the resource layer but not in the OZMIN deposit layer: match by position + name to our Australian occurrences
def norm(n): return re.sub(r"[^a-z0-9]", "", (n or "").lower())
GEN = {"mine", "deposit", "project", "prospect", "north", "south", "east", "west", "central", "group", "extended", "main"}
def wset(n): return {w for w in re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split() if len(w) >= 4 and w not in GEN and not w.isdigit()}
extra, matched_by = {}, collections.Counter()
for eno, x in {x["ENO"]: x for x in lr if x["ENO"] not in OCC}.items():
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND country_name = 'Australia' AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 5000) ORDER BY d""",
              (float(x["LONG_GDA94"]), float(x["LAT_GDA94"])) * 2)
    best = None
    for oid, nm, d in c.fetchall():
        if norm(nm) == norm(x["DEPOSIT_NAME"]): best = (oid, "same name"); break
        if d <= 2000 and wset(nm) & wset(x["DEPOSIT_NAME"]) and best is None: best = (oid, "name word within 2 km")
        if d <= 300 and best is None: best = (oid, "within 300 m")
    if best: extra[eno] = best[0]; matched_by[best[1]] += 1
log("resource-only deposits", len({x["ENO"] for x in lr if x["ENO"] not in OCC}), "| matched to an occurrence", dict(matched_by))
OCC.update(extra)
vals, no_occ, no_com, empty = [], set(), collections.Counter(), 0
for x in lr:
    oid = OCC.get(x["ENO"])
    if oid is None: no_occ.add(x["ENO"]); continue
    code = x["COMMODITY_CODE"].strip()
    cid = COM.get(CODES.get(code, code).lower())
    if cid is None: no_com[code] += 1
    tu = TU.get(x["TONNAGE_UNIT"], x["TONNAGE_UNIT"])
    gu_raw = x["GRADE_UNIT"].replace("Kg", "kg")
    gu = f"{gu_raw} {code}" if gu_raw else None
    for cat, tcol, gcol in CATS:
        t, gr = num(x[tcol]), num(x[gcol])
        if t is None and gr is None: continue
        contained, cunit = None, None
        if t is not None and gr is not None and tu in TONNES:
            tt = t * TONNES[tu]
            if gu_raw == "%": contained, cunit = tt * gr / 100, f"t {code}"
            elif gu_raw == "ppm": contained, cunit = tt * gr / 1e6, f"t {code}"
            elif gu_raw == "kg/t": contained, cunit = tt * gr / 1000, f"t {code}"
            elif gu_raw == "g/t": contained, cunit = tt * gr / 31.1035 / 1000, f"koz {code}"
        note = "; ".join(p for p in [
            "Source: Geoscience Australia OZMIN reserves and resources (CC BY 4.0)",
            f"OZMIN deposit {x['DEPOSIT_NAME']} (ENO {x['ENO']}), resource no {x['RESOURCE_NO']}, zone ENO {x['ZONE_ENO']}",
            f"Deposit status (OZMIN): {x['OPERATING_STATUS']}",
            "Resources INCLUDE reserves" if x["INCLUSIVE"] == "Y" else "Resources reported EXCLUSIVE of reserves (or not stated)",
            f"Reference: {x['RESOURCE_REF'].strip(' ,;')}" if x["RESOURCE_REF"].strip(" ,;") else None,
            "Contained metal calculated by Interzona from tonnage x grade (not reported by the source)" if contained is not None else None,
            "Latest statement held by GA for this zone; older statements not loaded"] if p)
        vals.append((oid, cid, cat, x["CLASSIFICATION_METHOD"] or None, x["RECORD_DATE"] or None, t, tu if t is not None else None, gr,
                     gu if gr is not None else None, contained, cunit, True, TAG, SRC, x["ZONE_NAME"] or None, note))
log("rows to insert", len(vals), "| deposits without an occurrence", len(no_occ), "| unmapped commodity codes", no_com.most_common(20))
execute_values(c, """INSERT INTO core.resource_estimates (occurrence_id, commodity_id, classification, reporting_standard, effective_date, tonnage, tonnage_unit,
                     grade, grade_unit, contained_metal, contained_metal_unit, is_active, created_by, created_date, source_system, zone_name, comments) VALUES %s""",
               vals, template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s)", page_size=5000)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-08',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "Geoscience Australia (Commonwealth of Australia)", "OZMIN ore reserves and mineral resources (WFS ama:ReservesAndResources), downloaded 2026-11-08",
           "Creative Commons Attribution 4.0 International (CC BY 4.0)", "https://creativecommons.org/licenses/by/4.0/",
           "Contains Geoscience Australia OZMIN reserves and resources data, Commonwealth of Australia (Geoscience Australia), licensed under CC BY 4.0.",
           "Cleared: CC BY 4.0 stated in the GA WFS AccessConstraints (checked 2026-11-08). Loaded 2026-11-08.",
           "Latest statement per deposit zone only (many are years old: check effective_date). Compiled by GA from company reports; contained metal is "
           "calculated by Interzona. Resources may include or exclude reserves (see comments). Zeroed zones not loaded.",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/GA_OZMIN/EVIDENCE.md", TAG))
c.execute("""SELECT count(*), count(DISTINCT occurrence_id), min(effective_date), max(effective_date),
             count(*) FILTER (WHERE effective_date >= '2020-01-01'), count(*) FILTER (WHERE commodity_id IS NULL), count(contained_metal)
             FROM core.resource_estimates WHERE source_system = %s""", (SRC,))
log("rows, occurrences, min/max date, since 2020, no commodity, with contained", c.fetchone())
c.execute("""SELECT o.name, r.zone_name, r.effective_date, r.classification, r.tonnage, r.tonnage_unit, r.grade, r.grade_unit, round(r.contained_metal), r.contained_metal_unit
             FROM core.resource_estimates r JOIN core.occurrences o USING (occurrence_id) WHERE r.source_system = %s
             AND (o.name ILIKE 'Olympic Dam%%' OR o.name ILIKE 'Greenbushes%%') AND r.grade_unit IN ('%% Cu','%% Li2O') ORDER BY 1,2,4""", (SRC,))
for r in c.fetchall(): log("  ", r)
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
