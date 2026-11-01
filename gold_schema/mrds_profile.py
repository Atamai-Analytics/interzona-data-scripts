"""READ-ONLY profile of USGS MRDS (mrds.csv) against interzona_cm: overlap with existing occurrences and mapping coverage."""
import csv, re, os, collections, sys
import numpy as np
import psycopg2
from scipy.spatial import cKDTree

csv.field_size_limit(10**8)
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
R = []
with open(r"D:\CriticalMineralsDB\mrds.csv", encoding="utf-8", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        R.append(r)
print("MRDS records", len(R))


def fnum(x):
    try: return float(x)
    except Exception: return None


for r in R:
    r["_lat"] = fnum(r["latitude"]); r["_lon"] = fnum(r["longitude"])
bad = [r for r in R if r["_lat"] is None or r["_lon"] is None or not (-90 <= r["_lat"] <= 90) or not (-180 <= r["_lon"] <= 180)]
zero = [r for r in R if r["_lat"] == 0 and r["_lon"] == 0]
print("coordinate problems: missing/out of range", len(bad), "| 0,0", len(zero))
good = [r for r in R if r not in bad] if len(bad) < 1000 else R
good = [r for r in R if r["_lat"] is not None and r["_lon"] is not None and -90 <= r["_lat"] <= 90 and -180 <= r["_lon"] <= 180 and not (r["_lat"] == 0 and r["_lon"] == 0)]
print("usable coordinates", len(good))


def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]) * 6371000.0


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def tokens(s):
    return {t for t in norm(s).split() if len(t) > 2 and t not in {"mine", "the", "and", "prospect", "claim", "claims", "group", "mines", "property", "deposit", "quarry", "pit"}}


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT occurrence_id, name, country_name, lat, lon, created_by FROM core.occurrences")
G = c.fetchall()
tree = cKDTree(xyz(np.array([r["_lat"] for r in good]), np.array([r["_lon"] for r in good])))
gx = xyz(np.array([x[3] for x in G]), np.array([x[4] for x in G]))
res = {}
for label, rad in (("500 m", 500), ("2 km", 2000)):
    res[label] = tree.query_ball_point(gx, rad)
print("\n== OVERLAP: gold occurrences with an MRDS record nearby")
grp = lambda cb: "Argentina SIGAM" if cb == "AtamaiAdmin" else "Washington DGER" if cb.startswith("migration_wa_") else "other"
stats = collections.defaultdict(lambda: collections.Counter())
for gi, x in enumerate(G):
    k = grp(x[5]); stats[k]["gold"] += 1
    near500 = res["500 m"][gi]; near2k = res["2 km"][gi]
    if near500: stats[k]["any_500m"] += 1
    if near2k: stats[k]["any_2km"] += 1
    gt = tokens(x[1])
    if gt and any(gt & tokens(good[j]["site_name"]) for j in near2k): stats[k]["name_match_2km"] += 1
    if norm(x[1]) and any(norm(x[1]) == norm(good[j]["site_name"]) for j in near2k): stats[k]["exact_name_2km"] += 1
for k, v in stats.items(): print(f"  {k:18s}", dict(v))
# MRDS records inside Washington / Argentina vs gold
for lab, key, col in (("Washington", "state", "Washington"), ("Argentina", "country", "Argentina")):
    ms = [r for r in R if r[key] == col]
    print(f"MRDS records with {key}={col}:", len(ms))
# reverse: MRDS records that have a gold occurrence within 500 m / 2 km
gt_tree = cKDTree(gx)
mx = xyz(np.array([r["_lat"] for r in good]), np.array([r["_lon"] for r in good]))
d, idx = gt_tree.query(mx, k=1)
near = d <= 500; near2 = d <= 2000
print("\nMRDS records within 500 m of ANY gold occurrence:", int(near.sum()), "| within 2 km:", int(near2.sum()), "of", len(good))
byc = collections.Counter(); byc_tot = collections.Counter()
for r, n2 in zip(good, near2):
    byc_tot[r["country"]] += 1
    if n2: byc[r["country"]] += 1
print("by country (within 2 km / total):", [(k, byc[k], byc_tot[k]) for k, _ in byc_tot.most_common(12) if byc[k]])

