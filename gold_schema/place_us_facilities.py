"""Placement PROPOSAL for the USGS US facilities worksheet (849 facilities). READ-ONLY: nothing is written to the database.

For every facility (USGS Facility ID) it finds
  1. the town centre: Census 2026 Gazetteer places file, matched on (state, normalised place name; hyphen/slash parts of a name are aliases);
     if the town text is a county (or not a gazetteer place) the centre of our own MRDS records for that county;
  2. an existing gold occurrence it probably IS: active US occurrence near that point whose name matches the part of the facility name BEYOND the town name
     (generic words such as mine / plant / smelter / refinery / quarry removed), with the commodity agreeing or within 10 km.
Proposed action
  ATTACH         strong match: use the existing occurrence (capacity and owners hang off it, no new occurrence)
  (weak candidates - facility name is only a town name, commodity agrees, <= 5 km - are NOT attached: user decision 2026-10-15; they become new records and the candidate is noted in review_candidate)
  NEW_AREA       town not a gazetteer place but a Census county subdivision (township / CCD) of that name: new occurrence at its centre, position_accuracy = AREA_CENTROID
  NEW_TOWN       no matching occurrence: new occurrence at the town centre, position_accuracy = TOWN_CENTROID
  NEW_COUNTY     town not a gazetteer place but the text is a county: new occurrence at the MRDS county centre, position_accuracy = COUNTY_CENTROID
  UNPLACED       neither
Output: D:/CriticalMineralsDB/Processing/facilities_placement_proposal.csv + a printed summary.
Usage: python place_us_facilities.py
"""
import os, re, time, difflib
import pandas as pd
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")

XLSX = r"D:\CriticalMineralsDB\Processing\Mines, smelters, refineries, and recycling facilities in the United States_worksheet.xlsx"
GAZ = r"D:\CriticalMineralsDB\Processing\Census_Gazetteer_2026\2026_Gaz_place_national.txt"
OUT = os.environ.get("PROP_OUT", r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal.csv")
ONLY_IDS_FILE = os.environ.get("ONLY_IDS_FILE")   # restrict to these facility ids (e.g. the never-loaded ones)
SNAP_KM = 25
STATES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
          "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
          "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
          "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
          "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
          "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR", "guam": "GU"}
USPS = set(STATES.values())
GENERIC = {"mine", "mines", "quarry", "quarries", "plant", "smelter", "refinery", "facility", "facilities", "mill", "mills", "operation", "operations", "project", "complex", "the", "inc", "llc",
           "co", "corp", "company", "pit", "deposit", "property", "works", "unit", "no", "of", "and", "at", "plants", "processing", "recycling", "recovery", "minerals", "mining", "metals", "metal"}
