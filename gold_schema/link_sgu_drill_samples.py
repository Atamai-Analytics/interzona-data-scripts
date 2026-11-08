"""Link SGU lithogeochemistry drill-core samples (SWEDEN_SGU_LITHOGEOCHEMISTRY, sample_context DRILLHOLE_POINT, 101,968) to SGU Borrhål holes
(SWEDEN_SGU_BORRHAL in drilling.drillholes) with their downhole section, so the drill-intercepts tool and page can composite them.

SGU's sample comments name the hole and section in Swedish, e.g. 'Karaktärisering av mineralisering i borrkärna Boliden borrhål ALA210, sektion
86-88,3 m' or 'Karaktärisering av borrkärna - 12DDTS006 - GRANMUREN , provtagen vid 140 - 141'. ~29,500 samples only say 'malm core' and cannot be linked.
Rules
  * hole token: after 'borrhål' / 'borrhal', or between dashes after 'borrkärna'; trailing punctuation stripped; matched case-insensitively to the
    hole's SGU idcode (source_hole_id, without the '#rowid' suffix used for duplicate idcodes). Several candidates -> the nearest collar.
  * fallback when the comment names no hole (or one not in the register): the source record's alt_id, then ext_id (bergartskemi.gpkg, joined via
    geochem.sample_provenance.source_record_id = bergartskemi_id) when it equals an SGU idcode - often it is only a lab or field number, so it must
    also pass the position check (tip from the parallel 'Interzona app' session).
  * position check: the sample's own point must lie within MAX_KM (5 km) of the collar, else not linked (same name, different hole).
  * section: 'sektion X-Y m', 'X-Y m' or 'vid X - Y' (decimal commas allowed). Kept only when 0 <= from < to and to <= hole depth + 5 m (or the hole
    depth is unknown); otherwise the sample is linked to the hole without depths (stays DRILLHOLE_POINT).
  * linked samples get drillhole_id; samples with a valid section also get depth_from_m / depth_to_m and sample_context 'DRILLHOLE_INTERVAL'.
Every changed row is written first to link_sgu_drill_samples_<time>.csv (old values). Rollback: per row UPDATE geochem.samples SET drillhole_id = old,
depth_from_m = old, depth_to_m = old, sample_context = old WHERE source_system = 'SWEDEN_SGU_LITHOGEOCHEMISTRY' AND sample_id = <id>; then rebuild wide.
Afterwards: python build_chem_wide.py SWEDEN_SGU_LITHOGEOCHEMISTRY
Usage: python link_sgu_drill_samples.py [--dry]
"""
import os, sys, re, csv, math, datetime, collections, sqlite3
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
SRC, HOLES = "SWEDEN_SGU_LITHOGEOCHEMISTRY", "SWEDEN_SGU_BORRHAL"
MAX_KM = 5.0
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"],
                     keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
c = g.cursor()
c.execute("SET statement_timeout = 0")

RE_HOLE = [re.compile(r"borrh[åa]l\s+([A-Za-z0-9][\w\-/.]*)", re.I), re.compile(r"borrkärna\s*-\s*([^\s,]+)\s*-", re.I)]
NUM = r"(\d+(?:[.,]\d+)?)"
RE_SEC = [re.compile(r"sektion\s+" + NUM + r"\s*-\s*" + NUM, re.I), re.compile(NUM + r"\s*-\s*" + NUM + r"\s*m\b"), re.compile(r"vid\s+" + NUM + r"\s*-\s*" + NUM, re.I)]
f = lambda s: float(s.replace(",", "."))


def parse(text):
    hole = sec = None
    for r in RE_HOLE:
        m = r.search(text or "")
        if m:
            hole = m.group(1).strip(".,;:/-").upper()
            break
    for r in RE_SEC:
        m = r.search(text or "")
        if m:
            sec = (f(m.group(1)), f(m.group(2)))
            break
    return hole, sec


def km(a_lat, a_lon, b_lat, b_lon):
    p = math.pi / 180
    x = (b_lon - a_lon) * p * math.cos((a_lat + b_lat) / 2 * p)
    return 6371 * math.hypot(x, (b_lat - a_lat) * p)