print("\n== COUNTRIES")
c.execute("SELECT name, iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'")
J = {norm(n): (n, i, j) for n, i, j in c.fetchall()}
cn = collections.Counter(r["country"] for r in R)
ALIAS = {"russia": "russian federation", "viet nam": "vietnam", "vietnam": "viet nam", "ivory coast": "cote d ivoire", "south korea": "korea republic of", "north korea": "korea democratic people s republic of", "iran": "iran islamic republic of", "bolivia": "bolivia plurinational state of", "venezuela": "venezuela bolivarian republic of", "tanzania": "tanzania united republic of", "syria": "syrian arab republic", "laos": "lao people s democratic republic", "congo (kinshasa)": "congo democratic republic of the", "taiwan": "taiwan province of china", "moldova": "moldova republic of"}
miss = [(k, v) for k, v in cn.most_common() if norm(k) not in J and norm(ALIAS.get(norm(k), "")) not in J]
print("countries total", len(cn), "| matched exactly or by alias", len(cn) - len(miss), "| unmatched", len(miss), "records", sum(v for _, v in miss)); print("unmatched list:", miss[:40])

print("\n== COMMODITIES")
c.execute("SELECT commodity_name, commodity_id FROM core.commodities")
CM = {norm(n): i for n, i in c.fetchall()}
vals = collections.Counter()
for r in R:
    for fld in ("commod1", "commod2", "commod3"):
        v = r[fld].strip()
        if v: vals[v] += 1
print("distinct commodity field values:", len(vals), "| total mentions", sum(vals.values()))
KNOWN_COMMA = ["Sand and Gravel, Construction", "Sand and Gravel, Industrial", "Stone, Crushed/Broken", "Stone, Dimension/Building", "Stone, Dimension", "Stone, Crushed", "Clay, Common", "Clay, Fire", "Rare Earths"]
tok = collections.Counter(); multi = 0
for v, n in vals.items():
    t = v
    for kc in KNOWN_COMMA: t = t.replace(kc, kc.replace(", ", "@@"))
    for p in [x.strip().replace("@@", ", ") for x in t.split(",")]:
        if p: tok[re.sub(r"\s*-[^-]*$", "", p) if re.search(r"-\w", p) and not re.match(r"^[A-Za-z ]+-[A-Za-z]+$", p) else p] += n
print("tokens after splitting:", len(tok)); top = tok.most_common(30)
matched = {k: v for k, v in tok.items() if norm(k) in CM}
print("matched to gold by name:", len(matched), "tokens covering", sum(matched.values()), "of", sum(tok.values()), "mentions")
unm = [(k, v) for k, v in tok.most_common() if norm(k) not in CM]
print("top unmatched tokens:", unm[:40])

print("\n== CODE FIELDS")
for fld in ("dev_stat", "oper_type", "work_type", "dep_type", "com_type", "score", "prod_size"):
    cc = collections.Counter(r[fld] for r in R); print(fld, len(cc), cc.most_common(10))
mm = collections.Counter()
for r in R:
    for m in re.findall(r"\{([^}]*)\}", r["model"]): mm[re.sub(r"\s+\S*$", "", m.strip()) if False else m.strip()] += 1
print("model values (braces):", len(mm), mm.most_common(8))
c.execute("SELECT count(*) FROM core.occurrence_types"); print("gold occurrence_types", c.fetchone())
print("\n== QUALITY")
dupe = collections.Counter((norm(r["site_name"]), round(r["_lat"], 3), round(r["_lon"], 3)) for r in good)
print("MRDS exact duplicates (same name and ~100 m): records in duplicate groups", sum(v for v in dupe.values() if v > 1), "groups", sum(1 for v in dupe.values() if v > 1))
print("no name:", sum(1 for r in R if not norm(r["site_name"])), "| unnamed or 'unnamed'/'unknown' names:", sum(1 for r in R if norm(r["site_name"]) in ("unnamed", "unknown", "no name", "")))
print("with year first production:", sum(1 for r in R if r["yr_fst_prd"].strip()), "| ore field:", sum(1 for r in R if r["ore"].strip()), "| gangue:", sum(1 for r in R if r["gangue"].strip()), "| hrock_type:", sum(1 for r in R if r["hrock_type"].strip()))
