"""Switch off CDoGS copies of Yukon RGS stream sediments now loaded from the Yukon Geological Survey compilation (YUKON_YGS_RGS).

Match: CDoGS field_id 'NTS :YYNNNN:SS' (e.g. '105K  :881005:00') <-> YGS SAMPLE_ID 'NTSYYNNNN' (e.g. '105K881005'), NTS zero-padded to 4.
Only CDoGS 'NGR bulk stream sediment' rows of the <177 micron (NGR) fraction are candidates; field-duplicate splits (suffix 10/20/30) and the
heavy-mineral-concentrate fraction stay active (the YGS file has neither). Matches more than 5 km apart are left and reported.
Action: geochem.samples.is_active = false (modified_by = TAG) and their active analytical_results.is_active = false.
Backup: backups/supersede_cdogs_yukon_20261116_samples.csv (cdogs sample_id, yukon sample_id, key, km) and ..._results.csv (result_ids switched off).
Usage: python supersede_cdogs_yukon.py [--check | --undo]
"""
import csv, math, os, re, sys, collections
import psycopg2

TAG = "supersede_cdogs_by_yukon_rgs_20261116"
HERE = os.path.dirname(os.path.abspath(__file__))
BK = os.path.join(HERE, "backups"); os.makedirs(BK, exist_ok=True)
FS, FR = os.path.join(BK, "supersede_cdogs_yukon_20261116_samples.csv"), os.path.join(BK, "supersede_cdogs_yukon_20261116_results.csv")
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")

if "--undo" in sys.argv:
    sids = [int(r["cdogs_sample_id"]) for r in csv.DictReader(open(FS))]
    rids = [int(r["result_id"]) for r in csv.DictReader(open(FR))]
    c.execute("UPDATE geochem.samples SET is_active = true, modified_by = %s, modified_date = now() WHERE sample_id = ANY(%s) AND modified_by = %s",
              ("undo_" + TAG, sids, TAG))
    print("samples restored", c.rowcount, "of", len(sids))
    c.execute("UPDATE geochem.analytical_results SET is_active = true WHERE source_system = 'CANADA_NRCAN_CDOGS' AND result_id = ANY(%s)", (rids,))
    print("results restored", c.rowcount, "of", len(rids))
    g.commit(); sys.exit(0)

c.execute("SELECT field_id, sample_id, lat, lon FROM geochem.samples WHERE source_system = 'YUKON_YGS_RGS' AND is_active")
yk = {}
for f, sid, lat, lon in c.fetchall():
    yk[f[:-6].zfill(4) + f[-6:]] = (sid, lat, lon)
assert len(yk) > 30000, len(yk)
c.execute("""SELECT sample_id, field_id, sample_number, lat, lon FROM geochem.samples
             WHERE source_system = 'CANADA_NRCAN_CDOGS' AND is_active AND sample_type_local = 'CDoGS: NGR bulk stream sediment'
               AND lat > 59.9 AND lon BETWEEN -141.1 AND -123.7""")
st = collections.Counter(); cand = collections.defaultdict(list)
for sid, f, num, lat, lon in c.fetchall():
    m = re.match(r"\s*(\d{2,3}[A-P])\s*:(\d{6}):?(\d*)", f or "")
    m2 = re.match(r"\s*(\d{2,3}[A-P])\s*:(\d{4}):(\d{4}):?(\d*)", f or "")
    if m: key, suf = m.group(1).zfill(4) + m.group(2), m.group(3)
    elif m2: key, suf = m2.group(1).zfill(4) + m2.group(2)[2:] + m2.group(3), m2.group(4)
    else: st["no key"] += 1; continue
    if key not in yk: st["no YGS match"] += 1; continue
    if "(<177 micron (NGR))" not in (num or ""): st["other fraction kept"] += 1; continue
    if suf in ("10", "20", "30"): st["field duplicate kept"] += 1; continue
    y = yk[key]
    km = math.hypot((lat - y[1]) * 111.2, (lon - y[2]) * 111.2 * math.cos(math.radians(lat)))
    cand[key].append((km, sid, y[0]))
rows = []
for key, lst in cand.items():
    if len(lst) > 1: st["keys with repeated CDoGS copies (all switched off)"] += 1
    for km, sid, ysid in lst:
        if km > 5: st["match > 5 km kept"] += 1; continue
        rows.append((sid, ysid, key, round(km, 3)))
st["to switch off"] = len(rows)
print(dict(st))
ids = [r[0] for r in rows]
c.execute("SELECT result_id FROM geochem.analytical_results WHERE source_system = 'CANADA_NRCAN_CDOGS' AND is_active AND sample_id = ANY(%s)", (ids,))
rids = [r[0] for r in c.fetchall()]
print("active CDoGS results on those samples", len(rids))
if "--check" in sys.argv:
    g.rollback(); print("CHECK only"); sys.exit(0)
with open(FS, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["cdogs_sample_id", "yukon_sample_id", "key", "km"]); w.writerows(rows)
with open(FR, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["result_id"]); w.writerows([[r] for r in rids])
c.execute("UPDATE geochem.samples SET is_active = false, modified_by = %s, modified_date = now() WHERE sample_id = ANY(%s) AND is_active", (TAG, ids))
assert c.rowcount == len(ids), c.rowcount
c.execute("UPDATE geochem.analytical_results SET is_active = false WHERE source_system = 'CANADA_NRCAN_CDOGS' AND result_id = ANY(%s)", (rids,))
assert c.rowcount == len(rids), c.rowcount
g.commit(); print("COMMITTED", TAG, len(ids), "samples", len(rids), "results; backups", FS, FR)
