"""USGS Mineral Resources Data System (MRDS, edition 20160315, mrds.csv, 304,632 records) -> interzona_cm core.occurrences / core.occurrence_commodities / core.external_ids.

Rules agreed with the user (2026-10-14):
  * skip records already in gold: within 200 m of an existing occurrence, or within 1 km sharing a name word with it;
  * keep the best of MRDS's own duplicates (same normalised name within 250 m): score A>B>C>D>E, then most filled fields;
  * load records that have a usable name OR a primary commodity; unnamed ones get a generated name 'MRDS <commodity> site <dep_id>'; skip those with neither;
  * is_deposit true for Prospect / Producer / Past Producer / Plant, false for Occurrence / Unknown; status from dev_stat;
  * prod_size (ambiguous), dep_type, model, ore/gangue etc. stay in the comments; NO occurrence_type, NO mineralogy rows (first pass);
  * the 'reporter' field (person names) is never loaded.
Commodities: element names -> gold symbol commodities, curated industrial minerals (see CURATED/ALIAS); commod1 = PRIMARY, commod2/3 = SECONDARY (PRIMARY wins).
Writes gold_schema/_mrds_skipped.csv (dep_id, reason) for review.  Usage: python load_mrds.py [--dry]
"""
import csv, re, os, sys, time, collections
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree

DRY = "--dry" in sys.argv
TAG = "migration_mrds_20261014"
HERE = os.path.dirname(os.path.abspath(__file__))
csv.field_size_limit(10**8)
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def _lines(path):
    with open(path, "rb") as fb:
        for raw in fb:
            try: yield raw.decode("utf-8")
            except UnicodeDecodeError: yield raw.decode("cp1252", errors="replace")


R = list(csv.DictReader(_lines(r"D:\CriticalMineralsDB\mrds.csv")))
log("MRDS records", len(R))
norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
STOP = {"mine", "the", "and", "prospect", "claim", "claims", "group", "mines", "property", "deposit", "quarry", "pit", "unnamed", "unknown", "no", "name"}
tokens = lambda s: {t for t in norm(s).split() if len(t) > 2 and t not in STOP}
UNNAMED = {"", "unnamed", "unknown", "no name", "n a", "na"}
skipped = []  # (dep_id, reason)


def fnum(x):
    try: return float(x)
    except Exception: return None


# ------------------------------------------------------------------ validity
recs = []
for r in R:
    r["_lat"], r["_lon"] = fnum(r["latitude"]), fnum(r["longitude"])
    if r["_lat"] is None or r["_lon"] is None or not (-90 <= r["_lat"] <= 90 and -180 <= r["_lon"] <= 180) or (r["_lat"] == 0 and r["_lon"] == 0):
        skipped.append((r["dep_id"], "no usable coordinates")); continue
    recs.append(r)
log("usable coordinates", len(recs))

# ------------------------------------------------------------------ country -> jurisdiction
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT jurisdiction_id, name, official_name, iso_code FROM core.jurisdictions WHERE level = 'COUNTRY'")
J = c.fetchall()
BYNAME = {}
for jid, n, o, iso in J:
    BYNAME[norm(n)] = jid
    if o: BYNAME.setdefault(norm(o), jid)
BYISO = {iso: jid for jid, n, o, iso in J}
ISO_ALIAS = {"Russia": "RU", "Laos": "LA", "Korea, South": "KR", "Korea, North": "KP", "Congo (Kinshasa)": "CD", "Congo (Brazzaville)": "CG", "Burma": "MM", "Vietnam": "VN",
             "Cote D'Ivoire": "CI", "Macedonia": "MK", "Swaziland": "SZ", "Syria": "SY", "Bahamas, the": "BS", "Bahamas, The": "BS", "Gambia, the": "GM"}
def jur(country):
    if country in ISO_ALIAS and BYISO.get(ISO_ALIAS[country]): return BYISO[ISO_ALIAS[country]]
    return BYNAME.get(norm(country))
ok = []
for r in recs:
    r["_jid"] = jur(r["country"])
    if r["_jid"] is None:
        skipped.append((r["dep_id"], "country not matched: '%s'" % r["country"])); continue
    ok.append(r)
log("country matched", len(ok), "| skipped for country", len(recs) - len(ok))

