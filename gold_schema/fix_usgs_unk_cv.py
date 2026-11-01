"""USGS NGDB package UNK-CV (package_id 138): INAA counting-error percentages that were loaded as concentrations -> deactivate (is_active = false).

Evidence (audit 2026-10-29, audit_drill3.py): 34,964 active results on 6,470 samples, unit '%', analytes Fe Na Co Zn Ni As Sb W Cr K; each element has only 9-32 distinct small integer values
(1, 2, 5, 10, 15 ...); on the same samples the INAA package gives e.g. Ni 15.3 ppm where UNK-CV says 15 % (median ratio 3,053 x). They are the coefficient of variation (%) of the INAA counts.
Nothing is deleted: rows are set is_active = false and logged in geochem.result_active_reconcile_log (reason below); ids are saved to _unk_cv_deactivated_ids.csv.
The USGS part of geochem.sample_chemistry_wide must be rebuilt afterwards:  python build_chem_wide.py USA_USGS_NGDB [--dry]
Rollback:  UPDATE geochem.analytical_results SET is_active = true WHERE source_system = 'USA_USGS_NGDB' AND result_id IN (SELECT result_id FROM geochem.result_active_reconcile_log WHERE reason LIKE 'claude_unk_cv_20261030%');
           (then DELETE those log rows and rebuild the USGS wide table)
Usage: python fix_usgs_unk_cv.py [--dry]   (--dry = apply, verify, ROLLBACK)
"""
import csv, os, sys, time
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
SRC = "USA_USGS_NGDB"
PKG = "UNK-CV"
REASON = "claude_unk_cv_20261030: INAA counting-error percent (coefficient of variation) loaded as concentration; not a result"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")


def one(sql, p=None):
    c.execute(sql, p); return c.fetchall()


pid = one("SELECT package_id FROM geochem.analytical_packages WHERE package_code = %s", (PKG,))[0][0]
log("package", PKG, "id", pid)
# safety checks: only the expected shape of rows is touched
rows = one("""SELECT r.result_id, r.sample_id, r.analyte_symbol, r.value, r.unit_code FROM geochem.analytical_results r WHERE r.source_system = %s AND r.package_id = %s AND r.is_active""", (SRC, pid))
log("active UNK-CV results", len(rows), "| samples", len({r[1] for r in rows}), "| units", {r[4] for r in rows}, "| analytes", sorted({r[2] for r in rows}))
assert {r[4] for r in rows} <= {"%"}, "unexpected units in UNK-CV"
assert all(float(r[3]) == int(float(r[3])) for r in rows), "non-integer values: not the pattern this fix was designed for"
log("distinct values (all analytes)", len({float(r[3]) for r in rows}), "| max", max(float(r[3]) for r in rows))
log("rows already in the reconcile log for this reason (must be 0)", one("SELECT count(*) FROM geochem.result_active_reconcile_log WHERE reason LIKE 'claude_unk_cv_20261030%'")[0][0])
log("before: active USGS results", one("SELECT count(*) FROM geochem.analytical_results WHERE source_system = %s AND is_active", (SRC,))[0][0])

with open(os.path.join(HERE, "_unk_cv_deactivated_ids.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["result_id", "sample_id", "analyte", "value", "unit"]); w.writerows(rows)
execute_values(c, "INSERT INTO geochem.result_active_reconcile_log (result_id, source_system, old_is_active, new_is_active, reason, changed_at) VALUES %s",
               [(r[0], SRC, True, False, REASON) for r in rows], template="(%s, %s, %s, %s, %s, now())", page_size=5000)
c.execute("UPDATE geochem.analytical_results SET is_active = false WHERE source_system = %s AND package_id = %s AND is_active", (SRC, pid))
log("deactivated", c.rowcount)
assert c.rowcount == len(rows)
log("after: active UNK-CV (must be 0)", one("SELECT count(*) FROM geochem.analytical_results WHERE source_system = %s AND package_id = %s AND is_active", (SRC, pid))[0][0])
log("after: active USGS results", one("SELECT count(*) FROM geochem.analytical_results WHERE source_system = %s AND is_active", (SRC,))[0][0])
log("log rows written", one("SELECT count(*) FROM geochem.result_active_reconcile_log WHERE reason LIKE 'claude_unk_cv_20261030%'")[0][0])
log("INAA (UNK-INAA) rows untouched (still active)", one("SELECT count(*) FROM geochem.analytical_results r JOIN geochem.analytical_packages p USING (package_id) WHERE r.source_system = %s AND p.package_code = 'UNK-INAA' AND r.is_active", (SRC,))[0][0])
log("wide table cells that currently rest on these results (USGS wide rows with a _p value for the 10 analytes on affected samples):",
    one("""SELECT count(*) FROM geochem.sample_chemistry_wide w WHERE w.source_system = %s AND w.sample_id IN (SELECT DISTINCT sample_id FROM geochem.analytical_results WHERE source_system = %s AND package_id = %s)
           AND (w.ni_p IS NOT NULL OR w.co_p IS NOT NULL OR w.zn_p IS NOT NULL OR w.as_p IS NOT NULL OR w.sb_p IS NOT NULL OR w.w_p IS NOT NULL OR w.cr_p IS NOT NULL OR w.fe_p IS NOT NULL OR w.na_p IS NOT NULL OR w.k_p IS NOT NULL)""", (SRC, SRC, pid))[0][0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
    log("after rollback: active UNK-CV", one("SELECT count(*) FROM geochem.analytical_results WHERE source_system = %s AND package_id = %s AND is_active", (SRC, pid))[0][0], "| log rows", one("SELECT count(*) FROM geochem.result_active_reconcile_log WHERE reason LIKE 'claude_unk_cv_20261030%'")[0][0])
else:
    g.commit(); log("COMMITTED - now rebuild the USGS wide table: python build_chem_wide.py USA_USGS_NGDB")
g.close()