PLACE_SUFFIX = r"\b(city and borough|unified government|metropolitan government|urban county|consolidated government|municipality|borough|village|town|city|cdp|township|plantation|comunidad|zona urbana)\b"
COMM = {"gold": {"au"}, "silver": {"ag"}, "copper": {"cu"}, "lead": {"pb"}, "zinc": {"zn"}, "uranium": {"u"}, "lithium": {"li"}, "titanium": {"ti"}, "nickel": {"ni"}, "cobalt": {"co"},
        "molybdenum": {"mo"}, "manganese": {"mn"}, "vanadium": {"v"}, "tungsten": {"w"}, "platinum": {"pt", "pge", "pgm"}, "palladium": {"pd", "pge", "pgm"}, "rhodium": {"rh", "pge"},
        "ruthenium": {"ru", "pge"}, "iridium": {"ir", "pge"}, "iron ore": {"fe", "iron"}, "aluminum": {"al", "bauxite"}, "alumina": {"al", "bauxite"}, "magnesium": {"mg", "magnesite", "dolomite", "mgco3"},
        "antimony": {"sb"}, "tin": {"sn"}, "zirconium": {"zr", "zircon"}, "beryllium": {"be"}, "rare earths": {"ree", "rare earth oxide", "la", "ce", "nd", "y"}, "graphite": {"graphite", "c"},
        "gypsum": {"gypsum"}, "lime": {"limestone", "lime", "ca", "calcium", "dolomite"}, "sulfur": {"s", "sulfur", "sulphur", "pyrite"}, "barite": {"baryte", "barite", "ba"},
        "potash": {"potash", "k", "sylvite"}, "phosphate rock": {"phosphate rock", "p", "phosphate"}, "phosphate": {"phosphate rock", "p", "phosphate"}, "fluorspar": {"fluorite", "fluorspar", "f"},
        "boron": {"b", "borate", "boron"}, "coal": {"coal"}, "coke": {"coal", "coke"}, "silicon": {"si", "silica", "quartz"}, "quartz": {"quartz", "silica", "si"}, "helium": {"helium"},
        "bromine": {"br", "bromine"}, "arsenic": {"as"}, "cadmium": {"cd"}, "selenium": {"se"}, "tellurium": {"te"}, "germanium": {"ge"}, "gallium": {"ga"}, "indium": {"in"}, "bismuth": {"bi"},
        "tantalum": {"ta"}, "niobium": {"nb"}, "hafnium": {"hf"}, "scandium": {"sc"}, "rhenium": {"re"}, "chromium": {"cr", "chromite"}, "ferroalloys": {"fe", "mn", "cr", "si"}}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def norm_place(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\bsaint\b", "st", s); s = re.sub(r"\bst\.", "st", s); s = re.sub(r"\bfort\b", "ft", s); s = re.sub(r"\bft\.", "ft", s); s = re.sub(r"\bmount\b", "mt", s); s = re.sub(r"\bmt\.", "mt", s)
    s = re.sub(PLACE_SUFFIX, " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tokens(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    return {t for t in re.sub(r"[^a-z0-9]+", " ", s).split() if t not in GENERIC and len(t) > 1}


def sim(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return max(inter / len(a | b), (inter / min(len(a), len(b))) * 0.9 if inter >= 2 or (inter == 1 and min(len(a), len(b)) == 1) else 0.0)


def comm_set(text):
    out = set()
    for x in (text or "").split(","):
        out |= COMM.get(x.strip().lower(), {x.strip().lower()})
    return out


# --- worksheet -> one row per facility
df = pd.read_excel(XLSX, sheet_name=0, dtype=str).fillna("")
df = df.loc[:, [c for c in df.columns if c.strip()]]
agg = df.groupby("USGS Facility ID").agg(name=("Facility Name", "first"), feature=("Feature Type", "first"), loc=("Location Description", "first"),
                                         state_name=("First-Level Administrative Division name", "first"), status=("Facility Status", "first"), rows=("Global entry", "count"),
                                         commodities=("Level 2 (Commodity)", lambda s: ", ".join(sorted(set(x for x in s if x))))).reset_index()
if ONLY_IDS_FILE:
    _ids = set(pd.read_csv(ONLY_IDS_FILE, dtype=str)["facility_id"])
    agg = agg[agg["USGS Facility ID"].isin(_ids)].reset_index(drop=True)
log("facilities", len(agg))


def parse_loc(row):
    parts = [p.strip() for p in row["loc"].split(",") if p.strip()]
    st = STATES.get(row["state_name"].strip().lower())
    if len(parts) >= 2 and not st:
        last = parts[-1]
        st = last.upper() if last.upper() in USPS else STATES.get(last.lower())
    return pd.Series({"town": parts[0] if parts else "", "st": st})


agg = pd.concat([agg, agg.apply(parse_loc, axis=1)], axis=1)
log("state resolved", int(agg["st"].notna().sum()), "| towns blank", int((agg["town"] == "").sum()))

# --- gazetteer (with hyphen / slash aliases)
gaz = pd.read_csv(GAZ, sep="|", dtype=str, encoding="latin-1").rename(columns=lambda c: c.strip())
gz = {}
for r in gaz.itertuples():
    base = re.sub(r"\(.*?\)", " ", r.NAME)
    keys = {norm_place(r.NAME), norm_place(base)}
    for part in re.split(r"[-/]", base):
        if len(part.strip()) > 2:
            keys.add(norm_place(part))
    for k in keys:
        gz.setdefault((r.USPS, k), []).append((r.NAME, float(r.INTPTLAT), float(r.INTPTLONG)))
log("gazetteer places", len(gaz))


def find_town(town, st):
    n = norm_place(town)
    cands = gz.get((st, n))
    how = "exact"
    if not cands:
        keys = [k[1] for k in gz if k[0] == st]
        m = difflib.get_close_matches(n, keys, n=1, cutoff=0.88)
        if m:
            cands, how = gz[(st, m[0])], "fuzzy"
    if not cands:
        return None, None, None, "none"
    nm, la, lo = cands[0]
    return nm, la, lo, how + ("_multi" if len(cands) > 1 else "")


# county subdivisions (townships, CCDs, precincts ...): second fallback, centre of a larger area -> position_accuracy AREA_CENTROID
SUB_SUFFIX = r"\b(ccd|township|twp|precinct|district|division|magisterial|election|voting|unorganized territory|territory|subdivision|barrio|census|area|town|city|village|borough|plantation|gore|grant|location|purchase|beat|ward|parish|hundred|canton)\b"
cs = pd.read_csv(GAZ.replace("place_national", "cousubs_national"), sep="|", dtype=str, encoding="latin-1").rename(columns=lambda c: c.strip())
sub = {}
for r in cs.itertuples():
    base = re.sub(r"\(.*?\)", " ", r.NAME)
    n = re.sub(r"[^a-z0-9]+", " ", re.sub(SUB_SUFFIX, " ", norm_place(base))).strip()
    if n:
        sub.setdefault((r.USPS, n), []).append((r.NAME, float(r.INTPTLAT), float(r.INTPTLONG)))
log("county subdivisions", len(cs))

# USGS GNIS (public domain) via The National Map web service: last-resort tier for localities that are in neither Census file. Results cached in gnis_cache.json.
import json, urllib.request, urllib.parse
GNIS_BASE = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer"
GNIS_UA = {"User-Agent": "interzona-research/1.0 (dean@atamaianalytics.com)"}
GNIS_CACHE_FILE = os.path.join(HERE, "_gnis_cache.json")
GNIS_CACHE = json.load(open(GNIS_CACHE_FILE, encoding="utf-8")) if os.path.exists(GNIS_CACHE_FILE) else {}
TYPOS = {"ceder city": "Cedar City", "humbolt": "Humboldt", "lehmi": "Lemhi", "northwest artic borough": "Northwest Arctic", "ceder": "Cedar"}


def gnis_variants(town):
    t = town.strip()
    out = [t]
    low = t.lower()
    for k, v in TYPOS.items():
        if k in low:
            out.append(re.sub(k, v, t, flags=re.I))
    out.append(re.sub(r"^city of\s+", "", t, flags=re.I))
    out.append(re.sub(r"\bMt\.?\s", "Mount ", t)); out.append(re.sub(r"\bSt\.?\s", "Saint ", t)); out.append(re.sub(r"\bSt\.?\s", "St. ", t))
    out.append(re.sub(r"\s+(Junction|Area|Region|Borough|County)$", "", t, flags=re.I))
    out.append(re.split(r"\s+and\s+|/", t)[0])           # 'Jefferson and Knox' -> 'Jefferson'
    seen, res = set(), []
    for v in out:
        if v and v.lower() not in seen:
            seen.add(v.lower()); res.append(v)
    return res


PLACE_CLASSES = {"Populated Place", "Civil", "Census", "Locale"}
AMBIG = {}


def gnis_all(town, st):
    """every GNIS feature with this name in the state (case-insensitive) from the first spelling variant that matches: (name, county, class, lat, lon)"""
    key = f"v2|{st}|{town}"
    if key in GNIS_CACHE:
        return [tuple(x) for x in GNIS_CACHE[key]]
    hits = []
    for variant in gnis_variants(town):
        for layer in (3, 2, 1, 5, 7):          # populated places, unincorporated (Census), incorporated, landforms, other hydrographic
            where = f"UPPER(gaz_name) = UPPER('{variant.replace(chr(39), chr(39) * 2)}') AND state_alpha = '{st}'"
            url = f"{GNIS_BASE}/{layer}/query?" + urllib.parse.urlencode({"where": where, "outFields": "gaz_name,gaz_featureclass,county_name", "returnGeometry": "true", "outSR": "4326", "f": "json", "resultRecordCount": 25})
            try:
                j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=GNIS_UA), timeout=40))
            except Exception:
                j = {}
            time.sleep(0.2)
            for f in j.get("features", []):
                pts = f.get("geometry", {}).get("points")
                if pts:
                    a = f["attributes"]
                    hits.append((a["gaz_name"], a.get("county_name") or "", a.get("gaz_featureclass") or "", pts[0][1], pts[0][0]))
        if hits:
            break
    GNIS_CACHE[key] = [list(h) for h in hits]
    json.dump(GNIS_CACHE, open(GNIS_CACHE_FILE, "w", encoding="utf-8"))
    return hits


