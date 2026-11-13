"""Third placement pass for the USGS 2024 MYB facilities (2026-11-13, user OK: download GeoNames allCountries, place named-place rows only).

Rows still unplaced after myb2024_place.py / myb2024_place_extra_20261112.py whose location text names a specific place (village, locality,
industrial city, port, mine, deposit) that is not in cities500. Province-only and district-only rows are deliberately left unplaced
(user decision 2026-11-13: district centres too rough).

Matching, per row (first part of the location text, e.g. 'Oysu Village, Kutahya Province' -> 'Oysu'):
  * GeoNames allCountries features in the same country, classes P (populated), S (spot: mine, quarry, industrial area, port...), L, T, H,
    matched on name / asciiname / alternate names (folded, punctuation removed); a generic word (village, town, city, deposit...) is
    dropped from the place text if the full text has no hit.
  * the candidate's admin1 must match the USGS province by spelling (ratio >= 0.75 after dropping 'province', 'region' ...). If the USGS
    province matches no admin1 of the country at all (e.g. UK council areas are admin2), the whole country is searched instead.
  * all remaining candidates must lie within 25 km of each other, otherwise the row is left as ambiguous.
  * chosen point: populated place with the largest population, else a mine/quarry/industrial spot, else any.
Writes method TOWN, lat/lon and a detail line into myb2024_placement.csv (backup myb2024_placement_backup_20261113.csv first) and a review
CSV myb2024_gazetteer_matches_20261113.csv. Load afterwards with load_myb2024.py (it loads only facilities not yet loaded).
Usage: python -P myb2024_place_gazetteer_20261113.py [--dry]
"""
import collections, csv, difflib, math, re, shutil, sys, unicodedata

DRY = "--dry" in sys.argv
GN = "D:/CriticalMineralsDB/World/geonames_20261113"
W = "D:/CriticalMineralsDB/World/usgs_facilities_20261110"
PL = f"{W}/myb2024_placement.csv"
MAXSPREAD_KM = 25
# features too large (or too linear) for one point to stand for a facility: peninsulas, ranges, plains, deserts, valleys, salt flats,
# regions/areas, rivers (GeoNames gives the mouth), island groups; also churches (matched a municipality name: Sunndal -> 'Hov' church)
TOO_BIG = {"T.PEN", "T.MTS", "T.HLLS", "T.PLN", "T.PLAT", "T.DSRT", "T.VAL", "T.UPLD", "T.ISLS", "T.RDGE", "T.MSTS", "L.AREA", "L.RGN",
           "L.SALT", "L.RGNE", "L.TRB", "L.PRK", "L.RESF", "L.RESN", "L.FRST", "L.OILF", "L.GASF", "L.MNA", "H.STM", "H.STMI", "H.STMX",
           "H.STMH", "H.WAD", "H.WADX", "H.CNL", "H.BGHS", "H.SALT", "H.LKS", "H.SEA", "H.GULF", "H.SD", "S.CH"}
# reviewed 2026-11-13 in the dry run: wrong feature (regional name hit a farm/reservoir/headland) or island too large for one point
REJECT = {("RU", "lovozerskoye deposit"), ("ZA", "waterberg"), ("LV", "kurzeme"), ("NO", "sunnfjord"), ("NO", "tana"), ("JP", "kurosaki"),
          ("CA", "baffin island"), ("GR", "euboea island"), ("AU", "groote eylandt"), ("IR", "qeshm island"), ("ID", "bintan"),
          ("ZM", "kapiri")}


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return "".join(ch for ch in s if not unicodedata.combining(ch))


norm = lambda s: re.sub(r"[^a-z0-9]", "", fold(s))
ADM_WORDS = r"\b(province|provincia|region|regional|state|county|governorate|oblast|oblysy|kray|krai|republic|department|departamento|prefecture|" \
            r"territory|emirate|voivodeship|canton|aymag|aimag|wilaya|division|autonomous|viloyati|viloyat|il|ili|municipality|metropolitan|city|" \
            r"of|the|and|special|capital|district|land|council|area|england|scotland|wales)\b"
admn = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(ADM_WORDS, " ", fold(s)))
ADM1_RX = r"\b(State|Province|Region|County|Kray|Krai|Oblast|Governorate|Department|Prefecture|Republic|Territory|Emirate|Voivodeship|Canton|Aymag|Wilaya|Division|Regional State|Autonomous)\b"
ADM2_RX = r"(?i)\b(District|Municipality|Raion|Rayon|Okrug|Municipio|Commune|Council Area|Shire|Borough|Tehsil|Taluk|Regency|Kabupaten|region)\b"
GENERIC = r"\b(village|town|city|industrial city|industrial area|industrial zone|industrial estate|free zone|port|deposit|deposits|field|area|" \
          r"settlement|township|mine|mines|quarry|quarries|plant|works|complex|near|vicinity of|outskirts of)\b"


def kind(loc):
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if not parts: return "empty"
    if len(parts) == 1 and re.search(ADM1_RX, parts[0]): return "province_only"
    if re.search(ADM2_RX, parts[0]): return "district"
    if re.search(ADM1_RX, parts[0]): return "province_only"
    return "named_place"


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


