"""EXACT recovery of the user's NSW method mapping ((ASSAYCODE, FIELD1, FIELD2) -> package_code; the dropped "NSWAnalyticalMapping" table)
by matching every bronze NSW result to the source row it was loaded from. READ-ONLY on both databases.

Bronze row (criticialmineralsexp, datasource 'Geological Survey of NSW'): samples.samplenumberalt = FILE_ID (samples.fieldid holds RPT_ID), samples.samplenumber = SAMPLEID, analyte_code =
ELEMENT, value = float(RESULT), package_code = the mapped package. Source row (criticalminerals staging): nsw_dd_sgc_data (FILE_ID, SAMPLEID, ASS_ID,
RESULT) + nsw_dd_gch_meta (ELEMENT, ASSAYCODE, UNITS, LAB_CODE) + nsw_dd_rpt_code (FIELD1, FIELD2 on FILE_ID + CODE = ASSAYCODE).
Both sides are streamed ordered by FILE_ID (text, COLLATE "C" so Python string order matches) and merged file by file; a bronze row votes for a key only when exactly one source key has the
same (SAMPLEID, ELEMENT, value) in that file. A key is RECOVERED when one package has >= 95 % of its votes (CONFLICT otherwise).
Outputs in argv[1]: nsw_mapping_exact.csv (key, package, votes, share, source rows), nsw_mapping_exact_conflicts.csv,
nsw_source_keys_not_in_mapping.csv (keys never matched, ranked by source rows, with LAB_CODE / UNITS / example ELEMENTs).
"""
import csv, os, sys, time, collections
import psycopg2

OUT = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


def con(db):
    g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db, user=ENV["LITHODAT_DB_USER"],
                         password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
    g.set_session(readonly=True)
    c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '1GB'")
    return g


def vk(x):
    try:
        return f"{float(x):.9g}"
    except (TypeError, ValueError):
        return None


gb, gs = con("criticialmineralsexp"), con("criticalminerals")
bc = gb.cursor(name="bronze_nsw"); bc.itersize = 200_000
bc.execute("""SELECT s.samplenumberalt::text, s.samplenumber::text, a.analyte_code, r.value, p.package_code
              FROM analytical_results r JOIN samples s ON s.sampleid = r.sampleid JOIN locations l ON l.locationid = s.locationid
              JOIN analytes a ON a.analyte_id = r.analyte_id JOIN analytical_packages p ON p.package_id = r.package_id
              WHERE l.datasource = 'Geological Survey of NSW' ORDER BY s.samplenumberalt::text COLLATE "C" """)
sc = gs.cursor(name="source_nsw"); sc.itersize = 200_000
sc.execute('''SELECT d."FILE_ID"::text, d."SAMPLEID"::text, m."ELEMENT"::text, d."RESULT"::text, m."ASSAYCODE"::text, c."FIELD1"::text, c."FIELD2"::text,
                     m."LAB_CODE"::text, m."UNITS"::text
              FROM nsw_dd_sgc_data d JOIN nsw_dd_gch_meta m ON m."FILE_ID" = d."FILE_ID" AND m."ASS_ID" = d."ASS_ID"
              LEFT JOIN nsw_dd_rpt_code c ON c."FILE_ID"::text = m."FILE_ID"::text AND c."CODE"::text = m."ASSAYCODE"::text
              ORDER BY d."FILE_ID"::text COLLATE "C"''')
log("both cursors open")


def groups(cur):
    """yield (file_id, [rows]) from a cursor ordered by file id"""
    cur_f, buf = None, []
    for row in cur:
        if row[0] != cur_f:
            if buf: yield cur_f, buf
            cur_f, buf = row[0], []
        buf.append(row)
    if buf: yield cur_f, buf


votes = collections.defaultdict(collections.Counter)      # key -> package -> votes
src_rows = collections.Counter()                           # key -> all source rows
key_info = {}
stats = collections.Counter()
bg = groups(bc); bnext = next(bg, None)
nfile = 0
for fid, srows in groups(sc):
    nfile += 1
    idx = collections.defaultdict(set)
    for _, sid, el, res, ac, f1, f2, lab, unit in srows:
        key = (ac or "", f1 or "", f2 or "")
        src_rows[key] += 1
        if key not in key_info: key_info[key] = (lab or "", unit or "", collections.Counter())
        key_info[key][2][el] += 1
        v = vk(res)
        if v is not None: idx[(sid, el, v)].add(key)
    while bnext is not None and bnext[0] < fid:
        stats["bronze rows in files absent from source"] += len(bnext[1]); bnext = next(bg, None)
    if bnext is not None and bnext[0] == fid:
        for _, sid, el, val, pk in bnext[1]:
            ks = idx.get((sid, el, vk(val)))
            if not ks: stats["bronze rows without a source match"] += 1
            elif len(ks) > 1: stats["bronze rows matching several source keys (no vote)"] += 1
            else: votes[next(iter(ks))][pk] += 1; stats["bronze rows matched to one key"] += 1
        bnext = next(bg, None)
    if nfile % 2000 == 0: log("files", nfile, dict(stats))
while bnext is not None:
    stats["bronze rows in files absent from source"] += len(bnext[1]); bnext = next(bg, None)
log("done files", nfile, dict(stats))

rec, conf = {}, {}
for k, cnt in votes.items():
    pk, n = cnt.most_common(1)[0]; tot = sum(cnt.values())
    (rec if n >= 0.95 * tot else conf)[k] = (pk, n, tot, cnt)
T = sum(src_rows.values())
cov = collections.Counter()
for k, n in src_rows.items():
    cov["recovered (your mapping)" if k in rec else "conflicting votes" if k in conf else "never in bronze"] += n
for k, v in cov.most_common(): log(f"  {k}: {v:,} rows ({v / T:.1%}), keys {sum(1 for x in src_rows if (x in rec if k.startswith('rec') else x in conf if k.startswith('con') else x not in votes))}")

with open(os.path.join(OUT, "nsw_mapping_exact.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "package_code", "votes", "share", "source_rows", "LAB_CODE", "UNITS"])
    for k, (pk, n, tot, cnt) in sorted(rec.items(), key=lambda x: -src_rows[x[0]]):
        w.writerow([*k, pk, tot, round(n / tot, 4), src_rows[k], key_info[k][0], key_info[k][1]])
with open(os.path.join(OUT, "nsw_mapping_exact_conflicts.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "packages (votes)", "source_rows"])
    for k, (pk, n, tot, cnt) in sorted(conf.items(), key=lambda x: -src_rows[x[0]]):
        w.writerow([*k, " ; ".join(f"{p} ({c})" for p, c in cnt.most_common()), src_rows[k]])
with open(os.path.join(OUT, "nsw_source_keys_not_in_mapping.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "LAB_CODE", "UNITS", "elements", "source_rows"])
    for k, n in sorted(((k, n) for k, n in src_rows.items() if k not in votes), key=lambda x: -x[1]):
        lab, unit, els = key_info[k]
        w.writerow([*k, lab, unit, ",".join(e for e, _ in els.most_common(12)), n])
log("written", len(rec), "recovered keys,", len(conf), "conflicts,", sum(1 for k in src_rows if k not in votes), "keys never in bronze")
