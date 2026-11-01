"""Backfill geochem.result_classifications AND reconcile is_active for sources migrated before the active-only rule
(Argentina SEGEMAR: partial classification; Greenland GEUS: none).

Findings that motivated this: the 2026-09 migration copied ALL bronze result rows, including rows bronze had marked isactive=false
(loader-time duplicates/overlaps and QC deactivations: values >100 %, sentinel 999, plausible-max exceedances ...), and marked them
is_active = true in gold. Here every gold result is matched to its bronze result on the natural key (sample, analyte, unit, package, qualifier,
value, report_number, date_analysed, detection limits); where bronze has the row inactive the gold row is set is_active = false.
Classification is then copied from bronze (richer vocabulary) with a qualifier/value rule as fallback. Existing gold classification rows are kept.
Usage: python backfill_classifications.py ARGENTINA_SEGEMAR|GREENLAND_GEUS [--dry]
"""
import os, sys, csv, time
import psycopg2

SRC = sys.argv[1]
DRY = "--dry" in sys.argv
CFG = {
    "ARGENTINA_SEGEMAR": ("analytical_results_argentina_segemar", "result_classifications_argentina_segemar"),
    "GREENLAND_GEUS": ("analytical_results_greenland_geus", "result_classifications_greenland_geus"),
}[SRC]
TAG = "claude_active_reconcile_20261011"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def connect(db):
    return psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname=db, user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])


def log(*a):
    print(time.strftime("%H:%M:%S"), SRC, *a, flush=True)


R, K = CFG
g = connect("interzona_cm")
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SET work_mem = '512MB'")
c.execute("SELECT e.source_id::bigint FROM core.external_ids e JOIN geochem.samples s ON s.sample_id = e.entity_id AND s.source_system = %s WHERE e.entity_type = 'SAMPLE' AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'", (SRC,))
bronze_ids = [r[0] for r in c.fetchall()]
log("gold samples with bronze ids", len(bronze_ids))

b = connect("criticialmineralsexp")
pre = b.cursor(); pre.execute("SET statement_timeout = 0")
bc = b.cursor("cls_cur")
bc.itersize = 100000
csv_path = os.path.join(HERE, f"_cls_{SRC}.csv")
t0 = time.time(); n = 0
bc.execute("""
SELECT r.sampleid, a.analyte_code, u.unitcode, coalesce(q.qualifier_code, ''), p.package_code, r.value, coalesce(r.report_number, ''), r.date_analysed,
       r.lower_detection_limit, r.upper_detection_limit, r.isactive, rc.result_status, rc.dl_value, rc.dl_source, rc.use_in_statistics
FROM analytical_results r JOIN analytes a ON a.analyte_id = r.analyte_id JOIN units u ON u.unitid = r.unitid
JOIN analytical_packages p ON p.package_id = r.package_id LEFT JOIN qualifiers q ON q.qualifier_id = r.qualifier_id
LEFT JOIN result_classifications rc ON rc.result_id = r.result_id
WHERE r.sampleid = ANY(%s)""", (bronze_ids,))
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for row in bc:
        w.writerow(["\\N" if x is None else x for x in row]); n += 1
bc.close(); b.rollback(); b.close()
log("bronze rows exported (active + inactive)", n, "in", round(time.time() - t0), "s")

c.execute("""CREATE TABLE geochem._stage_cls (bsid bigint, analyte_code text, unit_code text, qual text, package_code text, value numeric, report text, date_analysed date,
 ldl numeric, udl numeric, isactive boolean, status text, dl_value numeric, dl_source text, use_stats boolean)""")
with open(csv_path, "r", encoding="utf-8") as f:
    c.copy_expert("COPY geochem._stage_cls FROM STDIN WITH (FORMAT csv, NULL '\\N')", f)
log("staged")