# ------------------------------------------------------------------ commodities
ELEM = {"Hydrogen": "H", "Helium": "He", "Lithium": "Li", "Beryllium": "Be", "Boron": "B", "Carbon": "C", "Nitrogen": "N", "Oxygen": "O", "Fluorine": "F", "Sodium": "Na", "Magnesium": "Mg", "Aluminum": "Al", "Silicon": "Si",
        "Phosphorus": "P", "Sulfur": "S", "Chlorine": "Cl", "Potassium": "K", "Calcium": "Ca", "Scandium": "Sc", "Titanium": "Ti", "Vanadium": "V", "Chromium": "Cr", "Manganese": "Mn", "Iron": "Fe", "Cobalt": "Co", "Nickel": "Ni",
        "Copper": "Cu", "Zinc": "Zn", "Gallium": "Ga", "Germanium": "Ge", "Arsenic": "As", "Selenium": "Se", "Bromine": "Br", "Rubidium": "Rb", "Strontium": "Sr", "Yttrium": "Y", "Zirconium": "Zr", "Niobium": "Nb", "Molybdenum": "Mo",
        "Ruthenium": "Ru", "Rhodium": "Rh", "Palladium": "Pd", "Silver": "Ag", "Cadmium": "Cd", "Indium": "In", "Tin": "Sn", "Antimony": "Sb", "Tellurium": "Te", "Iodine": "I", "Cesium": "Cs", "Barium": "Ba", "Lanthanum": "La",
        "Cerium": "Ce", "Praseodymium": "Pr", "Neodymium": "Nd", "Samarium": "Sm", "Europium": "Eu", "Gadolinium": "Gd", "Terbium": "Tb", "Dysprosium": "Dy", "Holmium": "Ho", "Erbium": "Er", "Thulium": "Tm", "Ytterbium": "Yb",
        "Lutetium": "Lu", "Hafnium": "Hf", "Tantalum": "Ta", "Tungsten": "W", "Rhenium": "Re", "Osmium": "Os", "Iridium": "Ir", "Platinum": "Pt", "Gold": "Au", "Mercury": "Hg", "Thallium": "Tl", "Lead": "Pb", "Bismuth": "Bi",
        "Thorium": "Th", "Uranium": "U", "Radium": "Ra", "Promethium": "Pm", "Niobium (Columbium)": "Nb"}
CURATED = {"Sand and Gravel, Construction": "Sand and Gravel", "Sand and Gravel, Industrial": "Silica Sand", "Stone, Crushed/Broken": "Crushed Rock", "Stone": "Crushed Rock", "Stone, Dimension": "Miscellaneous Dimension Stones",
 "Dimension": "Miscellaneous Dimension Stones", "Stone, Dimension/Building": "Miscellaneous Dimension Stones", "Barium-Barite": "Baryte", "Fluorine-Fluorite": "Fluorite", "Phosphorus-Phosphates": "Phosphate Rock", "Gypsum-Anhydrite": "Gypsum",
 "Talc-Soapstone": "Talc", "Fire Clay (Refractory)": "White Firing Clay", "Silica": "SiO2", "Platinum-Group Metals": "PGE", "Rare Earths": "REE", "Rare Earths-Rare Earth Oxides": "Rare Earth Oxide", "Zeolites": "Zeolite",
 "Magnesite": "MgCO3", "Titanium-Ilmenite": "Ilmenite", "Titanium-Rutile": "Rutile", "Zirconium-Zircon": "Zircon", "Aluminum-Bauxite": "Bauxite", "Iron-Magnetite": "Magnetite", "Iron-Hematite": "Hematite",
 "Molybdenum-Molybdenite": "Molybdenite", "Chromium-Chromite": "Chromite", "Sulfur-Pyrite": "Pyrite", "Fluorspar": "Fluorite", "Barite": "Baryte", "Halite": "Salt", "Lignite": "Brown Coal", "Sodium Carbonate": "Soda Ash",
 "Ball Clay": "Clay", "Clay, Common": "Clay", "Aggregate": "Crushed Rock"}
KNOWN_COMMA = sorted(["Sand and Gravel, Construction", "Sand and Gravel, Industrial", "Stone, Crushed/Broken", "Stone, Dimension/Building", "Stone, Dimension", "Stone, Crushed", "Clay, Common", "Clay, Fire"], key=len, reverse=True)
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
_cache = {}
def map_tok(t):
    if t in _cache: return _cache[t]
    base = t.split("-")[0].strip(); out = None
    if t in CURATED: out = GN.get(CURATED[t].lower())
    if out is None and t in ELEM: out = GN.get(ELEM[t].lower())
    if out is None and base in ELEM: out = GN.get(ELEM[base].lower())
    if out is None: out = GN.get(t.lower())
    if out is None: out = GN.get(base.lower())
    _cache[t] = out; return out
def parse_comm(v):
    v = (v or "").strip()
    if not v: return []
    for kc in KNOWN_COMMA: v = v.replace(kc, kc.replace(", ", "@@"))
    return [p.strip().replace("@@", ", ") for p in v.split(",") if p.strip()]
