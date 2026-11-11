"""Read-only placement of the USGS 2024 Minerals Yearbook vol. III facilities (doi:10.5066/P1KEQASH, CC0; no coordinates in the table).
For each USGS facility (one id, many commodity rows) decide, in this order:
  1 OCC    an existing occurrence in the same country with the same (normalised) name - generic names ('Plant in X', 'Mines in X') never match
  2 REG    the facility matched to a point of the USGS regional GIS compilations (myb2024_match_coords.py) whose loaded occurrence we can find
  3 TOWN   the first place name in 'Location Description' found in GeoNames cities500 (CC BY 4.0) in that country (and province, when given);
           the most populous of several same-name places in the province; position_accuracy TOWN_CENTROID
  4 NONE   only a province or nothing usable -> not placed (not loaded)
Writes D:/CriticalMineralsDB/World/usgs_facilities_20261110/myb2024_placement.csv and prints rates. Usage: python -P myb2024_place.py
"""
import collections, csv, difflib, os, re, unicodedata
import pandas as pd, psycopg2

W = "D:/CriticalMineralsDB/World/usgs_facilities_20261110"
GN = "D:/CriticalMineralsDB/World/geonames_20261111"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return "".join(ch for ch in s if not unicodedata.combining(ch))


STOP = r"\b(mine|mines|plant|plants|smelter|refinery|refineries|works|quarry|quarries|deposit|project|operation|operations|complex|facility|factory|" \
       r"company|co|ltd|the|and|of|no|site|open|pit|underground|mining|beneficiation|concentrator|mill|field|fields)\b"
norm = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", fold(s)))
GENERIC = re.compile(r"(?i)^\s*(plant|plants|mine|mines|quarry|quarries|multiple|several|various|smelter|refinery|works|facility|facilities|unspecified|site|sites|kiln|kilns|steel plant|cement plant)\b.*\b(in|at|near|of)\b")

# ---------------------------------------------------------------- MYB table -> facilities
f = pd.read_csv(f"{W}/myb2024/2024MYBv3_Facilities_table.csv", dtype=str, encoding="utf-8-sig")   # UTF-8 with BOM (latin-1 garbles accents)
fac = f.groupby("USGS Facility ID").agg(name=("Facility Name", "first"), country=("Country (Short Form) or Locality", "first"),
                                         loc=("Location Description", "first"), adm1=("First-Level Administrative Division Name", "first"),
                                         ftype=("Feature Type", "first")).reset_index().rename(columns={"USGS Facility ID": "fid"})
fac = fac.astype(object).where(fac.notna(), None)

# ---------------------------------------------------------------- country codes
ci = {}
for line in open(f"{GN}/countryInfo.txt", encoding="utf-8"):
    if line.startswith("#"): continue
    p = line.rstrip("\n").split("\t")
    if len(p) > 4: ci[fold(p[4])] = p[0]
ALIAS = {"burma": "MM", "congo (kinshasa)": "CD", "congo (brazzaville)": "CG", "republic of korea": "KR", "korea, south": "KR", "korea, north": "KP",
         "north korea": "KP", "south korea": "KR", "russia": "RU", "iran": "IR", "syria": "SY", "laos": "LA", "vietnam": "VN", "czechia": "CZ",
         "turkey": "TR", "turkiye": "TR", "bahamas, the": "BS", "gambia, the": "GM", "cote d'ivoire": "CI", "côte d'ivoire": "CI", "eswatini": "SZ",
         "north macedonia": "MK", "macedonia": "MK", "moldova": "MD", "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ", "taiwan": "TW",
         "brunei": "BN", "timor-leste": "TL", "east timor": "TL", "kosovo": "XK", "palestine": "PS", "micronesia": "FM", "cabo verde": "CV",
         "west bank": "PS", "united states": "US", "united kingdom": "GB", "netherlands": "NL", "kyrgyzstan": "KG"}
iso = lambda name: ALIAS.get(fold(name)) or ci.get(fold(name))

# ---------------------------------------------------------------- GeoNames towns by (country, folded name) incl. ascii + alternate names
adm1name = {}
for line in open(f"{GN}/admin1CodesASCII.txt", encoding="utf-8"):
    code, name, ascii_, _ = line.rstrip("\n").split("\t")
    adm1name[code] = {norm(name), norm(ascii_)}
towns = collections.defaultdict(list)
with open(f"{GN}/extracted/cities500.txt", encoding="utf-8") as fh:
    for line in fh:
        p = line.rstrip("\n").split("\t")
        names = {p[1], p[2]} | (set(p[3].split(",")) if p[3] else set())
        rec = (float(p[4]), float(p[5]), p[8], p[10], int(p[14] or 0), p[1])   # lat, lon, cc, admin1, population, name
        for nm in names:
            k = norm(nm)
            if len(k) >= 3: towns[(p[8], k)].append(rec)

