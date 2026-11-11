"""Load the MIN4EU harmonised European mineral dataset (EGDI / GeoERA Mintell4EU, WFS at maps.europe-geology.eu, CC BY 4.0 except Polish
data CC BY-NC-ND) into core.occurrences: two layers downloaded 11 Nov 2026 to D:/CriticalMineralsDB/Europe/min4eu_20261111
  - egdi_mineraloccurr_critical_raw_materials (11,462 rows, one per site and commodity): critical-raw-material occurrences and deposits
  - egdi_mines (62,409 rows): mines and quarries
What is loaded: named records only; Poland left out (non-commercial licence); Sweden left out (SGU loaded directly, 7 Nov); mines whose only
commodities are construction materials, fuels or 'unknown' left out (aggregates, limestone, clays, sand, slate, dimension stone, coal, gas...).
Rows of one site (same name and position) are combined; a CRM site and a mine with a similar name within 1 km become one record.
Each site is then matched to existing occurrences (not from this load): similar name within 2 km -> ATTACH (external id, missing
commodities as SECONDARY, MIN4EU facts appended to comments), else NEW.

Usage: python load_min4eu.py [--dry]     (the dry run writes min4eu_load_log_20261111_DRY.csv and changes nothing)
"""
import collections, csv, difflib, json, os, re, sys, unicodedata
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_min4eu_20261111"
SRC = "EU_MIN4EU"
DIR = "D:/CriticalMineralsDB/Europe/min4eu_20261111/extracted"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for line in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v.strip().strip('"')

SKIP_COUNTRIES = {"Poland", "Sweden"}
CONSTRUCTION = r"^(unknown|aggregates|limestone|clays?|sand|sand and gravel|gravel|slate|dimension stone|marble|coal|lignite|natural gas|oil|peat|" \
               r"industrial rocks and minerals|chalk|dolomite|gypsum|granite|basalt|sandstone|crushed rock|building stone|brick clay|evaporite|salt|" \
               r"cement|organic material|oil shale|asphalt|carbon|metal|base metal|refractory mineral|gemstones|precious gemstones)$"
# MIN4EU commodity words -> core.commodities names (metals by symbol). None = not mapped (kept in comments only).
CMAP = {
    "copper": "Cu", "lead": "Pb", "iron": "Fe", "zinc": "Zn", "baryte": "Baryte", "fluospar": "Fluorite", "fluorspar": "Fluorite", "sulphur": "S",
    "uranium": "U", "gold": "Au", "feldspar industrial mineral": "Feldspar", "tin": "Sn", "silica": "Silica Sand", "tungsten": "W", "silver": "Ag",
    "quartz": "Quartz", "arsenic": "As", "antimony": "Sb", "phosphate": "Phosphate Rock", "phosphaterock": "Phosphate Rock", "titanium": "Ti",
    "manganese": "Mn", "cobalt": "Co", "bentonite": "Bentonite", "nickel": "Ni", "molybdenum": "Mo", "aluminium": "Al", "chromium": "Cr",
    "beryllium": "Be", "graphite": "Graphite", "graphiteunspecified": "Graphite", "graphiteamorphous": "Graphite", "bauxite": "Bauxite",
    "zirconium": "Zr", "talc": "Talc", "germanium": "Ge", "serpentine": "Serpentine", "bismuth": "Bi", "mica": "Mica", "mercury": "Hg",
    "magnesia": "Magnesia", "asbestos": "Asbestos", "lithium": "Li", "lithiumoxide": "Li", "magnetite": "Magnetite", "rare earth element": "REE",
    "ree": "REE", "lree": "LREE", "hree": "HREE", "indium": "In", "tantalum": "Ta", "tantalumpentoxide": "Ta", "calcite": "Calcite",
    "niobium": "Nb", "niobiumpentoxide": "Nb", "cadmium": "Cd", "potash": "Potash", "gallium": "Ga", "perlite": "Perlite", "apatite": "Apatite",
    "alunite": "Alunite", "strontium": "Sr", "kyanite": "Kyanite", "vanadium": "V", "vanadiumpentoxide": "V", "potassium": "K", "cesium": "Cs",
    "rubidium": "Rb", "thorium": "Th", "chert": "Chert", "wollasonite": "Wollastonite", "tellurium": "Te", "fuller's earth": "Fullers Earth",
    "platinum": "Pt", "aluminosilicate": "Aluminosilicate", "alumina": "Alumina", "magnesium": "Mg", "monazite": "Monazite", "boron": "B",
    "sillimanite": "Sillimanite", "thallium": "Tl", "selenium": "Se", "vermiclite": "Vermiculite", "palladium": "Pd", "rhenium": "Re",
    "samarium": "Sm", "beryl": "Beryl", "borate": "Borate", "thenarite": "Thenardite", "zircon": "Zircon", "bromine": "Br", "rhodonite": "Rhodonite",
    "halloysite": "Halloysite", "pgm": "PGE", "phosphorous": "P", "phosphorouspentoxide": "P", "scandium": "Sc", "hafnium": "Hf",
    "rhodium": "Rh", "ruthenium": "Ru", "iridium": "Ir", "yttriumoxide": "Y",
}
MSTATUS = {"operating": "PRODUCER", "operating continuously": "PRODUCER", "operating intermittently": "PRODUCER", "abandoned": "PAST_PRODUCER",
           "historic": "PAST_PRODUCER", "closed": "PAST_PRODUCER", "not operating": "CARE_AND_MAINTENANCE", "retention": "CARE_AND_MAINTENANCE",
           "pending approval": "DEVELOPMENT", "under development": "DEVELOPMENT"}
