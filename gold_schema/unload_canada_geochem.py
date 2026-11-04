"""Remove everything load_sigeom_qc.py (CANADA_QC_SIGEOM) or load_sask_sgs.py (CANADA_SK_SGS) loaded, so the source can be reloaded cleanly.

Removes: the source's wide-table rows, result and classification partitions, lithology observations, interval QC flags, intercepts, samples,
external ids, drill-hole surveys and drill holes. Keeps: the SIGEOM-* / SKGS-* packages and their source_package_rules, the drilling schema.
Usage: python unload_canada_geochem.py CANADA_QC_SIGEOM|CANADA_SK_SGS [--dry]   (--dry = delete, report, ROLLBACK)
"""
import os, sys, time
import psycopg2

SRC = sys.argv[1]
CFG = {"CANADA_QC_SIGEOM": ("canada_qc_sigeom", "SIGEOM", "migration_sigeom_qc_"), "CANADA_SK_SGS": ("canada_sk_sgs", "SASK_SGS", "migration_sask_sgs_")}
PART, XID, TAG = CFG[SRC]
DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")


def run(label, sql, *a):
    t = time.time(); c.execute(sql, a); print(f"{label}: {c.rowcount} ({time.time() - t:.0f}s)", flush=True)


run("wide rows", "DELETE FROM geochem.sample_chemistry_wide WHERE source_system = %s", SRC)
for part in (f"result_classifications_{PART}", f"analytical_results_{PART}"):
    c.execute("SELECT to_regclass(%s)", (f"geochem.{part}",))
    if c.fetchone()[0]:
        parent = "analytical_results" if part.startswith("analytical") else "result_classifications"
        c.execute(f"ALTER TABLE geochem.{parent} DETACH PARTITION geochem.{part}")   # the classification FK refers to the result partition
        c.execute(f"DROP TABLE geochem.{part}"); print("dropped partition", part)
c.execute("DELETE FROM geochem.classification_batches WHERE source_system = %s", (SRC,))
run("intercepts", "DELETE FROM drilling.intercepts WHERE source_system = %s", SRC)
run("interval QC flags", "DELETE FROM drilling.interval_qc WHERE drillhole_id IN (SELECT drillhole_id FROM drilling.drillholes WHERE source_system = %s)", SRC)
run("lithology observations", "DELETE FROM geochem.lithology_observations WHERE created_by LIKE %s", TAG + "%")
run("external ids", "DELETE FROM core.external_ids WHERE source_system = %s", XID)
run("samples", "DELETE FROM geochem.samples WHERE source_system = %s", SRC)
run("surveys", "DELETE FROM drilling.surveys WHERE drillhole_id IN (SELECT drillhole_id FROM drilling.drillholes WHERE source_system = %s)", SRC)
run("drill holes", "DELETE FROM drilling.drillholes WHERE source_system = %s", SRC)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
g.close()