PROV = r"\b(province|provinces|state|oblast|region|regions|department|prefecture|county|district|municipality|governorate|territory|republic|" \
       r"krai|kray|okrug|autonomous|division|canton|voivodeship|wilaya|emirate|parish|area|city|of|the|near|about|approximately|km|kilometers|" \
       r"north|south|east|west|northeast|northwest|southeast|southwest|northern|southern|eastern|western|central)\b"


def place_town(loc, cc, adm1):
    if not loc or not cc: return None
    want_adm = norm(adm1) if adm1 else None
    for part in re.split(r"[,;()]| and ", loc):
        part = part.strip()
        if not part or re.search(r"(?i)\b(province|state|oblast|region|prefecture|governorate|department|county|territory|krai|kray|district|division|emirate|voblasts'?|municipality|canton|voivodeship|wojewodztwo|wilaya|okrug|republic|regency|aimag|velayat|viloyati?)\b\s*$", part):
            continue
        cand = re.sub(r"\s+", " ", re.sub(PROV, " ", fold(part))).strip()
        for key in (norm(part), norm(cand)):
            hits = towns.get((cc, key)) if key and len(key) >= 3 else None
            if not hits: continue
            if want_adm:
                inprov = [h for h in hits if want_adm in adm1name.get(f"{cc}.{h[3]}", set()) or any(want_adm in a or a in want_adm for a in adm1name.get(f"{cc}.{h[3]}", set()) if a)]
                if inprov: hits = inprov
                elif len({h[3] for h in hits}) > 1: continue          # same name in several provinces, none is the stated one: ambiguous
            best = max(hits, key=lambda h: h[4])
            return best[0], best[1], best[5], part
    return None


# ---------------------------------------------------------------- existing occurrences and regional matches
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'"); JI = dict(c.fetchall())
occ = collections.defaultdict(lambda: collections.defaultdict(list))
c.execute("""SELECT o.occurrence_id, o.name, j.iso_code FROM core.occurrences o JOIN core.jurisdictions j ON j.jurisdiction_id = o.jurisdiction_id
             WHERE o.is_active AND j.level = 'COUNTRY'""")
for oid, nm, cc in c.fetchall():
    k = norm(nm)
    if len(k) >= 4: occ[cc][k].append(oid)
reg = pd.read_csv(f"{W}/myb2024_facility_positions.csv", dtype=str).set_index("facility_id")
c.execute("SELECT source_id, entity_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system LIKE 'USGS_%' AND source_id LIKE 'fac:%'")
regocc = {}
for sid, oid in c.fetchall():
    for u in sid[4:].split("#")[0].split("+"): regocc.setdefault(u, oid)

out, how = [], collections.Counter()
for r in fac.itertuples():
    cc = iso(r.country); method = lat = lon = oid = None; detail = ""
    if r.country and fold(r.country) == "united states": how["US (skipped)"] += 1; continue
    k = norm(r.name)
    if cc and k and len(k) >= 4 and not GENERIC.match(r.name or ""):
        ids = occ.get(cc, {}).get(k)
        if ids and len(set(ids)) == 1: method, oid, detail = "OCC", ids[0], "same name in country"
    if method is None and r.fid in reg.index and isinstance(reg.at[r.fid, "regional_uid"], str):
        ro = regocc.get(reg.at[r.fid, "regional_uid"])
        if ro: method, oid, detail = "REG", ro, f"regional {reg.at[r.fid, 'region']} {reg.at[r.fid, 'regional_uid']}"
    if method is None:
        t = place_town(r.loc, cc, r.adm1)
        if t: method, (lat, lon), detail = "TOWN", t[:2], f"GeoNames '{t[2]}' from '{t[3]}'"
    how[method or ("NONE (no country code)" if not cc else "NONE")] += 1
    out.append([r.fid, r.name, r.country, cc, r.adm1, r.loc, r.ftype, method or "", oid, lat, lon, detail])
pd.DataFrame(out, columns=["fid", "name", "country", "iso2", "adm1", "location", "feature_type", "method", "occurrence_id", "lat", "lon", "detail"]) \
  .to_csv(f"{W}/myb2024_placement.csv", index=False, encoding="utf-8")
print(dict(how), "of", len(fac))
df = pd.DataFrame(out, columns=["fid", "name", "country", "iso2", "adm1", "location", "ftype", "method", "oid", "lat", "lon", "detail"])
print("unplaced by country (top 20):", df[df.method == ""].country.value_counts().head(20).to_dict())
print("no iso code:", sorted(set(df[df.iso2.isna()].country)))