for r in ok:
    r["_c1"] = parse_comm(r["commod1"]); r["_c23"] = parse_comm(r["commod2"]) + parse_comm(r["commod3"])

# ------------------------------------------------------------------ weak records
def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]) * 6371000.0
keep = []
for r in ok:
    named = norm(r["site_name"]) not in UNNAMED
    if not named and not r["_c1"]:
        skipped.append((r["dep_id"], "no name and no primary commodity")); continue
    keep.append(r)
log("after dropping records with neither name nor commodity", len(keep))

# ------------------------------------------------------------------ vs gold
c.execute("SELECT name, lat, lon FROM core.occurrences")
G = c.fetchall()
gx = xyz(np.array([x[1] for x in G]), np.array([x[2] for x in G]))
mx = xyz(np.array([r["_lat"] for r in keep]), np.array([r["_lon"] for r in keep]))
near = cKDTree(gx).query_ball_point(mx, 1000)
kept2 = []
for i, r in enumerate(keep):
    dup = False
    mt = tokens(r["site_name"])
    for j in near[i]:
        d = np.linalg.norm(mx[i] - gx[j])
        if d <= 200 or (mt and mt & tokens(G[j][0])): dup = True; break
    if dup: skipped.append((r["dep_id"], "already in gold (near an existing occurrence)"))
    else: kept2.append(r)
log("after removing records already in gold", len(kept2))

# ------------------------------------------------------------------ internal duplicates
SC = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
filled = lambda r: sum(1 for k in ("commod1", "commod2", "commod3", "dev_stat", "oper_type", "ore", "gangue", "dep_type", "hrock_type", "ref", "model") if (r[k] or "").strip() not in ("", "Unknown"))
rank = lambda r: (SC.get(r["score"], 5), -filled(r), r["dep_id"])
mx2 = xyz(np.array([r["_lat"] for r in kept2]), np.array([r["_lon"] for r in kept2]))
pairs = cKDTree(mx2).query_pairs(250)
parent = list(range(len(kept2)))
def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
for a, b in pairs:
    na, nb = norm(kept2[a]["site_name"]), norm(kept2[b]["site_name"])
    if na and na == nb and na not in UNNAMED:
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
groups = collections.defaultdict(list)
for i in range(len(kept2)): groups[find(i)].append(i)
final = []
for ids in groups.values():
    best = min(ids, key=lambda i: rank(kept2[i]))
    final.append(kept2[best])
    for i in ids:
        if i != best: skipped.append((kept2[i]["dep_id"], "duplicate of MRDS record " + kept2[best]["dep_id"]))
log("after merging MRDS's own duplicates", len(final))