def km(a, b):
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371 * 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def commodity_neighbours(lat, lon, fc):
    """existing active occurrences within 30 km that share a commodity with the facility"""
    if not fc:
        return 0
    c.execute("""SELECT count(*) FROM core.occurrences o WHERE o.is_active AND o.created_by IS DISTINCT FROM 'migration_usgs_facilities_20261015'
                 AND ST_DWithin(o.geog, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 30000) AND EXISTS (SELECT 1 FROM unnest(o.commodities) k WHERE lower(k) = ANY(%s))""", (lon, lat, list(fc)))
    return c.fetchone()[0]


def gnis_lookup(town, st, fc=None):
    """One GNIS location (name, lat, lon, county, class) for town/state, or None. Several different places with that name in the state are resolved only when
    one of them has at least 3 existing occurrences of the facility's commodity within 30 km and at least twice as many as the runner-up; otherwise the
    candidates are kept in AMBIG (shown in the proposal CSV) and the facility stays unplaced."""
    cands = gnis_all(town, st)
    if not cands:
        return None
    pool = [h for h in cands if h[2] in PLACE_CLASSES] or cands
    uniq = []
    for h in pool:
        if not any(km((h[3], h[4]), (x[3], x[4])) < 15 for x in uniq):
            uniq.append(h)
    if len(uniq) == 1:
        h = uniq[0]
        return (h[0], h[3], h[4], h[1], h[2])
    scored = sorted(((commodity_neighbours(h[3], h[4], fc), h) for h in uniq), key=lambda x: -x[0])
    if scored[0][0] >= 3 and scored[0][0] >= 2 * max(scored[1][0], 1):
        h = scored[0][1]
        return (h[0], h[3], h[4], h[1], h[2])
    AMBIG[(town, st)] = [(h[1], h[2], round(h[3], 3), round(h[4], 3), n) for n, h in scored[:6]]
    return None


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 120000")

