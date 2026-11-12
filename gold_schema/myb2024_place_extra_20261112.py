"""Second placement pass for the USGS 2024 MYB facilities (2026-11-12, user OK 'Load the 17'): places only rows left unplaced by
myb2024_place.py that can be placed safely:
  (a) the town name exists in several provinces and the stated province matches exactly one of them by fuzzy name (ratio >= 0.75)
      - USGS spells provinces differently from GeoNames (Saint Gallen / Sankt Gallen, Mangghystau / Mangistauskaya ...);
  (b) explicit aliases for places GeoNames lists under another name: Puerto Ordaz -> Ciudad Guayana (VE), Kalgoorlie Boulder Township ->
      Kalgoorlie (AU).
Writes method TOWN, lat/lon and a detail line into myb2024_placement.csv (backup myb2024_placement_backup_20261112b.csv first).
Usage: python -P myb2024_place_extra_20261112.py [--dry]
"""
import collections, csv, difflib, re, shutil, sys, unicodedata

DRY = "--dry" in sys.argv
GN = "D:/CriticalMineralsDB/World/geonames_20261111"
PL = "D:/CriticalMineralsDB/World/usgs_facilities_20261110/myb2024_placement.csv"


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return "".join(ch for ch in s if not unicodedata.combining(ch))


STOP = r"\b(mine|mines|plant|plants|smelter|refinery|refineries|works|quarry|quarries|deposit|project|operation|operations|complex|facility|factory|company|co|ltd|the|and|of|no|site|open|pit|underground|mining|beneficiation|concentrator|mill|field|fields)\b"
norm = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", fold(s)))
adm1name = {}
for line in open(f"{GN}/admin1CodesASCII.txt", encoding="utf-8"):
    code, name, ascii_, _ = line.rstrip("\n").split("\t"); adm1name[code] = {norm(name), norm(ascii_)}
towns = collections.defaultdict(list); byid = {}
for line in open(f"{GN}/extracted/cities500.txt", encoding="utf-8"):
    p = line.rstrip("\n").split("\t")
    rec = (p[10], int(p[14] or 0), p[1], float(p[4]), float(p[5]), p[0])   # adm1, pop, name, lat, lon, geonameid
    byid[p[0]] = rec
    for nm in {p[1], p[2]} | (set(p[3].split(",")) if p[3] else set()):
        k = norm(nm)
        if len(k) >= 3: towns[(p[8], k)].append(rec)

# explicit aliases: (iso2, location prefix) -> GeoNames town name to look up in that country
ALIAS = {("VE", "puerto ordaz"): "Ciudad Guayana", ("AU", "kalgoorlie boulder township"): "Kalgoorlie"}

rows = list(csv.DictReader(open(PL, encoding="utf-8", newline=""))); cols = list(rows[0].keys())
placed = []
for r in rows:
    if r["method"] or not r["iso2"]: continue
    loc = r["location"] or ""; first = re.split(r"[,;()]| and ", loc)[0].strip()
    al = ALIAS.get((r["iso2"], fold(first)))
    if al:
        hits = towns.get((r["iso2"], norm(al)))
        if hits:
            best = max(hits, key=lambda h: h[1])
            r.update(method="TOWN", lat=str(best[3]), lon=str(best[4]), detail=f"GeoNames '{best[2]}' ({best[5]}) for '{first}' (alias, placed 2026-11-12)")
            placed.append((r["fid"], r["country"], loc, best[2], "alias")); continue
    hits = towns.get((r["iso2"], norm(first)))
    if not hits or not r["adm1"] or len({h[0] for h in hits}) <= 1: continue
    want = norm(r["adm1"])
    scored = [(max([difflib.SequenceMatcher(None, want, a).ratio() for a in adm1name.get(f"{r['iso2']}.{h[0]}", set())] + [0]), h) for h in hits]
    good = [x for x in scored if x[0] >= 0.75]
    if good and len({x[1][0] for x in good}) == 1:
        best = max(good, key=lambda x: x[1][1])[1]
        r.update(method="TOWN", lat=str(best[3]), lon=str(best[4]), detail=f"GeoNames '{best[2]}' ({best[5]}) from '{first}', province matched by spelling to '{r['adm1']}' (placed 2026-11-12)")
        placed.append((r["fid"], r["country"], loc, best[2], f"adm1 {max(x[0] for x in good):.2f}"))
for p in placed: print(p)
print("placed", len(placed))
if not DRY:
    shutil.copy(PL, PL.replace(".csv", "_backup_20261112b.csv"))
    with open(PL, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print("written", PL, "| rows", len(rows), "| Namibia NA kept:", sum(1 for r in rows if r["iso2"] == "NA"))
