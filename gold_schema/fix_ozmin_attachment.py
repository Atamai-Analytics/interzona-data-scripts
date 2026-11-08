"""Re-choose which occurrence each OZMIN deposit (attached to a MINEDEX site) and each resource-only GA deposit points to.

The first pass (load_ga_australia_occurrences.py / load_ga_resources.py, 2026-11-08) took the closest MINEDEX site sharing a name word, so e.g.
OZMIN Greenbushes (Li, Ta, Sn) landed on 'Gold Coin - Greenbushes (01)' and Pilgangoora on 'Creek 2'. Here every candidate active Australian
occurrence within 3 km is ranked by: commodity overlap with the OZMIN deposit (or its resource rows) > identical or shared name word >
is_deposit > name says 'resource' > distance. When the best candidate differs, the OZMIN external id, the appended 'OZMIN: ...' comment text
and the GA resource rows (core.resource_estimates, source AUSTRALIA_GA_OZMIN_RESOURCES) move to it. Every move is logged
(fix_ozmin_attachment_log_<ts>.csv: eno, old, new, names) for rollback.
Usage: python fix_ozmin_attachment.py [--dry]
"""
import csv, os, re, sys, time, datetime, collections
import psycopg2

DRY = "--dry" in sys.argv
TAG = "fix_ozmin_attachment_20261108"
HERE = os.path.dirname(os.path.abspath(__file__))
DL = "D:/CriticalMineralsDB/Australia/download_20261108"
STAMP = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
CODES = {}
exec(re.search(r"^CODES = \{.*?\}\n", open(os.path.join(HERE, "load_minedex_occurrences.py"), encoding="utf-8").read(), re.S | re.M).group(0))
CODES.update({"U3O8": "U", "Li2O": "Li", "Ta2O5": "Ta", "SnO2": "Sn", "WO3": "W", "V2O5": "V", "Nb2O5": "Nb", "TiO2": "Ti", "FeOre": "Fe",
              "Hem": "Fe", "Mag": "Fe", "MnOre": "Mn", "Cbl": "Coal", "Cbr": "Coal", "P2O5": "P", "Al2O3": "Al", "Bx": "Al", "REO": "REE"})
ALIAS = {"Ta2O5": "Ta", "SnO2": "Sn", "Li2O": "Li", "Spodumene": "Li", "WO3": "W", "V2O5": "V", "Nb2O5": "Nb", "Hematite": "Fe", "Magnetite": "Fe",
         "Black Coal": "Coal", "Brown Coal": "Coal", "Bauxite": "Al", "Alumina": "Al", "Manganese Ore": "Mn", "Rare Earth Oxide": "REE", "TiO2": "Ti",
         "Ilmenite": "Ti", "Rutile": "Ti", "Leucoxene": "Ti", "Heavy Mineral Sand": "Ti"}