# county centres from our own MRDS records ('Location: <county>, <state name>, United States' in the comments)
c.execute("""SELECT lower(m[1]), lower(m[2]), avg(lat), avg(lon), count(*)
             FROM core.occurrences o, LATERAL regexp_match(o.comments, 'Location: ([^,|]+), ([^,|]+), United States') m
             WHERE o.created_by = 'migration_mrds_20261014' AND o.country_name = 'United States' GROUP BY 1, 2 HAVING count(*) >= 3""")
county = {(STATES.get(sn), norm_place(cn)): (float(la), float(lo), n) for cn, sn, la, lo, n in c.fetchall() if STATES.get(sn)}
log("county centres from MRDS", len(county))

rows = []
for r in agg.itertuples():
    nm, la, lo, how = find_town(r.town, r.st) if r.st else (None, None, None, "no_state")
    pos = "TOWN_CENTROID"
    if la is None and r.st:
        sc = sub.get((r.st, re.sub(r"[^a-z0-9]+", " ", re.sub(SUB_SUFFIX, " ", norm_place(r.town))).strip()))
        if sc:
            nm, la, lo = sc[0]
            pos, how = "AREA_CENTROID", "subdivision" + ("_multi" if len(sc) > 1 else "")
    if la is None and r.st:
        hit = gnis_lookup(r.town, r.st, comm_set(r.commodities))
        if hit:
            nm, la, lo, gcounty, gclass = hit
            pos = "TOWN_CENTROID" if gclass == "Populated Place" or gclass in ("Locale", "Civil", "Census") else "AREA_CENTROID"
            how = f"gnis:{gclass}" + (f" ({gcounty} Co.)" if gcounty else "")
    if la is None and r.st:
        cc = county.get((r.st, norm_place(re.sub(r"\b(county|parish)\b", "", r.town, flags=re.I))))
        if cc:
            la, lo, pos, how = cc[0], cc[1], "COUNTY_CENTROID", f"county({cc[2]})"
    rec = dict(facility_id=r._1, name=r.name, feature=r.feature, status=r.status, commodities=r.commodities, town_text=r.loc, st=r.st, gaz_place=nm, town_lat=la, town_lon=lo, town_match=how,
               action="UNPLACED", review_candidate=("AMBIGUOUS GNIS (county, class, lat, lon, same-commodity sites within 30 km): " + str(AMBIG[(r.town, r.st)])) if (r.town, r.st) in AMBIG else "", occ_id="", occ_name="", occ_dist_km="", name_sim="", comm_match="", occ_source="", lat="", lon="", position_accuracy="")
    if la is not None:
        town_tok = tokens(r.town) | tokens(nm)
        ft_disc = tokens(r.name) - town_tok
        fc = comm_set(r.commodities)
        c.execute("""SELECT occurrence_id, name, lat, lon, created_by, commodities, round((ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) / 1000)::numeric, 1)
                     FROM core.occurrences WHERE is_active AND country_name = 'United States' AND created_by IS DISTINCT FROM 'migration_usgs_facilities_20261015' AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)""",
                  (lo, la, lo, la, (SNAP_KM if pos == "TOWN_CENTROID" else 40) * 1000))
        best = None
        for oid, oname, olat, olon, cb, ocom, dkm in c.fetchall():
            d = float(dkm)
            cm = bool(fc & {str(x).lower() for x in (ocom or [])})
            ot_disc = tokens(oname) - town_tok
            if ft_disc and ot_disc:
                sd = sim(ft_disc, ot_disc)
                if (sd >= 0.9 and (cm or d <= 10)) or (sd >= 0.6 and cm and d <= 10):
                    cand = (3 + sd + (0.5 if cm else 0), "ATTACH", sd)
                else:
                    continue
            elif not ft_disc and cm and d <= 5 and pos == "TOWN_CENTROID":
                cand = (1 + (1 - d / 5), "ATTACH_REVIEW", 0.0)
            else:
                continue
            if best is None or cand[0] > best[0][0]:
                best = (cand, oid, oname, olat, olon, dkm, cb, cm)
        new_action = {"TOWN_CENTROID": "NEW_TOWN", "AREA_CENTROID": "NEW_AREA", "COUNTY_CENTROID": "NEW_COUNTY"}[pos]
        if best and best[0][1] == "ATTACH":
            (sc, act, sd), oid, oname, olat, olon, dkm, cb, cm = best
            rec.update(action=act, occ_id=oid, occ_name=oname, occ_dist_km=float(dkm), name_sim=round(sd, 2), comm_match=cm, occ_source=cb, lat=olat, lon=olon)
        else:
            # weak 'town name only' candidates are NOT attached (user decision 2026-10-15); kept as a note for review
            note = f"{best[1]}: {best[2]} ({best[5]} km)" if best else ""
            rec.update(action=new_action, lat=la, lon=lo, position_accuracy=pos, review_candidate=note)
    rows.append(rec)

