"""SGU strat_p stratigraphic classification (code + Swedish text with an age range in Ga) -> interzona_cm geochem.age_stratigraphic.

Additive schema changes (same transaction):
  * geochem.age_stratigraphic gains nullable age_max_ma (older bound) and age_min_ma (younger bound) = SGU's range, in Ma.
  * geochem.stratigraphic_age_reference gains the official ICS periods Siderian, Rhyacian, Orosirian, Statherian, Stenian.
Each sample gets the narrowest official period/epoch that contains SGU's range (tolerance 5 Ma) as stratigraphic_age_id.
Skipped: code 0 (none), 199 (stratigraphic position unknown), 141 and 750 (no age range in the text).
Usage: python load_sgu_strat_p.py [--dry]   (--dry = everything, then ROLLBACK)
"""
import csv, re, os, sys, time, collections
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
CB = "sgu_strat_p_20261012"
SRC = "SWEDEN_SGU_LITHOGEOCHEMISTRY"
TOL = 5.0
SKIP = {"0", "199", "141", "750"}
ENV = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def lines(path):
    with open(path, "rb") as fb:
        for raw in fb:
            try: yield raw.decode("utf-8")
            except UnicodeDecodeError: yield raw.decode("cp1252", errors="replace")


NUM = r"(\d+(?:[.,]\d+)?)"


def ga(s):
    return float(s.replace(",", ".")) * 1000


def parse(t):
    """returns (older_ma, younger_ma); None = open end"""
    s = t.replace("Ga", " Ga")
    m = re.search(NUM + r"\s*[-\u2013]\s*" + NUM, s)
    if m:
        a, b = ga(m.group(1)), ga(m.group(2)); return max(a, b), min(a, b)
    m = re.search(r"([<>])\s*(?:ca\s*)?" + NUM, s)
    if m:
        return (None, ga(m.group(2))) if m.group(1) == ">" else (ga(m.group(2)), None)
    m = re.search(r"ca\s*" + NUM + r"\s*Ga", s)
    if m:
        v = ga(m.group(1)); return v, v
    return None, None


rows = {}
for x in csv.DictReader(lines(r"D:\CriticalMineralsDB\Sweden\bergartskemi.csv")):
    code = x["strat_p"].strip(); txt = x["strat_p_tx"].strip()
    if code in SKIP or txt in ("", "NA"): continue
    rows[x["bergartskemi_id"]] = (code, txt)
log("CSV analyses with a usable strat_p class", len(rows))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET lock_timeout = '60s'")

# schema additions
c.execute("ALTER TABLE geochem.age_stratigraphic ADD COLUMN IF NOT EXISTS age_max_ma numeric, ADD COLUMN IF NOT EXISTS age_min_ma numeric")
c.execute("SELECT stratigraphic_age_id, age_name FROM geochem.stratigraphic_age_reference WHERE age_name IN ('Paleoproterozoic','Mesoproterozoic')")
par = {n: i for i, n in c.fetchall()}
NEW = [("Siderian", 2500, 2300, "Paleoproterozoic"), ("Rhyacian", 2300, 2050, "Paleoproterozoic"), ("Orosirian", 2050, 1800, "Paleoproterozoic"),
       ("Statherian", 1800, 1600, "Paleoproterozoic"), ("Stenian", 1200, 1000, "Mesoproterozoic")]
for name, a, b, parent in NEW:
    c.execute("SELECT 1 FROM geochem.stratigraphic_age_reference WHERE age_name = %s", (name,))
    if not c.fetchone():
        c.execute("""INSERT INTO geochem.stratigraphic_age_reference (age_name, age_type, parent_age_id, age_start_ma, age_end_ma, age_rank, region, is_official, reference, is_active, created_by)
          VALUES (%s, 'PERIOD', %s, %s, %s, 3, 'Global', true, 'ICS International Chronostratigraphic Chart', true, %s)""",
                  (name, par[parent], a, b, CB))
log("periods added", [n for n, *_ in NEW])

c.execute("""SELECT stratigraphic_age_id, age_name, age_start_ma, age_end_ma, is_official, age_type FROM geochem.stratigraphic_age_reference
 WHERE is_active AND age_start_ma IS NOT NULL AND age_end_ma IS NOT NULL""")
REFS = [(i, n, float(a), float(b), off, t) for i, n, a, b, off, t in c.fetchall()]
OFFICIAL = [r for r in REFS if r[4] and r[5] in ("EON", "ERA", "PERIOD", "EPOCH")]


def best(older, younger):
    a = 4000.0 if older is None else older
    b = 0.0 if younger is None else younger
    for pool in (OFFICIAL, REFS):
        cand = [(r[2] - r[3], r[0], r[1]) for r in pool if r[2] >= a - TOL and r[3] <= b + TOL]
        if cand: return min(cand)
    return None


c.execute("SELECT sample_number, sample_id FROM geochem.samples WHERE source_system = %s", (SRC,))
SID = dict(c.fetchall())
out, unmatched, byref, nmiss = [], 0, collections.Counter(), 0
cls_range = {}
for bid, (code, txt) in rows.items():
    sid = SID.get(bid)
    if sid is None: nmiss += 1; continue
    if code not in cls_range:
        cls_range[code] = parse(txt)
    older, younger = cls_range[code]
    if older is None and younger is None: unmatched += 1; continue
    b = best(older, younger)
    if b is None: unmatched += 1; continue
    byref[b[2]] += 1
    rng = "%s-%s Ma" % ("open" if older is None else int(older), "open" if younger is None else int(younger))
    out.append((b[1], txt, "POINT_LOCATION", sid, "MEDIUM", "SGU stratigraphic classification (strat_p)", txt,
                "SGU strat_p class %s; age range %s older-younger bound; period link is the narrowest ICS period containing the range" % (code, rng),
                older, younger, True, CB))
log("rows to insert", len(out), "| unmatched class", unmatched, "| csv ids not in gold", nmiss)
log("by period", byref.most_common())
execute_values(c, """INSERT INTO geochem.age_stratigraphic (stratigraphic_age_id, age_local, observation_context, sample_id, confidence_level, determination_method,
 reported_age_raw, comments, age_max_ma, age_min_ma, is_active, created_by) VALUES %s""", out, page_size=1000)
c.execute("SELECT count(*), count(DISTINCT sample_id), min(age_min_ma), max(age_max_ma) FROM geochem.age_stratigraphic WHERE created_by = %s", (CB,)); log("inserted (rows, samples, min, max)", c.fetchone())
c.execute("SELECT count(*) FROM geochem.age_stratigraphic"); log("age_stratigraphic total", c.fetchone()[0])
c.execute("""SELECT count(*) FROM geochem.age_stratigraphic WHERE created_by = %s AND age_max_ma IS NOT NULL AND age_min_ma IS NOT NULL AND age_max_ma < age_min_ma""", (CB,)); log("rows with older < younger (must be 0)", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
