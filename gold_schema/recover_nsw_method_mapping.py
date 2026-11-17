"""Recover the NSW method mapping (the dropped "NSWAnalyticalMapping" table: (ASSAYCODE, FIELD1, FIELD2) -> package code, built by hand by the user)
from what the Dec-2025 bronze load produced, and measure how much of the full NSW source it covers. READ-ONLY on both databases.

Old loader (D:/CriticalMineralsDB/Scripts/working_23_Dec-2025.sql): nsw_dd_sgc_data s JOIN nsw_dd_gch_meta m (FILE_ID, ASS_ID) JOIN nsw_dd_rpt_code c
(FILE_ID, CODE = ASSAYCODE) -> key (m.ASSAYCODE, c.FIELD1, c.FIELD2) -> "NSWAnalyticalMapping"."Code" = package_code; analyte = m.ELEMENT; samples matched on
samples.samplenumber = SAMPLEID AND samples.fieldid = FILE_ID (bronze datasource 'Geological Survey of NSW').
Recovery: bronze active+inactive NSW results grouped by (FILE_ID = fieldid, analyte_code, package_code) joined to staging (FILE_ID, ELEMENT) ->
(ASSAYCODE, FIELD1, FIELD2). A key is RECOVERED when one package carries >= 90 % of its matched rows; CONFLICT otherwise. source_rows = all source rows using the key.
Outputs (scratch dir given as argv[1]): nsw_mapping_recovered.csv, nsw_mapping_conflicts.csv, nsw_source_keys_unmapped.csv (ranked by source rows).
"""
import csv, os, sys, collections
import psycopg2

OUT = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def con(db):
    g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db, user=ENV["LITHODAT_DB_USER"],
                         password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=6)
    g.set_session(readonly=True); c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET work_mem = '1GB'")
    return g, c


# 1. bronze: (FILE_ID, element, package) -> rows
_, b = con("criticialmineralsexp")
b.execute("""SELECT s.fieldid, a.analyte_code, p.package_code, count(*)
             FROM analytical_results r JOIN samples s ON s.sampleid = r.sampleid JOIN locations l ON l.locationid = s.locationid
             JOIN analytes a ON a.analyte_id = r.analyte_id JOIN analytical_packages p ON p.package_id = r.package_id
             WHERE l.datasource = 'Geological Survey of NSW' GROUP BY 1, 2, 3""")
bronze = collections.defaultdict(dict)
for fid, el, pk, n in b.fetchall():
    bronze[(str(fid), el)][pk] = n
print("bronze (file, element) groups", len(bronze), "rows", sum(sum(v.values()) for v in bronze.values()), flush=True)

# 2. staging: per (FILE_ID, ELEMENT, ASSAYCODE, FIELD1, FIELD2, LAB_CODE, UNITS) row counts
_, s = con("criticalminerals")
s.execute('''SELECT m."FILE_ID"::text, m."ELEMENT", m."ASSAYCODE"::text, c."FIELD1"::text, c."FIELD2"::text, m."LAB_CODE"::text, m."UNITS"::text, count(*)
             FROM nsw_dd_sgc_data d JOIN nsw_dd_gch_meta m ON m."FILE_ID" = d."FILE_ID" AND m."ASS_ID" = d."ASS_ID"
             LEFT JOIN nsw_dd_rpt_code c ON c."FILE_ID"::text = m."FILE_ID"::text AND c."CODE"::text = m."ASSAYCODE"::text
             GROUP BY 1, 2, 3, 4, 5, 6, 7''')
src = s.fetchall()
print("staging groups", len(src), "rows", sum(r[7] for r in src), flush=True)

# 3. recover key -> package
key_pk = collections.defaultdict(collections.Counter)
for fid, el, ac, f1, f2, lab, unit, n in src:
    pk = bronze.get((fid, el))
    if pk and len(pk) == 1:
        key_pk[(ac, f1, f2)][next(iter(pk))] += n
rec, conf = {}, {}
for k, cnt in key_pk.items():
    tot_k = sum(cnt.values()); top_pk, top_n = cnt.most_common(1)[0]
    (rec if top_n >= 0.9 * tot_k else conf)[k] = cnt          # recovered = one package carries >= 90 % of the matched rows
full = collections.Counter()
for fid, el, ac, f1, f2, lab, unit, n in src: full[(ac, f1, f2)] += n   # ALL source rows using the key
print("keys recovered", len(rec), "conflicting", len(conf), flush=True)

# 4. coverage of the whole source
cov = collections.Counter(); unm = collections.Counter(); unm_info = {}
for fid, el, ac, f1, f2, lab, unit, n in src:
    k = (ac, f1, f2)
    if k in rec: cov["mapped (recovered)"] += n
    elif k in conf: cov["key with conflicting packages"] += n
    else:
        cov["unmapped"] += n; unm[k] += n; unm_info.setdefault(k, (lab, unit))
tot = sum(cov.values())
for k, v in cov.most_common(): print(f"  {k}: {v:,} ({v / tot:.1%})")

with open(os.path.join(OUT, "nsw_mapping_recovered.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "package_code", "source_rows"])
    for k, cnt in sorted(rec.items(), key=lambda x: -sum(x[1].values())):
        pk, n = cnt.most_common(1)[0]; w.writerow([*k, pk, full[k]])
with open(os.path.join(OUT, "nsw_mapping_conflicts.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "packages (matched rows)", "source_rows"])
    for k, cnt in sorted(conf.items(), key=lambda x: -sum(x[1].values())):
        w.writerow([*k, " ; ".join(f"{p} ({n})" for p, n in cnt.most_common()), full[k]])
with open(os.path.join(OUT, "nsw_source_keys_unmapped.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ASSAYCODE", "FIELD1", "FIELD2", "LAB_CODE", "UNITS", "source_rows"])
    for k, n in unm.most_common():
        w.writerow([*k, *unm_info[k], n])
print("top unmapped keys:")
for k, n in unm.most_common(25): print(f"  {n:>9,}  {k}  lab/unit {unm_info[k]}")