# second pass for UNPLACED: the town is not a gazetteer place, but the FACILITY may already be an occurrence. Search by name inside the same state (MRDS comments carry
# 'Location: <county>, <State>, United States'; non-MRDS records have no state, so they need a unique name match plus commodity agreement). Strong matches only.
ST_NAME = {v: k.title() for k, v in STATES.items()}
by_id = {r["facility_id"]: r for r in rows}
agg_idx = agg.set_index("USGS Facility ID")
n_found = 0
for fid, rec in by_id.items():
    if rec["action"] != "UNPLACED" or not rec["st"]:
        continue
    row = agg_idx.loc[fid]
    ft = tokens(row["name"]) - tokens(row["town"])
    if not ft:
        ft = tokens(row["name"])
    if not ft:
        continue
    key = max(ft, key=len)
    fc = comm_set(row["commodities"])
    c.execute("""SELECT occurrence_id, name, lat, lon, created_by, commodities, comments FROM core.occurrences
                 WHERE is_active AND country_name = 'United States' AND created_by IS DISTINCT FROM 'migration_usgs_facilities_20261015' AND name ILIKE %s""", (f"%{key}%",))
    cands = []
    for oid, oname, olat, olon, cb, ocom, comm in c.fetchall():
        sd = sim(ft, tokens(oname) - tokens(row["town"]) or tokens(oname))
        cm = bool(fc & {str(x).lower() for x in (ocom or [])})
        in_state = bool(comm and re.search(r"Location: (?:[^,|]+, )?" + re.escape(ST_NAME[rec["st"]]) + r", United States", comm, re.I))
        if sd >= 0.9 and cm and (in_state or not (cb or "").startswith("migration_mrds")):
            cands.append((in_state, sd, oid, oname, olat, olon, cb, cm))
    if cands:
        # prefer an in-state MRDS match; accept a non-MRDS match only when it is the single candidate
        inst = [x for x in cands if x[0]]
        pick = (sorted(inst, reverse=True)[0] if inst else (cands[0] if len(cands) == 1 else None))
        if pick:
            _, sd, oid, oname, olat, olon, cb, cm = pick
            rec.update(action="ATTACH", occ_id=oid, occ_name=oname, occ_dist_km="", name_sim=round(sd, 2), comm_match=cm, occ_source=cb, lat=olat, lon=olon, town_match="state_name_match")
            n_found += 1
