"""Relabel samples that sit in the ARGENTINA_SEGEMAR / GREENLAND_GEUS sets but come from another bronze data source.

The earlier migration assigned source_system by country.  Bronze says 383 of those samples are USGS (NGDB) and 1,053 are from the Wu et al.
global zircon U-Th-Pb database (no results or ages in gold).  This script, in ONE transaction:
  * moves the USGS-origin samples AND their results + classifications (+ reconcile-log rows) to source_system 'USA_USGS_NGDB'
    (insert into the new partitions with the same result_id, then delete from the old ones);
  * relabels the Wu samples 'GLOBAL_ZIRCON_WU' and registers that source in core.data_sources (CC BY 4.0, Zenodo 10.5281/zenodo.8303076);
  * deletes the wide-table rows of all 1,436 samples (the USGS ones are rebuilt with the USGS wide table).
Input: gold_schema/_foreign_samples.json {gold sample_id: [old source_system, origin]}.
Usage: python fix_foreign_source_labels.py [--dry]
"""
import json, os, sys, time
import psycopg2

DRY = "--dry" in sys.argv
CB = "relabel_foreign_20261012"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


foreign = json.load(open(os.path.join(HERE, "_foreign_samples.json"), encoding="utf-8"))
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0"); c.execute("SET lock_timeout = '60s'")
c.execute("SELECT sample_id, source_system FROM geochem.samples WHERE sample_id = ANY(%s)", ([int(k) for k in foreign],))
cur = dict(c.fetchall())
usgs, wu = [], []
for sid_s, (old, origin) in foreign.items():
    sid = int(sid_s)
    assert cur[sid] == old, (sid, cur[sid], old)
    (usgs if origin == "USGS" else wu).append(sid)
log("USGS-origin samples", len(usgs), "| Wu samples", len(wu))
assert len(usgs) == 383 and len(wu) == 1053

def counts(tag):
    c.execute("""SELECT 'samples', source_system, count(*) FROM geochem.samples WHERE source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS','USA_USGS_NGDB','GLOBAL_ZIRCON_WU') GROUP BY 2
      UNION ALL SELECT 'results', source_system, count(*) FROM geochem.analytical_results WHERE source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS','USA_USGS_NGDB') GROUP BY 2
      UNION ALL SELECT 'classif', source_system, count(*) FROM geochem.result_classifications WHERE source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS','USA_USGS_NGDB') GROUP BY 2
      UNION ALL SELECT 'wide', source_system, count(*) FROM geochem.sample_chemistry_wide WHERE source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS','USA_USGS_NGDB') GROUP BY 2 ORDER BY 1, 2""")
    r = c.fetchall(); log(tag, r); return r

before = counts("BEFORE")

# --- move USGS-origin results + classifications
c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'geochem' AND table_name = 'analytical_results' ORDER BY ordinal_position")
cols = [r[0] for r in c.fetchall()]
sel = ", ".join("'USA_USGS_NGDB'" if x == "source_system" else "r." + x for x in cols)
c.execute("CREATE TEMP TABLE _mv ON COMMIT DROP AS SELECT result_id, source_system AS old_src FROM geochem.analytical_results WHERE sample_id = ANY(%s) AND source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS')", (usgs,))
c.execute("SELECT old_src, count(*) FROM _mv GROUP BY 1"); log("results to move", c.fetchall())
c.execute("ALTER TABLE geochem.analytical_results DISABLE TRIGGER trg_resolve_analytical_result_labels")
c.execute(f"INSERT INTO geochem.analytical_results ({', '.join(cols)}) OVERRIDING SYSTEM VALUE SELECT {sel} FROM geochem.analytical_results r JOIN _mv m ON m.result_id = r.result_id AND m.old_src = r.source_system")
n_ins = c.rowcount
c.execute("""INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
  SELECT k.result_id, 'USA_USGS_NGDB', k.result_status, k.dl_value, k.dl_source, k.use_in_statistics FROM geochem.result_classifications k JOIN _mv m ON m.result_id = k.result_id AND m.old_src = k.source_system""")
n_cls = c.rowcount
c.execute("UPDATE geochem.result_active_reconcile_log l SET source_system = 'USA_USGS_NGDB' FROM _mv m WHERE l.result_id = m.result_id AND l.source_system = m.old_src")
n_log = c.rowcount
c.execute("DELETE FROM geochem.result_classifications k USING _mv m WHERE k.result_id = m.result_id AND k.source_system = m.old_src")
c.execute("DELETE FROM geochem.analytical_results r USING _mv m WHERE r.result_id = m.result_id AND r.source_system = m.old_src")
c.execute("ALTER TABLE geochem.analytical_results ENABLE TRIGGER trg_resolve_analytical_result_labels")
log("moved results", n_ins, "classifications", n_cls, "reconcile-log rows", n_log)
assert n_ins == n_cls

# --- sample labels
c.execute("UPDATE geochem.samples SET source_system = 'USA_USGS_NGDB' WHERE sample_id = ANY(%s)", (usgs,)); log("samples -> USA_USGS_NGDB", c.rowcount)
c.execute("UPDATE geochem.samples SET source_system = 'GLOBAL_ZIRCON_WU' WHERE sample_id = ANY(%s)", (wu,)); log("samples -> GLOBAL_ZIRCON_WU", c.rowcount)
c.execute("DELETE FROM geochem.sample_chemistry_wide WHERE sample_id = ANY(%s)", (usgs + wu,)); log("wide rows removed", c.rowcount)

# --- register the Wu source
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded, licence_status, caveats, evidence_location, evidence_date, is_active, created_by)
SELECT 'GLOBAL_ZIRCON_WU', 'Wu, Y., Fang, X., Ji, J.', 'Global zircon U-Th-Pb geochronology database, version 2.1', 'CC BY 4.0', 'https://zenodo.org/records/8303076', true,
 'Wu, Y., Fang, X., Ji, J. (2023) A global zircon U-Th-Pb geochronological database. Earth System Science Data 15, 5171-5188; Zenodo, doi:10.5281/zenodo.8303076 (CC BY 4.0).', true,
 'Cleared: Zenodo record 8303076 states license cc-by-4.0, access open (checked 2026-10-12).',
 'Only 1,053 sample points (Argentina 709, Greenland 344) are in the gold layer, with no ages or results; the remaining database is not loaded. Compiled from about 12,000 papers and theses.',
 'D:/CriticalMineralsDB/Documents/Licence_Evidence/GLOBAL_ZIRCON_WU/ (Zenodo record JSON, EVIDENCE.md)', '2026-10-12', true, %s
WHERE NOT EXISTS (SELECT 1 FROM core.data_sources WHERE source_system = 'GLOBAL_ZIRCON_WU')""", (CB,))

after = counts("AFTER")
c.execute("SELECT count(*) FROM geochem.result_classifications k LEFT JOIN geochem.analytical_results r ON r.result_id = k.result_id AND r.source_system = k.source_system WHERE r.result_id IS NULL AND k.source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS','USA_USGS_NGDB')")
log("orphan classifications (must be 0)", c.fetchone()[0])
c.execute("SELECT count(*) FROM geochem.analytical_results r LEFT JOIN geochem.result_classifications k ON k.result_id = r.result_id AND k.source_system = r.source_system WHERE k.result_id IS NULL AND r.source_system IN ('ARGENTINA_SEGEMAR','GREENLAND_GEUS','USA_USGS_NGDB')")
log("results without classification (must be 0)", c.fetchone()[0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
g.close()