# one row per natural key with active / inactive counts and the classification of each side
c.execute("""CREATE TABLE geochem._stage_k AS
SELECT bsid, analyte_code, unit_code, qual, package_code, value, report, date_analysed, ldl, udl,
  count(*) FILTER (WHERE isactive) AS a_n, count(*) FILTER (WHERE NOT isactive) AS i_n,
  min(status) FILTER (WHERE isactive) AS a_status, max(status) FILTER (WHERE isactive) AS a_status_max,
  min(dl_value) FILTER (WHERE isactive) AS a_dl, min(dl_source) FILTER (WHERE isactive) AS a_src, bool_and(use_stats) FILTER (WHERE isactive) AS a_use,
  min(status) FILTER (WHERE NOT isactive) AS i_status, min(dl_value) FILTER (WHERE NOT isactive) AS i_dl, min(dl_source) FILTER (WHERE NOT isactive) AS i_src
FROM geochem._stage_cls GROUP BY bsid, analyte_code, unit_code, qual, package_code, value, report, date_analysed, ldl, udl""")
c.execute("CREATE INDEX ON geochem._stage_k (bsid, analyte_code, package_code)")
c.execute("ANALYZE geochem._stage_k")
c.execute("SELECT count(*), count(*) FILTER (WHERE a_n > 0 AND i_n > 0), count(*) FILTER (WHERE a_status IS DISTINCT FROM a_status_max) FROM geochem._stage_k")
log("bronze keys, keys with both active and inactive rows, keys with conflicting active statuses", c.fetchone())

# every gold result of the source with its key and a per-key sequence number
c.execute(f"""
CREATE TABLE geochem._gold_all AS
SELECT r.result_id, r.source_system, r.is_active, e.source_id::bigint AS bsid, a.analyte_code, r.unit_code, coalesce(r.qualifier_code, '') AS qual, p.package_code, r.value,
       coalesce(r.report_number, '') AS report, r.date_analysed, r.lower_detection_limit AS ldl, r.upper_detection_limit AS udl, (k.result_id IS NOT NULL) AS has_cls,
       row_number() OVER (PARTITION BY e.source_id::bigint, a.analyte_code, r.unit_code, coalesce(r.qualifier_code, ''), p.package_code, r.value, coalesce(r.report_number, ''), r.date_analysed,
                          r.lower_detection_limit, r.upper_detection_limit ORDER BY r.result_id) AS rn
FROM geochem.{R} r
JOIN geochem.analytes a ON a.analyte_id = r.analyte_id
JOIN geochem.analytical_packages p ON p.package_id = r.package_id
JOIN core.external_ids e ON e.entity_type = 'SAMPLE' AND e.entity_id = r.sample_id AND e.source_system = 'BRONZE_CRITICIALMINERALSEXP'
LEFT JOIN geochem.{K} k ON k.result_id = r.result_id""")
c.execute("SELECT count(*), count(*) FILTER (WHERE has_cls) FROM geochem._gold_all"); ng, nhc = c.fetchone()
c.execute(f"SELECT count(*) FROM geochem.{R}"); assert c.fetchone()[0] == ng, "join lost gold rows"
log("gold results", ng, "already classified", nhc)

c.execute("""
CREATE TABLE geochem._gold_plan AS
SELECT m.result_id, m.source_system, m.is_active, m.has_cls, m.value, m.qual, m.ldl, m.rn,
  s.bsid IS NOT NULL AS matched, s.a_n, s.i_n, s.a_status, s.a_dl, s.a_src, s.a_use, s.i_status, s.i_dl, s.i_src,
  CASE WHEN s.bsid IS NULL THEN m.is_active ELSE m.rn <= s.a_n END AS want_active
FROM geochem._gold_all m
LEFT JOIN geochem._stage_k s ON s.bsid = m.bsid AND s.analyte_code = m.analyte_code AND s.package_code = m.package_code AND s.unit_code = m.unit_code
 AND s.qual = m.qual AND s.value IS NOT DISTINCT FROM m.value AND s.report = m.report AND s.date_analysed IS NOT DISTINCT FROM m.date_analysed
 AND s.ldl IS NOT DISTINCT FROM m.ldl AND s.udl IS NOT DISTINCT FROM m.udl""")