# idempotence: skip dep_ids already loaded
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = 'USGS_MRDS'")
done = {x[0] for x in c.fetchall()}
final = [r for r in final if r["dep_id"] not in done]
log("to load (not yet loaded)", len(final))
with open(os.path.join(HERE, "_mrds_skipped.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["dep_id", "reason"]); w.writerows(skipped)
log("skipped rows written:", len(skipped), dict(collections.Counter(re.sub(r"MRDS record .*|: '.*", "", s[1]) for s in skipped)))

# ------------------------------------------------------------------ build rows
STATUS = {"Producer": "PRODUCER", "Past Producer": "PAST_PRODUCER", "Occurrence": "OCCURRENCE", "Prospect": "PROSPECT", "Plant": "UNKNOWN", "Unknown": "UNKNOWN"}
DEPOSIT = {"Producer", "Past Producer", "Prospect", "Plant"}
WORK = {"Surface": "Surface", "Underground": "Underground", "Surface-Underground": "Surface and underground", "Placer": "Placer", "Processing Plant": "Processing plant", "Well": "Well", "Offshore": "Offshore", "Geothermal": "Geothermal", "Brine Operation": "Brine operation"}
def comment(r):
    p = [f"USGS MRDS record {r['dep_id']} ({r['url'].strip()})"]
    if r["mrds_id"].strip(): p.append("MRDS id " + r["mrds_id"].strip())
    loc = ", ".join(x for x in (r["county"].strip(), r["state"].strip(), r["country"].strip()) if x and x != "NA")
    if loc: p.append("Location: " + loc)
    comm = " / ".join(x for x in (r["commod1"].strip(), r["commod2"].strip(), r["commod3"].strip()) if x)
    if comm: p.append("Commodities (as reported): " + comm)
    for lab, k in (("Development status", "dev_stat"), ("Operation type", "oper_type"), ("Workings", "work_type"), ("Production size code (meaning unreliable)", "prod_size"), ("Deposit type", "dep_type"),
                   ("Model", "model"), ("Ore", "ore"), ("Gangue", "gangue"), ("Other materials", "other_matl"), ("Orebody form", "orebody_fm"), ("Alteration", "alteration"), ("Ore control", "ore_ctrl"),
                   ("Host rock", "hrock_type"), ("Associated rock", "arock_type"), ("Structure", "structure"), ("Tectonic setting", "tectonic"), ("Alternative names", "names"), ("First production year", "yr_fst_prd"),
                   ("Last production year", "yr_lst_prd"), ("Discovery year", "disc_yr"), ("Discoverer", "discr")):
        v = (r.get(k) or "").strip()
        if v and v not in ("NA", "Unknown"): p.append(f"{lab}: {v[:300]}")
    if r["score"].strip(): p.append("MRDS record-quality score " + r["score"].strip() + " (A best, E worst)")
    ref = (r["ref"] or "").strip()
    if ref: p.append("References: " + ref[:1500])
    p.append("Source: U.S. Geological Survey, Mineral Resources Data System (MRDS), edition 20160315. Load tag " + TAG)
    return " | ".join(p)
rows, meta = [], []
for r in final:
    name = r["site_name"].strip() if norm(r["site_name"]) not in UNNAMED else "MRDS %s site %s" % ((r["commod1"].split(",")[0].strip() or "mineral"), r["dep_id"])
    ds = r["dev_stat"].strip()
    rows.append((name[:300], ds in DEPOSIT, r["_jid"], r["_lon"], r["_lat"], STATUS.get(ds, "UNKNOWN"), WORK.get(r["oper_type"].strip()), comment(r)))
    meta.append(r)
tmpl = "(%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, 'UNKNOWN', %s, %s, true, '" + TAG + "', now())"
ids = execute_values(c, "INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, comments, is_active, created_by, created_date) VALUES %s RETURNING occurrence_id",
                     rows, template=tmpl, page_size=2000, fetch=True)
OID = [i[0] for i in ids]
assert len(OID) == len(rows)
log("occurrences inserted", len(OID))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("OCCURRENCE", oid, "USGS_MRDS", r["dep_id"], TAG) for oid, r in zip(OID, meta)], page_size=5000)
links = {}
unmapped = collections.Counter()
for oid, r in zip(OID, meta):
    for role, toks in (("PRIMARY", r["_c1"]), ("SECONDARY", r["_c23"])):
        for t in toks:
            cid = map_tok(t)
            if cid is None: unmapped[t] += 1; continue
            k = (oid, cid)
            if k not in links or (role == "PRIMARY" and links[k] != "PRIMARY"): links[k] = role
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s",
               [(o, cid, role, True, TAG) for (o, cid), role in links.items()], template="(%s, %s, %s, %s, %s)", page_size=5000)
log("commodity links", len(links), "| unmapped commodity mentions", sum(unmapped.values()), unmapped.most_common(10))

# ------------------------------------------------------------------ verification
c.execute("SELECT count(*), count(*) FILTER (WHERE is_deposit), count(*) FILTER (WHERE array_length(commodities,1) > 0), count(DISTINCT country_name) FROM core.occurrences WHERE created_by = %s", (TAG,))
log("occurrences (count, is_deposit, with commodities, countries)", c.fetchone())
c.execute("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); log("status", c.fetchall())
c.execute("SELECT country_name, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC LIMIT 8", (TAG,)); log("countries", c.fetchall())
c.execute("""SELECT cm.commodity_name, count(*) FROM core.occurrence_commodities oc JOIN core.commodities cm USING (commodity_id) WHERE oc.created_by = %s AND oc.commodity_role = 'PRIMARY' GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", (TAG,)); log("top primary commodities", c.fetchall())
c.execute("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND comments ILIKE %s", (TAG, "%| Reporter%")); log("comments carrying a Reporter field (must be 0)", c.fetchone()[0])
c.execute("SELECT name, round(lat::numeric,4), round(lon::numeric,4), country_name, status, is_deposit, commodities FROM core.occurrences WHERE created_by = %s ORDER BY occurrence_id LIMIT 3", (TAG,))
for x in c.fetchall(): log("  ", x)
c.execute("SELECT count(*) FROM core.occurrences"); log("core.occurrences total", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    c.execute("UPDATE core.data_sources SET is_loaded = true, licence_status = 'Cleared: no access or use constraints stated; USGS policy treats USGS-authored data as public domain (2026-10-14). Loaded 2026-10-14.' WHERE source_system = 'USA_USGS_MRDS'")
    g.commit(); log("COMMITTED")
g.close()
