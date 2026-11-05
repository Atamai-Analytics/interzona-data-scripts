"""Link drill holes to the mineral occurrence they were drilled on - HIGH-CONFIDENCE links only; anything ambiguous stays unlinked.

Rules (every link needs specific evidence besides distance; distance alone never links; final distance limits: A alone 1 km, or 500 m when the
  occurrence record is itself other drill holes; B alone 2 km; A and B together 3 km; C 500 m):
  A  SHARED ASSESSMENT FILE (Saskatchewan): the hole's source assessment file is listed in the occurrence's SMDI 'Assessment files', and the
     occurrence is within 5 km of the collar.
  B  NAME: the hole's prospect / project name and the occurrence's name share a distinctive word (4+ letters, not a generic geographic or mining
     word) or are equal, and the occurrence is within 3 km.
  C  COMMODITY CONFIRMED BY THE HOLE (Québec intercepts): the hole reports a mineralised intercept of one of the occurrence's commodities, the
     occurrence is within 500 m of the collar, and it is the only occurrence with that commodity within 1 km.
A hole is linked only when all its rule matches point to ONE occurrence. Stored: drilling.drillholes.occurrence_id, occurrence_link_method
('A_ASSESSMENT_FILE' / 'B_NAME' / 'C_INTERCEPT_COMMODITY', joined with '+' when several agree) and occurrence_link_detail (evidence, distance).
Usage: python link_drillholes.py            report only (writes link_drillholes_review.csv), changes nothing
       python link_drillholes.py --apply    writes the links (re-running replaces earlier links made by this script)
"""
import os, sys, re, csv, collections, unicodedata
import psycopg2

APPLY = "--apply" in sys.argv
TAG = "link_drillholes_20261105"
HERE = os.path.dirname(os.path.abspath(__file__))
SK_CSV = "D:/CriticalMineralsDB/Canada/Saskatchewan_geochem_drillholes/drillholes.csv"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60)
c = g.cursor()
c.execute("SET statement_timeout = 0")

GENERIC = set("""lake lakes creek river hill hills mount mountain mine mines deposit deposits prospect project property claim claims zone zones area
north south east west northeast northwest southeast southwest central upper lower main new old little big grand petit grande lac riviere
mont bay island point road showing occurrence vein veins grid block extension township canton camp mill shaft pit trench drill hole holes
sample samples site sites gold copper zinc nickel uranium lithium iron silver lead tin tungsten clay kaolin potash coal sand gravel
quarry the and des les une sur near south-east north-east""".split())


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def words(s):
    return {w for w in norm(s).split() if len(w) >= 4 and w not in GENERIC and not w.isdigit()}


# ---------------------------------------------------------------- candidate occurrences near each hole (up to 5 km)
c.execute("""
CREATE TEMP TABLE near AS
SELECT h.drillhole_id, h.source_system, coalesce(h.prospect, '') AS prospect, coalesce(h.hole_name, '') AS hole_name, h.comments AS hcomm,
       o.occurrence_id, o.name AS oname, o.commodities, o.comments AS ocomm, o.created_by AS ocreated, p.name AS pname,
       ST_Distance(h.geog, o.geog) AS dist
FROM drilling.drillholes h
JOIN core.occurrences o ON o.is_active AND ST_DWithin(h.geog, o.geog, 5000)
LEFT JOIN core.projects p ON p.project_id = o.project_id
WHERE h.geog IS NOT NULL""")
c.execute("SELECT count(*), count(DISTINCT drillhole_id) FROM near"); print("hole-occurrence pairs within 5 km (pairs, holes):", c.fetchone(), flush=True)

# hole -> intercept element symbols (Québec)
c.execute("""SELECT i.drillhole_id, array_agg(DISTINCT a.element_symbol) FROM drilling.intercepts i JOIN geochem.analytes a USING (analyte_id)
             WHERE i.is_active AND a.element_symbol IS NOT NULL GROUP BY 1""")
hole_elems = {r[0]: set(r[1]) for r in c.fetchall()}

# Saskatchewan hole source assessment file, by GOS id (the '#n' suffix marks holes sharing an id)
sk_src = {}
for r in csv.DictReader(open(SK_CSV, encoding="utf-8")):
    s = r["SOURCE"].strip()
    if s: sk_src.setdefault(r["GOS_UNIQUE_DRILLHOLE_ID"].strip(), s.upper())

c.execute("SELECT drillhole_id, source_hole_id FROM drilling.drillholes WHERE source_system = 'CANADA_SK_SGS'")
sk_file = {hid: sk_src.get(gid.split("#")[0]) for hid, gid in c.fetchall()}

c.execute("SELECT drillhole_id, source_system, prospect, hole_name, occurrence_id, oname, commodities, ocomm, pname, dist FROM near")
rows = c.fetchall()
by_hole = collections.defaultdict(list)
for r in rows: by_hole[r[0]].append(r)