c.execute("SELECT drillhole_id, upper(split_part(source_hole_id, '#', 1)), lat, lon, total_depth_m FROM drilling.drillholes WHERE source_system = %s AND is_active", (HOLES,))
by_id = collections.defaultdict(list)
for hid, code, lat, lon, depth in c.fetchall():
    by_id[code].append((hid, lat, lon, float(depth) if depth is not None else None))
c.execute("""SELECT sample_id, comments, lat, lon, drillhole_id, depth_from_m, depth_to_m, sample_context FROM geochem.samples
             WHERE source_system = %s AND sample_context IN ('DRILLHOLE_POINT', 'DRILLHOLE_INTERVAL')""", (SRC,))
rows = c.fetchall()
c.execute("SELECT sample_id, source_record_id FROM geochem.sample_provenance WHERE source_system = %s", (SRC,))
rec_of = {sid: str(r) for sid, r in c.fetchall()}
gp = sqlite3.connect("file:D:/CriticalMineralsDB/Sweden/bergartskemi/bergartskemi.gpkg?mode=ro", uri=True)
alt = {str(b): [x.strip().upper() for x in (a, e) if x and str(x).strip()] for b, a, e in gp.execute("SELECT bergartskemi_id, alt_id, ext_id FROM bergartskemi")}
st = collections.Counter()
updates, old = [], []
for sid, text, lat, lon, o_h, o_f, o_t, o_ctx in rows:
    hole, sec = parse(text)
    cands = by_id.get(hole, []) if hole else []
    via = "comment"
    if not cands:
        for a in alt.get(rec_of.get(sid, ""), []):
            if by_id.get(a):
                hole, cands, via = a, by_id[a], "alt/ext id"
                break
    if not cands:
        st["no hole in comment" if not hole else "hole name not in SGU register"] += 1; continue
    if lat is None or lon is None:
        st["sample has no position"] += 1; continue
    best = min(cands, key=lambda h: km(lat, lon, h[1], h[2]) if h[1] is not None else 1e9)
    d = km(lat, lon, best[1], best[2]) if best[1] is not None else 1e9
    if d > MAX_KM:
        st[f"collar > {MAX_KM:g} km from sample"] += 1; continue
    if len(cands) > 1: st["(duplicate hole name, nearest used)"] += 1
    if via != "comment": st["(matched via alt/ext id)"] += 1
    ok = sec is not None and 0 <= sec[0] < sec[1] and (best[3] is None or sec[1] <= best[3] + 5)
    if sec is None: st["linked, no section in comment"] += 1
    elif not ok: st["linked, section rejected (from >= to or past end of hole)"] += 1
    else: st["linked with section"] += 1
    new = (best[0], sec[0] if ok else None, sec[1] if ok else None, "DRILLHOLE_INTERVAL" if ok else "DRILLHOLE_POINT")
    if (o_h, o_f, o_t, o_ctx) != new:
        updates.append((sid, *new)); old.append((sid, o_h, o_f, o_t, o_ctx, hole, round(d, 3)))
print("samples:", len(rows)); [print(f"  {k}: {v}") for k, v in st.most_common()]
print("rows to change:", len(updates), "| holes involved:", len({u[1] for u in updates}))
out = os.path.join(HERE, f"link_sgu_drill_samples_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["sample_id", "old_drillhole_id", "old_from", "old_to", "old_context", "hole_token", "collar_km"]); w.writerows(old)
execute_values(c, """UPDATE geochem.samples s SET drillhole_id = v.h, depth_from_m = v.f, depth_to_m = v.t, sample_context = v.ctx
                     FROM (VALUES %s) AS v(sid, h, f, t, ctx) WHERE s.source_system = 'SWEDEN_SGU_LITHOGEOCHEMISTRY' AND s.sample_id = v.sid""",
               updates, template="(%s::bigint, %s::bigint, %s::numeric, %s::numeric, %s)", page_size=5000)
print("updated:", c.rowcount if len(updates) <= 5000 else len(updates), "| list:", out)
c.execute("""SELECT sample_context, count(*), count(drillhole_id), count(DISTINCT drillhole_id) FROM geochem.samples WHERE source_system = %s
             AND sample_context LIKE 'DRILLHOLE%%' GROUP BY 1""", (SRC,))
print("after:", c.fetchall())
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