rows = list(csv.DictReader(open(PL, encoding="utf-8", newline=""))); cols = list(rows[0].keys())
todo = []
for r in rows:
    if r["method"] or not r["iso2"] or kind(r["location"] or "") != "named_place": continue
    first = re.split(r"[,;()]| and | near ", r["location"])[0].strip()
    if (r["iso2"], fold(first)) in REJECT: continue
    keys = [norm(first)]
    g2 = norm(re.sub(r"\s+", " ", re.sub(GENERIC, " ", fold(first))).strip())
    if g2 and g2 != keys[0]: keys.append(g2)
    keys = [k for k in keys if len(k) >= 3]
    if keys: todo.append((r, first, keys))
want = {(r["iso2"], k) for r, _, ks in todo for k in ks}
isos = {r["iso2"] for r, _, _ in todo}
print("rows to try", len(todo), "| countries", len(isos), "| name keys", len(want))

adm1 = collections.defaultdict(dict)  # iso2 -> code -> {normalised names}
for line in open(f"{GN}/admin1CodesASCII.txt", encoding="utf-8"):
    code, name, ascii_, _ = line.rstrip("\n").split("\t"); iso, a = code.split(".", 1)
    adm1[iso][a] = {admn(name), admn(ascii_)}

cand = collections.defaultdict(list)  # (iso2, key) -> [(fclass, fcode, adm1, pop, name, lat, lon, gid)]
n = 0
with open(f"{GN}/allCountries.txt", encoding="utf-8") as fh:
    for line in fh:
        n += 1
        p = line.split("\t", 15)
        if p[8] not in isos or p[6] not in ("P", "S", "L", "T", "H"): continue
        if f"{p[6]}.{p[7]}" in TOO_BIG: continue
        names = {p[1], p[2]} | (set(p[3].split(",")) if p[3] else set())
        rec = None
        for nm in names:
            k = (p[8], norm(nm))
            if k in want:
                rec = rec or (p[6], p[7], p[10], int(p[14] or 0), p[1], float(p[4]), float(p[5]), p[0])
                if rec not in cand[k]: cand[k].append(rec)
print("gazetteer lines read", n, "| keys with hits", len(cand))


def rank(c):
    if c[0] == "P": return (0, -c[3])
    if c[0] == "S" and re.match(r"(MN|MNQ|MNAU|MNC|MNCU|MNFE|MNN|QRY|MFG|MFGC|MFGM|MLWTR|INDS|PRT|RFY|SMLT)", c[1] or ""): return (1, 0)
    return (2, 0)


out, placed = [], 0
for r, first, keys in todo:
    hits = []
    for k in keys:
        hits = cand.get((r["iso2"], k), [])
        if hits: break
    res = "no gazetteer match"; best = None
    if hits:
        a_want = admn(r["adm1"]) if r["adm1"] else ""
        a_codes = adm1.get(r["iso2"], {})
        ok_codes = {code for code, nms in a_codes.items() if a_want and max([difflib.SequenceMatcher(None, a_want, x).ratio() for x in nms if x] + [0]) >= 0.75}
        if ok_codes:
            pool = [h for h in hits if h[2] in ok_codes]; scope = "province"
        else:
            pool = hits; scope = "country (province name not matched)"
        if not pool:
            res = f"hits only in other provinces ({len(hits)})"
        else:
            spread = max((km(a[5:7], b[5:7]) for a in pool for b in pool), default=0)
            if spread > MAXSPREAD_KM:
                res = f"ambiguous: {len(pool)} candidates {spread:.0f} km apart ({scope})"
            else:
                best = min(pool, key=rank)
                res = f"placed ({scope}; {len(pool)} candidate(s) within {spread:.0f} km)"
    if best:
        placed += 1
        r.update(method="TOWN", lat=str(best[5]), lon=str(best[6]),
                 detail=f"GeoNames allCountries '{best[4]}' ({best[7]}, {best[0]}.{best[1]}) for '{first}', {res} (placed 2026-11-13)")
    out.append([r["fid"], r["name"], r["country"], r["adm1"], r["location"], first, res,
                best[4] if best else "", f"{best[0]}.{best[1]}" if best else "", best[3] if best else "", best[5] if best else "", best[6] if best else ""])

with open(f"{W}/myb2024_gazetteer_matches_20261113{'_DRY' if DRY else ''}.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["fid", "name", "country", "adm1", "location", "place_text", "result", "geonames_name", "feature", "population", "lat", "lon"]); w.writerows(out)
print("placed", placed, "of", len(todo))
print(collections.Counter(re.sub(r"\(.*|:.*|\d+", "", x[6]).strip() for x in out).most_common())
if not DRY:
    shutil.copy(PL, PL.replace(".csv", "_backup_20261113.csv"))
    with open(PL, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print("written", PL, "| rows", len(rows), "| Namibia NA kept:", sum(1 for r in rows if r["iso2"] == "NA"))
