"""READ-ONLY: draft MRDS commodity crosswalk + how many records would load after de-duplication."""
import csv, re, os, collections
import numpy as np
import psycopg2
from scipy.spatial import cKDTree

csv.field_size_limit(10**8)
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
R = list(csv.DictReader(open(r"D:\CriticalMineralsDB\mrds.csv", encoding="utf-8", errors="replace", newline="")))
fnum = lambda x: float(x) if x not in ("", "NA", None) else None
for r in R:
    try: r["_lat"] = fnum(r["latitude"]); r["_lon"] = fnum(r["longitude"])
    except Exception: r["_lat"] = r["_lon"] = None
good = [r for r in R if r["_lat"] is not None and r["_lon"] is not None and -90 <= r["_lat"] <= 90 and -180 <= r["_lon"] <= 180 and not (r["_lat"] == 0 and r["_lon"] == 0)]

ELEM = {"Hydrogen": "H", "Helium": "He", "Lithium": "Li", "Beryllium": "Be", "Boron": "B", "Carbon": "C", "Nitrogen": "N", "Oxygen": "O", "Fluorine": "F", "Sodium": "Na", "Magnesium": "Mg", "Aluminum": "Al", "Silicon": "Si",
        "Phosphorus": "P", "Sulfur": "S", "Chlorine": "Cl", "Potassium": "K", "Calcium": "Ca", "Scandium": "Sc", "Titanium": "Ti", "Vanadium": "V", "Chromium": "Cr", "Manganese": "Mn", "Iron": "Fe", "Cobalt": "Co", "Nickel": "Ni",
        "Copper": "Cu", "Zinc": "Zn", "Gallium": "Ga", "Germanium": "Ge", "Arsenic": "As", "Selenium": "Se", "Bromine": "Br", "Rubidium": "Rb", "Strontium": "Sr", "Yttrium": "Y", "Zirconium": "Zr", "Niobium": "Nb", "Molybdenum": "Mo",
        "Ruthenium": "Ru", "Rhodium": "Rh", "Palladium": "Pd", "Silver": "Ag", "Cadmium": "Cd", "Indium": "In", "Tin": "Sn", "Antimony": "Sb", "Tellurium": "Te", "Iodine": "I", "Cesium": "Cs", "Barium": "Ba", "Lanthanum": "La",
        "Cerium": "Ce", "Praseodymium": "Pr", "Neodymium": "Nd", "Samarium": "Sm", "Europium": "Eu", "Gadolinium": "Gd", "Terbium": "Tb", "Dysprosium": "Dy", "Holmium": "Ho", "Erbium": "Er", "Thulium": "Tm", "Ytterbium": "Yb",
        "Lutetium": "Lu", "Hafnium": "Hf", "Tantalum": "Ta", "Tungsten": "W", "Rhenium": "Re", "Osmium": "Os", "Iridium": "Ir", "Platinum": "Pt", "Gold": "Au", "Mercury": "Hg", "Thallium": "Tl", "Lead": "Pb", "Bismuth": "Bi",
        "Thorium": "Th", "Uranium": "U", "Radium": "Ra", "Promethium": "Pm"}
CURATED = {  # token -> gold commodity_name (guess for review)
 "Sand and Gravel, Construction": "Sand and Gravel", "Sand and Gravel, Industrial": "Silica Sand", "Stone, Crushed/Broken": "Crushed Rock", "Stone": "Crushed Rock", "Stone, Dimension": "Miscellaneous Dimension Stones",
 "Dimension": "Miscellaneous Dimension Stones", "Stone, Dimension/Building": "Miscellaneous Dimension Stones", "Barium-Barite": "Baryte", "Fluorine-Fluorite": "Fluorite", "Phosphorus-Phosphates": "Phosphate Rock", "Gypsum-Anhydrite": "Gypsum",
 "Talc-Soapstone": "Talc", "Fire Clay (Refractory)": "White Firing Clay", "Silica": "SiO2", "Platinum-Group Metals": "PGE", "Rare Earths": "REE", "Rare Earths-Rare Earth Oxides": "Rare Earth Oxide", "Coal": "Coal", "Peat": "Peat", "Limestone": "Limestone", "Clay": "Clay", "Clay, Common": "Clay",
 "Granite": "Granite", "Sandstone": "Sandstone", "Slate": "Slate", "Marble": "Marble", "Basalt": "Basalt", "Diatomite": "Diatomite", "Perlite": "Perlite", "Pumice": "Pumice", "Zeolites": "Zeolite", "Mica": "Mica", "Feldspar": "Feldspar", "Garnet": "Garnet",
 "Graphite": "Graphite", "Asbestos": "Asbestos", "Salt": "Salt", "Potash": "Potash", "Bauxite": "Bauxite", "Bentonite": "Bentonite", "Kaolin": "Kaolin", "Vermiculite": "Vermiculite", "Wollastonite": "Wollastonite", "Diamond": "Diamond", "Lime": "Lime", "Magnesite": "MgCO3",
 "Titanium-Ilmenite": "Ilmenite", "Titanium-Rutile": "Rutile", "Zirconium-Zircon": "Zircon", "Aluminum-Bauxite": "Bauxite", "Iron-Magnetite": "Magnetite", "Iron-Hematite": "Hematite", "Molybdenum-Molybdenite": "Molybdenite", "Chromium-Chromite": "Chromite", "Sulfur-Pyrite": "Pyrite",
 "Fluorspar": "Fluorite", "Barite": "Baryte", "Thorium": "Th", "Uranium": "U",
}
KNOWN_COMMA = sorted(["Sand and Gravel, Construction", "Sand and Gravel, Industrial", "Stone, Crushed/Broken", "Stone, Dimension/Building", "Stone, Dimension", "Stone, Crushed", "Clay, Common", "Clay, Fire"], key=len, reverse=True)
tok = collections.Counter()
for r in R:
    for f in ("commod1", "commod2", "commod3"):
        v = r[f].strip()
        if not v: continue
        t = v
        for kc in KNOWN_COMMA: t = t.replace(kc, kc.replace(", ", "@@"))
        for p in [x.strip().replace("@@", ", ") for x in t.split(",")]:
            if p: tok[p] += 1
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = True
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT commodity_name, commodity_id FROM core.commodities"); GN = {n.lower(): i for n, i in c.fetchall()}
how = collections.Counter(); mapped = {}; unmapped = []
for t, n in tok.most_common():
    base = t.split("-")[0].strip()
    if t in CURATED and CURATED[t].lower() in GN: mapped[t] = (CURATED[t], "curated", n)
    elif base in ELEM and ELEM[base].lower() in GN: mapped[t] = (ELEM[base], "element", n)
    elif t.lower() in GN: mapped[t] = (t, "exact name", n)
    elif base.lower() in GN: mapped[t] = (base, "base name", n)
    else: unmapped.append((t, n))