# per-commodity occurrence counts within 1 km of each hole (for rule C uniqueness)
matches = collections.defaultdict(lambda: collections.defaultdict(list))   # hole -> occ -> [rule evidence]
stats = collections.Counter()
for hid, cands in by_hole.items():
    src = cands[0][1]
    hwords = words(cands[0][2]) | (words(cands[0][3]) if src == "AUSTRALIA_TAS_MRT" else set())
    elems = hole_elems.get(hid, set())
    for (_, _, prospect, hname, oid, oname, comms, ocomm, pname, dist) in cands:
        comms = set(comms or [])
        # A: shared assessment file
        if src == "CANADA_SK_SGS" and sk_file.get(hid) and dist <= 5000:
            m = re.search(r"Assessment files: ([^;]*)", ocomm or "")
            files = {f.strip().upper() for f in m.group(1).split(",")} if m else set()
            if sk_file[hid] in files:
                matches[hid][oid].append(("A_ASSESSMENT_FILE", f"assessment file {sk_file[hid]}", dist))
        # B: name
        if dist <= 3000 and hwords:
            onames = words(oname) | words(pname or "")
            m = re.search(r"Project \(SMDI\): ([^;]*)", ocomm or "")
            if m: onames |= words(m.group(1))
            m = re.search(r"Historic names: ([^;]*)", ocomm or "")
            if m: onames |= words(m.group(1))
            common = hwords & onames
            if common or (norm(prospect) and norm(prospect) == norm(oname)):
                matches[hid][oid].append(("B_NAME", f"name word(s) {', '.join(sorted(common)) or norm(prospect)}", dist))
        # C: intercept commodity (checked after the loop for uniqueness)
        if dist <= 500 and elems & comms:
            others = [x for x in cands if x[4] != oid and x[9] <= 1000 and set(x[6] or []) & elems & comms]
            if not others:
                matches[hid][oid].append(("C_INTERCEPT_COMMODITY", f"intercept of {', '.join(sorted(elems & comms))}", dist))
            else:
                stats["C ambiguous (another occurrence with the commodity within 1 km)"] += 1

# distance limit by the evidence an occurrence has for a hole (checked before ambiguity, so only qualifying candidates count)
c.execute("SELECT occurrence_id FROM core.occurrences WHERE name ~* '^drill ?holes?\\M'")
hole_named = {r[0] for r in c.fetchall()}


def limit(oid, methods):
    if {"A_ASSESSMENT_FILE", "B_NAME"} <= methods: return 3000      # two independent pieces of evidence
    if "A_ASSESSMENT_FILE" in methods: return 500 if oid in hole_named else 1000   # an SMDI record that is itself other drill holes
    if "B_NAME" in methods: return 2000
    return 500                                                      # C: intercept commodity


for hid in list(matches):
    for oid in list(matches[hid]):
        ev = matches[hid][oid]
        if min(e[2] for e in ev) > limit(oid, {e[0] for e in ev}):
            del matches[hid][oid]; stats["dropped: evidence but too far for its rule"] += 1
    if not matches[hid]: del matches[hid]

links = {}
for hid, occs in matches.items():
    if len(occs) == 1:
        oid, ev = next(iter(occs.items()))
        method = "+".join(sorted({e[0] for e in ev}))
        detail = "; ".join(sorted({e[1] for e in ev})) + f"; collar {round(min(e[2] for e in ev))} m from the occurrence"
        links[hid] = (oid, method, detail, min(e[2] for e in ev))
        stats["linked " + method] += 1
    else:
        stats["ambiguous: evidence points to several occurrences"] += 1
print("result:", dict(stats), flush=True)

# review file: every link with names and evidence
c.execute("SELECT drillhole_id, source_system, hole_name, prospect FROM drilling.drillholes WHERE drillhole_id = ANY(%s)", (list(links),))
hinfo = {r[0]: r[1:] for r in c.fetchall()}
c.execute("SELECT occurrence_id, name, status, commodities FROM core.occurrences WHERE occurrence_id = ANY(%s)", (list({v[0] for v in links.values()}),))
oinfo = {r[0]: r[1:] for r in c.fetchall()}
out = os.path.join(HERE, "link_drillholes_review.csv")
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["drillhole_id", "source_system", "hole_name", "prospect", "occurrence_id", "occurrence", "status", "commodities", "method", "evidence"])
    for hid, (oid, method, detail, dist) in sorted(links.items()):
        h = hinfo[hid]; o = oinfo[oid]
        w.writerow([hid, h[0], h[1], h[2], oid, o[0], o[1], ";".join(o[2] or []), method, detail])
print("review file", out)
c.execute("SELECT source_system, count(*) FROM drilling.drillholes GROUP BY 1"); tot = dict(c.fetchall())
per = collections.Counter(hinfo[h][0] for h in links)
print("linked per source:", {k: f"{per.get(k, 0)} of {v}" for k, v in tot.items()})
print("distinct occurrences linked:", len({v[0] for v in links.values()}))

if APPLY:
    c.execute("SET lock_timeout = '20s'")
    c.execute("ALTER TABLE drilling.drillholes ADD COLUMN IF NOT EXISTS occurrence_link_method varchar(60)")
    c.execute("ALTER TABLE drilling.drillholes ADD COLUMN IF NOT EXISTS occurrence_link_detail text")
    g.commit()
    c.execute("SET lock_timeout = 0")
    c.execute("UPDATE drilling.drillholes SET occurrence_id = NULL, occurrence_link_method = NULL, occurrence_link_detail = NULL WHERE modified_by = %s", (TAG,))
    print("cleared earlier links", c.rowcount)
    c.execute("CREATE TEMP TABLE lk (hid bigint, oid int, method text, detail text)")
    c.executemany("INSERT INTO lk VALUES (%s,%s,%s,%s)", [(h, v[0], v[1], v[2]) for h, v in links.items()])
    c.execute(f"""UPDATE drilling.drillholes h SET occurrence_id = lk.oid, occurrence_link_method = lk.method, occurrence_link_detail = lk.detail,
                  modified_by = '{TAG}', modified_date = now() FROM lk WHERE h.drillhole_id = lk.hid""")
    print("linked", c.rowcount)
    g.commit(); print("COMMITTED")
else:
    g.rollback(); print("REPORT ONLY - nothing changed")
