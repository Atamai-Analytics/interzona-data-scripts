"""Remove everything load_mrt_tas.py loaded for AUSTRALIA_TAS_MRT, so the source can be reloaded cleanly.

Removes: the source's wide-table rows, result and classification partitions, lithology observations, interval QC flags, samples, external ids
(SAMPLE / DRILLHOLE, MRT_TIGER), drill-hole surveys and drill holes. Keeps: MRT-* packages, their source_package_rules, the ZnO analyte, the
drilling schema itself, core.data_sources.
Usage: python unload_mrt_tas.py [--dry]   (--dry = delete, report, ROLLBACK)
"""
import os, sys, time
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_TAS_MRT"
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
for part in ("result_classifications_australia_tas_mrt", "analytical_results_australia_tas_mrt"):
    c.execute("SELECT to_regclass(%s)", (f"geochem.{part}",))
    if c.fetchone()[0]:
        parent = "analytical_results" if part.startswith("analytical") else "result_classifications"
        c.execute(f"ALTER TABLE geochem.{parent} DETACH PARTITION geochem.{part}")   # the classification FK refers to the result partition
        c.execute(f"DROP TABLE geochem.{part}"); print("dropped partition", part)
c.execute("DELETE FROM geochem.classification_batches WHERE source_system = %s", (SRC,))
run("lithology observations", """DELETE FROM geochem.lithology_observations WHERE created_by LIKE 'migration_mrt_tas_%%'""")
c.execute("SELECT to_regclass('drilling.interval_qc')")
if c.fetchone()[0]:
    run("interval QC flags", "DELETE FROM drilling.interval_qc WHERE drillhole_id IN (SELECT drillhole_id FROM drilling.drillholes WHERE source_system = %s)", SRC)
run("external ids", "DELETE FROM core.external_ids WHERE source_system = 'MRT_TIGER'")
run("samples", "DELETE FROM geochem.samples WHERE source_system = %s", SRC)
run("surveys", "DELETE FROM drilling.surveys WHERE drillhole_id IN (SELECT drillhole_id FROM drilling.drillholes WHERE source_system = %s)", SRC)
run("drill holes (wedge links first)", "UPDATE drilling.drillholes SET parent_drillhole_id = NULL WHERE source_system = %s", SRC)
run("drill holes", "DELETE FROM drilling.drillholes WHERE source_system = %s", SRC)
if DRY:
    g.rollback(); print("DRY RUN - rolled back")
else:
    g.commit(); print("COMMITTED")