c.execute("SELECT count(*) FROM geochem._gold_plan"); assert c.fetchone()[0] == ng, "plan join multiplied rows"
c.execute("SELECT count(*) FILTER (WHERE NOT matched), count(*) FILTER (WHERE matched AND want_active), count(*) FILTER (WHERE matched AND NOT want_active), count(*) FILTER (WHERE matched AND is_active AND NOT want_active) FROM geochem._gold_plan")
unm, wa, wi, todeact = c.fetchone()
log("unmatched (kept as is)", unm, "bronze-active", wa, "bronze-inactive", wi, "to deactivate in gold", todeact)
c.execute("SELECT count(*) FROM geochem._gold_plan WHERE matched AND a_n + i_n > (SELECT 0)")  # sanity touch
c.execute("SELECT count(*) FROM geochem._gold_plan WHERE matched AND rn > a_n + i_n")
log("gold rows beyond the bronze row count of their key (should be 0)", c.fetchone()[0])

# 1) deactivate gold rows that bronze has inactive
c.execute("""CREATE TABLE IF NOT EXISTS geochem.result_active_reconcile_log (result_id bigint, source_system varchar(40), old_is_active boolean, new_is_active boolean,
 reason text, changed_at timestamptz DEFAULT now())""")
c.execute(f"""INSERT INTO geochem.result_active_reconcile_log (result_id, source_system, old_is_active, new_is_active, reason)
 SELECT p.result_id, p.source_system, true, false, '{TAG}: bronze row isactive=false' FROM geochem._gold_plan p WHERE p.is_active AND p.matched AND NOT p.want_active""")
c.execute(f"""UPDATE geochem.{R} r SET is_active = false
 FROM geochem._gold_plan p WHERE p.result_id = r.result_id AND r.is_active AND p.matched AND NOT p.want_active""")
log("gold results deactivated", c.rowcount)

# 2) classification for rows without one
c.execute(f"""
INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
SELECT result_id, source_system,
  coalesce(CASE WHEN want_active THEN a_status ELSE coalesce(i_status, a_status) END,
    CASE WHEN qual IN ('<','ND','L','N') THEN 'BELOW_DL_QUALIFIED' WHEN qual IN ('>','G') THEN 'ABOVE_UDL' WHEN value IS NULL THEN 'NULL_RESULT' ELSE 'DETECTED' END),
  CASE WHEN CASE WHEN want_active THEN a_status ELSE coalesce(i_status, a_status) END IS NOT NULL THEN CASE WHEN want_active THEN a_dl ELSE coalesce(i_dl, a_dl) END
       WHEN qual IN ('<','L','N') THEN coalesce(ldl, value) END,
  CASE WHEN CASE WHEN want_active THEN a_status ELSE coalesce(i_status, a_status) END IS NOT NULL THEN CASE WHEN want_active THEN a_src ELSE coalesce(i_src, a_src) END
       WHEN qual IN ('<','L','N') THEN CASE WHEN ldl IS NOT NULL THEN 'QUALIFIER_LDL' ELSE 'QUALIFIER_VALUE' END END,
  want_active AND coalesce(CASE WHEN a_status IS NOT NULL THEN a_use END, (qual NOT IN ('<','ND','L','N','>','G') AND value IS NOT NULL))
FROM geochem._gold_plan WHERE NOT has_cls""")
log("classification rows inserted", c.rowcount)
# inactive rows must never count as 'use in statistics'
c.execute(f"""UPDATE geochem.{K} k SET use_in_statistics = false FROM geochem.{R} r WHERE r.result_id = k.result_id AND NOT r.is_active AND k.use_in_statistics""")
log("use_in_statistics cleared on inactive rows", c.rowcount)

c.execute(f"SELECT r.is_active, k.result_status, k.use_in_statistics, count(*) FROM geochem.{R} r JOIN geochem.{K} k ON k.result_id = r.result_id GROUP BY 1,2,3 ORDER BY 1 DESC, 4 DESC")
for r in c.fetchall():
    log("  now", r)
c.execute(f"SELECT count(*) FROM geochem.{R} r LEFT JOIN geochem.{K} k ON k.result_id = r.result_id WHERE k.result_id IS NULL")
left = c.fetchone()[0]
log("results still without classification", left)
assert left == 0
for t in ("_stage_cls", "_stage_k", "_gold_all", "_gold_plan"):
    c.execute(f"DROP TABLE geochem.{t}")
if DRY:
    g.rollback(); log("DRY - rolled back")
else:
    g.commit(); log("COMMITTED")
os.remove(csv_path)