tot = sum(tok.values()); m = sum(v[2] for v in mapped.values())
print("commodity tokens", len(tok), "| mentions", tot, "| auto-mapped tokens", len(mapped), "covering", m, f"({100*m/tot:.1f}%) | unmapped tokens", len(unmapped), "mentions", tot - m)
by = collections.Counter(); [by.update({v[1]: v[2]}) for v in mapped.values()]; print("mapped mentions by method", dict(by))
print("UNMAPPED (top 45):", unmapped[:45])
print("curated/base guesses to review:", [(t, v[0], v[2]) for t, v in mapped.items() if v[1] in ("curated", "base name")][:30])

# ------ de-duplication sizing
def norm(s): return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
STOP = {"mine", "the", "and", "prospect", "claim", "claims", "group", "mines", "property", "deposit", "quarry", "pit", "unnamed", "unknown", "no", "name"}
tokens = lambda s: {t for t in norm(s).split() if len(t) > 2 and t not in STOP}
def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]) * 6371000.0
c.execute("SELECT occurrence_id, name, lat, lon FROM core.occurrences"); G = c.fetchall()
gx = xyz(np.array([x[2] for x in G]), np.array([x[3] for x in G])); gtree = cKDTree(gx)
mx = xyz(np.array([r["_lat"] for r in good]), np.array([r["_lon"] for r in good]))
near = gtree.query_ball_point(mx, 1000)
dup_gold = []
for r, nb in zip(good, near):
    flag = False
    for j in nb:
        d = np.linalg.norm(mx[good.index(r)] - gx[j]) if False else None
    dup_gold.append(nb)
# distance-aware duplicate rule against gold: within 200 m (any name) or within 1 km with a shared name word
dg = np.zeros(len(good), dtype=bool)
for i, (r, nb) in enumerate(zip(good, near)):
    if not nb: continue
    mt = tokens(r["site_name"])
    for j in nb:
        d = np.linalg.norm(mx[i] - gx[j])
        if d <= 200 or (mt and mt & tokens(G[j][1])): dg[i] = True; break
print("\nMRDS records treated as already in gold (<=200 m, or <=1 km with a shared name word):", int(dg.sum()))
# internal duplicates: same normalised name within 250 m -> keep best score
ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
cell = collections.defaultdict(list)
for i, r in enumerate(good):
    if dg[i]: continue
    cell[(norm(r["site_name"]), round(r["_lat"] * 400), round(r["_lon"] * 400))].append(i)
drop_internal = 0
for k, ids in cell.items():
    if len(ids) > 1 and k[0] not in ("", "unnamed", "unknown"):
        drop_internal += len(ids) - 1
unnamed = sum(1 for i, r in enumerate(good) if not dg[i] and norm(r["site_name"]) in ("", "unnamed", "unknown"))
nocomm = sum(1 for i, r in enumerate(good) if not dg[i] and not r["commod1"].strip())
keep = len(good) - int(dg.sum()) - drop_internal
print("internal duplicates dropped (same name within ~250 m):", drop_internal, "| unnamed among remaining:", unnamed, "| no primary commodity among remaining:", nocomm)
print("records that would load:", keep, "of", len(R))
cn = collections.Counter(r["country"] for i, r in enumerate(good) if not dg[i]); print("by country (remaining before internal dedupe):", cn.most_common(10))
print("US by state top:", collections.Counter(r["state"] for i, r in enumerate(good) if not dg[i] and r["country"] == "United States").most_common(8))