WORK = {"quarry": "Quarry", "surface mining": "Surface", "open pit": "Surface", "underground": "Underground", "subsurface mining": "Underground",
        "open pit and underground": "Surface and underground", "borehole mining": "Well"}
SIZE = {"very large deposit": "GIANT", "large deposit": "LARGE", "medium sized deposit": "MEDIUM", "small deposit": "SMALL", "occurrence": "OCCURRENCE"}
NONAME = {"", "unknown", "empty data", "-", "n/a", "sin nombre", "s/n"}
STOP = r"\b(mine|mines|mina|deposit|gisement|mine de|prospect|occurrence|quarry|cantera|indicio|vein|filon|mining|area)\b"
def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()).replace("ae", "a").replace("oe", "o").replace("ue", "u")   # Kylmakoski = Kylmaekoski
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", s))


CODE = re.compile(r"^[A-Z]{2,4}[-_ ]?\d+[A-Z]?$")   # BRGM / Greek / Cypriot ids used as names (France: real name in alternative_name)
named = lambda s: (s or "").strip().lower() not in NONAME


def words(txt):
    return [w.strip() for w in re.split(r",", txt or "") if w.strip()]


# ------------------------------------------------------------------ read and combine
crm = json.load(open(f"{DIR}/crm/geojson-export.dat", encoding="utf-8"))["features"]
mines = json.load(open(f"{DIR}/mines/geojson-export.dat", encoding="utf-8"))["features"]
CODENAME = {}
for f in mines:
    p = f["properties"]; nm = (p["name"] or "").strip(); alt = (p["alternative_name"] or "").strip()
    if CODE.match(nm) and named(alt):
        p["code"] = nm; p["name"] = alt; CODENAME[nm] = alt
for f in crm:
    p = f["properties"]; nm = (p["name"] or "").strip()
    if CODE.match(nm):
        p["code"] = nm
        p["name"] = CODENAME.get(nm) or f"Unnamed {p['commodity_hidden'] or 'mineral'} occurrence ({nm})"
sites = collections.OrderedDict()
for f in crm:
    p = f["properties"]
    if p["country"] in SKIP_COUNTRIES or not named(p["name"]): continue
    lon, lat = f["geometry"]["coordinates"][:2]
    k = ("CRM", p["name"].strip(), round(lon, 5), round(lat, 5))
    s = sites.setdefault(k, dict(layer="CRM", name=p["name"].strip(), country=p["country"], lon=lon, lat=lat, comms=[], ids=[], sig=set(),
                                 imp=set(), dtype=set(), work=set(), status=set(), raw=set()))
    s["comms"].append(p["commodity_hidden"] or ""); s["raw"].add(p["commodity"] or ""); s["ids"].append(str(p["id_hidden"]))
    if p.get("code"): s["code"] = p["code"]
    s["sig"].add(p["significance"] or ""); s["imp"].add(p["importance"] or ""); s["dtype"].add(p["deposit_type"] or "")
    s["work"].add(p["mining_activity_type"] or "")
n_m = 0
for f in mines:
    p = f["properties"]
    if p["country"] in SKIP_COUNTRIES or not named(p["name"]): continue
    useful = [w for w in words(p["commodity"]) if not re.match(CONSTRUCTION, w.lower())]
    if not useful: continue
    n_m += 1
    lon, lat = f["geometry"]["coordinates"][:2]
    k = ("MINE", p["name"].strip(), round(lon, 5), round(lat, 5))
    s = sites.setdefault(k, dict(layer="MINE", name=p["name"].strip(), country=p["country"], lon=lon, lat=lat, comms=[], ids=[], sig=set(),
                                 imp=set(), dtype=set(), work=set(), status=set(), raw=set(), dates=set()))
    s["comms"] += useful; s["raw"].add(p["commodity"] or ""); s["ids"].append(p["inspireid"] or str(p["hidden_id"]))
    s["work"].add(p["miningactivity"] or ""); s["status"].add(p["status"] or "")
    if p.get("code"): s["code"] = p["code"]
    s.setdefault("dates", set()).add(f"{p['start_date'] or ''}-{p['end_date'] or ''}".strip("-"))