GEN = {"mine", "mines", "deposit", "project", "prospect", "north", "south", "east", "west", "central", "group", "extended", "main", "openpit", "pit",
       "underground", "resources", "resource", "zone", "lode", "area"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def canon(t):
    t = CODES.get(t, t)
    return ALIAS.get(t, t)


def norm(n): return re.sub(r"[^a-z0-9]", "", (n or "").lower())
def wset(n): return {w for w in re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split() if len(w) >= 4 and w not in GEN and not w.isdigit()}


dep = {r["ENO"]: r for r in csv.DictReader(open(f"{DL}/ga_ozmin_mineral_deposits_20261108.csv", encoding="utf-8"))}
res = collections.defaultdict(set); resname = {}; respos = {}
for r in csv.DictReader(open(f"{DL}/ga_ozmin_reserves_resources_20261108.csv", encoding="utf-8")):
    res[r["ENO"]].add(canon(r["COMMODITY_CODE"].strip())); resname[r["ENO"]] = r["DEPOSIT_NAME"]; respos[r["ENO"]] = (float(r["LONG_GDA94"]), float(r["LAT_GDA94"]))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
# A: OZMIN deposits attached to a MINEDEX site (external id AUSTRALIA_GA_OZMIN on an occurrence not created by the GA loader)
c.execute("""SELECT e.source_id, e.entity_id FROM core.external_ids e JOIN core.occurrences o ON o.occurrence_id = e.entity_id
             WHERE e.source_system = 'AUSTRALIA_GA_OZMIN' AND o.created_by = 'migration_minedex_occ_20261108'""")
attached = dict(c.fetchall())
# B: resource-only deposits (GA resource rows whose ENO is not an OZMIN external id)
c.execute("""SELECT DISTINCT substring(comments from 'ENO ([0-9]+)\\)'), occurrence_id FROM core.resource_estimates
             WHERE source_system = 'AUSTRALIA_GA_OZMIN_RESOURCES'""")
res_occ = collections.defaultdict(set)
for eno, oid in c.fetchall(): res_occ[eno].add(oid)
c.execute("SELECT source_id FROM core.external_ids WHERE source_system = 'AUSTRALIA_GA_OZMIN'")
ozmin_enos = {r[0] for r in c.fetchall()}
resonly = {e: next(iter(o)) for e, o in res_occ.items() if e not in ozmin_enos and len(o) == 1}
log("OZMIN attached to MINEDEX", len(attached), "| resource-only deposits", len(resonly))

moves = []
for kind, items in (("ozmin", attached), ("resonly", resonly)):
    for eno, cur in items.items():
        if kind == "ozmin":
            d = dep[eno]; name = d["DEPOSIT_NAME"]; lon, lat = float(d["LONG_GDA94"]), float(d["LAT_GDA94"])
            coms = {canon(t.strip().strip("()")) for t in d["COMMODITY_CODES"].split(",") if t.strip().strip("()")} | res.get(eno, set())
        else:
            name = resname[eno]; lon, lat = respos[eno]; coms = res.get(eno, set())
        c.execute("""SELECT occurrence_id, name, commodities, is_deposit, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)
                     FROM core.occurrences WHERE is_active AND country_name = 'Australia'
                     AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 3000)""", (lon, lat, lon, lat))
        best, bkey = None, None
        for oid, nm, ocom, isdep, dist in c.fetchall():
            ov = len(coms & {canon(x) for x in (ocom or [])})
            nmatch = 2 if norm(nm) == norm(name) else (1 if wset(nm) & wset(name) else 0)
            key = (ov > 0, nmatch, ov, bool(isdep), "resource" in (nm or "").lower(), -dist)
            if bkey is None or key > bkey: best, bkey = (oid, nm, round(dist)), key
        if best and best[0] != cur:
            moves.append((kind, eno, cur, best[0], name, best[1], best[2]))
log("moves", len(moves), collections.Counter(m[0] for m in moves))
c.execute("SELECT occurrence_id, name FROM core.occurrences WHERE occurrence_id = ANY(%s)", ([m[2] for m in moves],))
oldname = dict(c.fetchall())
for m in moves:
    if re.search(r"greenbushes|pilgangoora|kathleen|wodgina|olympic|cattlin|marion", m[4], re.I):
        log("  ", m[1], m[4], "|", oldname.get(m[2]), "->", m[5], f"({m[6]} m)")

for kind, eno, old, new, name, newname, dist in moves:
    if kind == "ozmin":
        c.execute("UPDATE core.external_ids SET entity_id = %s WHERE source_system = 'AUSTRALIA_GA_OZMIN' AND source_id = %s AND entity_id = %s", (new, eno, old))
        c.execute("SELECT comments FROM core.occurrences WHERE occurrence_id = %s", (old,))
        oc = c.fetchone()[0] or ""
        mt = re.search(rf"; OZMIN: ENO {eno} \(.*?(?=; OZMIN: ENO |$)", oc, re.S)
        if mt:
            c.execute("UPDATE core.occurrences SET comments = %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (oc.replace(mt.group(0), ""), TAG, old))
            c.execute("UPDATE core.occurrences SET comments = concat_ws('', comments, %s), modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
                      (mt.group(0), TAG, new))
    c.execute("""UPDATE core.resource_estimates SET occurrence_id = %s WHERE source_system = 'AUSTRALIA_GA_OZMIN_RESOURCES' AND occurrence_id = %s
                 AND comments LIKE %s""", (new, old, f"%(ENO {eno})%"))
path = os.path.join(HERE, f"fix_ozmin_attachment_log_{STAMP}{'_DRY' if DRY else ''}.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["kind", "eno", "old_occurrence_id", "new_occurrence_id", "ozmin_name", "old_name", "new_name", "distance_m"])
    for kind, eno, old, new, name, newname, dist in moves: w.writerow([kind, eno, old, new, name, oldname.get(old), newname, dist])
log("log", path)
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