log("second pass: unplaced facilities attached by state+name match", n_found)

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False, encoding="utf-8-sig")
log("written", OUT)
print("\n=== action counts ===\n", out["action"].value_counts().to_string())
print("\n=== town match quality ===\n", out["town_match"].str.replace(r"\(.*\)", "(n)", regex=True).value_counts().to_string())
print("\n=== action by feature type ===\n", pd.crosstab(out["feature"], out["action"]).to_string())
a = out[out.action == "ATTACH"]
print("\nATTACH:", len(a), "| occurrence sources", a["occ_source"].value_counts().to_dict(), "| median dist km", a["occ_dist_km"].median(), "| with commodity agreement:", int(a["comm_match"].astype(bool).sum()))
print("\n=== ATTACH sample (weakest name similarity) ===")
print(a.sort_values("name_sim").head(10)[["name", "town_text", "occ_name", "occ_dist_km", "name_sim", "comm_match"]].to_string())
print("\n=== ATTACH sample (random) ===")
print(a.sample(min(8, len(a)), random_state=3)[["name", "town_text", "occ_name", "occ_dist_km", "name_sim", "comm_match"]].to_string())
print("\n=== new records that had a weak 'town name only' candidate (NOT attached; candidate kept in review_candidate) ===")
print(out[out.review_candidate != ""].shape[0], "facilities")
print(out[out.review_candidate != ""].head(6)[["name", "town_text", "review_candidate"]].to_string())
print("\n=== NEW_AREA (county-subdivision centre) sample ===")
print(out[out.action == "NEW_AREA"].head(10)[["name", "town_text", "gaz_place", "town_match"]].to_string())
print("\n=== NEW_COUNTY sample ===")
print(out[out.action == "NEW_COUNTY"].head(8)[["name", "town_text", "town_match"]].to_string())
print("\n=== UNPLACED ===")
print(out[out.action == "UNPLACED"][["name", "town_text", "st"]].head(30).to_string())