print("CRM rows ->", sum(1 for k in sites if k[0] == "CRM"), "sites | mine rows kept", n_m, "->", sum(1 for k in sites if k[0] == "MINE"), "sites")

# a CRM site and a mine with a similar name within ~1 km -> one record (the mine keeps its status, the CRM site adds commodities)
mine_keys = [k for k in sites if k[0] == "MINE"]
grid = collections.defaultdict(list)
for k in mine_keys: grid[(round(k[3], 1), round(k[2], 1))].append(k)
merged = 0
for k in [k for k in sites if k[0] == "CRM"]:
    s = sites[k]
    cands = [m for dy in (-0.1, 0, 0.1) for dx in (-0.1, 0, 0.1) for m in grid.get((round(k[3] + dy, 1), round(k[2] + dx, 1)), [])]
    for m in cands:
        if m not in sites: continue
        if abs(m[3] - k[3]) < 0.01 and abs(m[2] - k[2]) < 0.014 and difflib.SequenceMatcher(None, norm(m[1]), norm(k[1])).ratio() > 0.85:
            t = sites[m]
            t["comms"] += s["comms"]; t["raw"] |= s["raw"]; t["ids"] += ["CRM:" + i for i in s["ids"]]; t["sig"] |= s["sig"]; t["imp"] |= s["imp"]
            t["dtype"] |= s["dtype"]; t["layer"] = "MINE+CRM"
            del sites[k]; merged += 1
            break
print("CRM sites merged into mines:", merged, "| sites to load:", len(sites))

# ------------------------------------------------------------------ database
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
c.execute("SELECT lower(name), jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'"); JN = dict(c.fetchall())
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,)); DONE = {x[0] for x in c.fetchall()}
unmapped, nojur, stats, logrows, ext = collections.Counter(), collections.Counter(), collections.Counter(), [], []


def cids(comms):
    out = []
    for w in comms:
        nm = CMAP.get(w.strip().lower())
        if nm is None: unmapped[w] += 1; continue
        cid = GN.get(nm.lower())
        if cid is None: unmapped[w + " -> " + nm] += 1; continue
        if cid not in out: out.append(cid)
    return out


def match(name, lon, lat):
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND created_by <> %s AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 2000) ORDER BY d LIMIT 8""",
              (lon, lat, TAG, lon, lat))
    near = c.fetchall(); nm = norm(name)
    for oid, n2, d in near:
        if d < 150 or (nm == "drakelands" and "hemerdon" in norm(n2)):   # same site under another name (Weisswassergraben = Koralpe, 27 m)
            return oid, n2, round(d)
        n2n = norm(n2)
        if nm and n2n and (difflib.SequenceMatcher(None, nm, n2n).ratio() > 0.8 or (len(nm) > 4 and len(n2n) > 4 and (nm in n2n or n2n in nm))):
            return oid, n2, round(d)
    return None, (near[0][1] if near else None), (round(near[0][2]) if near else None)


def facts(s):
    st = "; ".join(sorted(x for x in s["status"] if x)); wk = "; ".join(sorted(x for x in s["work"] if x and x != "unknown"))
    parts = [f"MIN4EU {s['layer'].replace('CRM', 'critical-raw-material occurrence').replace('MINE', 'mine')} ({s['country']})",
             f"commodities as published: {'; '.join(sorted(x for x in s['raw'] if x))}"]
    if st: parts.append(f"status as published: {st}")
    if wk: parts.append(f"mining: {wk}")
    sig = "; ".join(sorted(x for x in s["sig"] | s["imp"] if x))
    if sig: parts.append(f"significance: {sig}")
    dt = "; ".join(sorted(x for x in s["dtype"] if x))
    if dt: parts.append(f"deposit type: {dt}")
    dates = "; ".join(sorted(x for x in s.get("dates", set()) if x))
    if dates: parts.append(f"dates: {dates}")
    parts.append(f"ids: {', '.join(([s['code']] if s.get('code') else []) + s['ids'][:6])}{' ...' if len(s['ids']) > 6 else ''}")
    return " | ".join(parts) + " | Source: MIN4EU harmonised dataset, EGDI / GeoERA Mintell4EU (CC BY 4.0)."


def status(s):
    if s["status"]:
        ranked = [MSTATUS.get(x.lower(), "UNKNOWN") for x in s["status"]]
        for want in ("PRODUCER", "DEVELOPMENT", "CARE_AND_MAINTENANCE", "PAST_PRODUCER"):
            if want in ranked: return want
        return "UNKNOWN"
    sig = {x for x in s["sig"] if x}
    if sig & {"project"}: return "EXPLORATION"
    if sig & {"prospect"}: return "PROSPECT"
    if sig <= {"occurrence", "mineralizedZone"} and sig: return "OCCURRENCE"
    return "UNKNOWN"


for s in sites.values():
    sid = s["ids"][0] if s["layer"] != "CRM" else "CRM:" + s["ids"][0]
    if sid in DONE: stats["already loaded"] += 1; continue
    comm_ids = cids(s["comms"])
    oid, near_name, dist = match(s["name"], s["lon"], s["lat"])
    if oid:
        stats["attach"] += 1; act = "ATTACH"
        if not DRY:
            c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,)); have = {x[0] for x in c.fetchall()}
            for cid in comm_ids:
                if cid not in have:
                    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'SECONDARY',true,%s)", (oid, cid, TAG))
            c.execute("UPDATE core.occurrences SET comments = coalesce(comments || ' | ', '') || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
                      (facts(s), TAG, oid))
    else:
        jid = JN.get(s["country"].lower())
        if jid is None: nojur[s["country"]] += 1
        is_dep = s["layer"] != "CRM" or bool({x for x in s["sig"]} & {"mineralDeposit", "field", "district"})
        size = next((SIZE[x] for x in ("very large deposit", "large deposit", "medium sized deposit", "small deposit", "occurrence") if x in s["imp"]), "UNKNOWN")
        work = next((WORK[x.lower()] for x in s["work"] if x and x.lower() in WORK), None)
        stats["new"] += 1; act = "NEW"
        if not DRY:
            c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, mineralization_style,
                         comments, is_active, created_by, created_date) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,%s,%s,true,%s,now())
                         RETURNING occurrence_id""",
                      (s["name"][:300], is_dep, jid, float(s["lon"]), float(s["lat"]), status(s), size, work,
                       ("; ".join(sorted(x for x in s["dtype"] if x)) or None), facts(s), TAG))
            oid = c.fetchone()[0]
            for i, cid in enumerate(comm_ids):
                c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                          (oid, cid, "PRIMARY" if i == 0 else "SECONDARY", TAG))
    stats[f"{act} {s['layer']}"] += 1
    ext.append(("OCCURRENCE", oid, SRC, sid, "MEDIUM" if act == "ATTACH" else "EXACT", TAG))
    logrows.append([s["layer"], act, sid, s["name"], s["country"], oid, near_name, dist])

