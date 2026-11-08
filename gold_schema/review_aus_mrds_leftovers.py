"""Classify the active Australian USGS MRDS occurrences left after the MINEDEX / GA loads (2026-11-08).

For each MRDS record: nearest new survey occurrence (MINEDEX or GA OZMIN/state) and the best candidate within 5 km scored by name overlap and
commodity overlap. Classes:
  DUP_STRONG  <= 2 km, shares a name word (or identical name) AND a commodity  -> merge
  DUP_NAME    <= 5 km, identical normalised name                                -> merge
  NEAR_ONLY   <= 2 km, shares a commodity but no name word                      -> leave (could be a different working)
  UNIQUE      nothing within 5 km sharing name or commodity                     -> keep (MRDS adds coverage)
Writes aus_mrds_leftovers_review.csv. With --merge, merges DUP_STRONG + DUP_NAME exactly as the loaders do (references re-pointed, MRDS row
deactivated, log aus_mrds_leftover_merge_log_<ts>.csv).
"""
import csv, os, re, sys, time, datetime, collections
import numpy as np, psycopg2
from scipy.spatial import cKDTree

MERGE = "--merge" in sys.argv
TAG = "fix_aus_mrds_leftovers_20261108"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
GEN = {"mine", "mines", "deposit", "prospect", "north", "south", "east", "west", "central", "group", "extended", "main", "australia",
       "austrlia", "mount", "creek", "hill", "range", "well", "lake", "river", "area", "field", "project", "workings", "quarry", "reef", "lode"}
norm = lambda n: re.sub(r"[^a-z0-9]", "", re.sub(r",?\s*austra?lia$", "", (n or "").lower().strip()))
words = lambda n: {w for w in re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split() if len(w) >= 4 and w not in GEN and not w.isdigit()}

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("""SELECT occurrence_id, name, lat, lon, coalesce(commodities, '{}') FROM core.occurrences WHERE is_active AND country_name = 'Australia'
             AND created_by = 'migration_mrds_20261014' AND lat IS NOT NULL""")
mrds = c.fetchall()
c.execute("""SELECT occurrence_id, name, lat, lon, coalesce(commodities, '{}') FROM core.occurrences WHERE is_active AND country_name = 'Australia'
             AND created_by IN ('migration_minedex_occ_20261108', 'migration_ga_aus_occ_20261108') AND lat IS NOT NULL""")
new = c.fetchall()
print("MRDS left", len(mrds), "| survey occurrences", len(new))
lat0 = np.radians(-27)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(lat0) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
tree = cKDTree(xy([n[2] for n in new], [n[3] for n in new])); P = xy([m[2] for m in mrds], [m[3] for m in mrds])
out, cls = [], collections.Counter()
for i, m in enumerate(mrds):
    best, bkey, nearest = None, None, None
    for j in tree.query_ball_point(P[i], 5000):
        d = float(np.hypot(*(P[i] - tree.data[j]))); n = new[j]
        if nearest is None or d < nearest[1]: nearest = (n, d)
        same = norm(n[1]) == norm(m[1]) and len(norm(m[1])) >= 4
        wo = bool(words(n[1]) & words(m[1])); co = bool(set(n[4]) & set(m[4]))
        key = (same, wo and co, wo, co, -d)
        if bkey is None or key > bkey: best, bkey = (n, d, same, wo, co), key
    if best is None: k = "UNIQUE"
    else:
        n, d, same, wo, co = best
        if d <= 2000 and wo and co: k = "DUP_STRONG"
        elif same: k = "DUP_NAME"
        elif d <= 2000 and co: k = "NEAR_ONLY"
        else: k = "UNIQUE"
    cls[k] += 1
    out.append((k, m[0], m[1], ",".join(m[4]), best[0][0] if best else "", best[0][1] if best else "", ",".join(best[0][4]) if best else "",
                round(best[1]) if best else "", round(nearest[1]) if nearest else ""))
print(dict(cls))
with open(os.path.join(HERE, "aus_mrds_leftovers_review.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["class", "mrds_id", "mrds_name", "mrds_commodities", "best_id", "best_name", "best_commodities", "best_m", "nearest_m"]); w.writerows(out)
for k in ("DUP_STRONG", "DUP_NAME", "NEAR_ONLY"):
    ex = [o for o in out if o[0] == k][:6]
    for o in ex: print(k, "|", o[2], "->", o[5], f"({o[7]} m)", o[3], "/", o[6])

if MERGE:
    REPOINT = [("geochem.sample_occurrence_links", "occurrence_id"), ("core.projects", "occurrence_id"), ("core.resource_estimates", "occurrence_id"),
               ("docs.documents", "occurrence_id"), ("geochem.samples", "occurrence_id"), ("core.occurrence_ownership", "occurrence_id"),
               ("geochem.occurrence_mineralogy", "occurrence_id"), ("geochem.occurrence_endowment", "occurrence_id"), ("docs.document_chunks", "occurrence_id")]
    logrows = []
    for o in out:
        if o[0] not in ("DUP_STRONG", "DUP_NAME"): continue
        old, new_id = o[1], o[4]
        c.execute("""DELETE FROM geochem.sample_occurrence_links WHERE occurrence_id = %s
                     AND sample_id IN (SELECT sample_id FROM geochem.sample_occurrence_links WHERE occurrence_id = %s)""", (old, new_id))
        if c.rowcount: logrows.append(("drop_duplicate_link", "geochem.sample_occurrence_links", old, new_id, c.rowcount, o[7], o[2], o[5]))
        for tbl, col in REPOINT:
            c.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new_id, old))
            if c.rowcount: logrows.append(("repoint", tbl, old, new_id, c.rowcount, o[7], o[2], o[5]))
        c.execute("UPDATE core.external_ids SET entity_id = %s WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MRDS'", (new_id, old))
        c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now() WHERE occurrence_id = %s", (TAG, old))
        logrows.append(("deactivate", "core.occurrences", old, new_id, 1, o[7], o[2], o[5]))
    p = os.path.join(HERE, f"aus_mrds_leftover_merge_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["action", "table", "old_occurrence_id", "new_occurrence_id", "rows", "distance_m", "mrds_name", "new_name"]); w.writerows(logrows)
    g.commit(); print("MERGED", sum(1 for r in logrows if r[0] == "deactivate"), "log", p)