with open(os.path.join(HERE, f"min4eu_load_log_20261111{'_DRY' if DRY else ''}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["layer", "action", "source_id", "name", "country", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)
print(dict(stats))
print("unmapped commodities:", dict(unmapped.most_common(20)), "| countries without jurisdiction:", dict(nojur))
print("by country (new / attach):", sorted(collections.Counter((r[4], r[1]) for r in logrows).items(), key=lambda x: -x[1])[:30])
if DRY:
    g.rollback(); print("DRY RUN - nothing written"); sys.exit()
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s ON CONFLICT DO NOTHING", ext, page_size=2000)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'EGDI (European Geological Data Infrastructure) / GeoERA Mintell4EU, national geological surveys',
             'MIN4EU harmonised dataset - Minerals Inventory: mines and critical-raw-material occurrences (WFS egdi_mines, egdi_mineraloccurr_critical_raw_materials)',
             'CC BY 4.0 (Polish data CC BY-NC-ND 4.0 - not loaded)','https://creativecommons.org/licenses/by/4.0/',true,
             'Contains MIN4EU harmonised data from EGDI / GeoERA Mintell4EU and the contributing national geological surveys, CC BY 4.0.',true,
             'Cleared: EGDI metadata record 60c74fbf-b934-4f5a-9e55-7cd40a010833 (WFS download service) gives CC BY 4.0, Polish data CC BY-NC-ND - checked 2026-11-11.',
             'Named records only; Poland (non-commercial licence) and Sweden (SGU loaded directly) left out; mines whose only commodities are construction materials, fuels or unknown left out. Status is as published by each survey (operating / abandoned / historic ...), often years old; positions as published. Harmonised from national databases of very different completeness (Spain, France, Norway, Czechia rich; Germany, UK, Poland thin).',
             'https://metadata.europe-geology.eu/record/full/60c74fbf-b934-4f5a-9e55-7cd40a010833','2026-11-11',true,%s,now()) ON CONFLICT DO NOTHING""", (SRC, TAG))
g.commit()
c.execute("SELECT count(*), count(*) FILTER (WHERE jurisdiction_id IS NULL), count(*) FILTER (WHERE array_length(commodities,1) > 0) FROM core.occurrences WHERE created_by = %s", (TAG,))
print("new occurrences / no jurisdiction / with commodities:", c.fetchone())
c.execute("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); print(c.fetchall())
