"""Undo QC rule 1 (SUSPECT) for 50 USGS NGDB heavy-mineral-concentrate results that are plausible in concentrates (2026-11-14):
Hf 5,200-11,000 ppm (zircon-rich), Th 11,000-100,000 ppm (monazite-rich), U 15,000-20,000 ppm. Kept SUSPECT: Zn 781,000 ppm (above ZnS 67 %)
and P 30 % (above apatite 18 %). Ids from qc_usa_usgs_ngdb_impossible_20261114_095917.csv; same rollback as documented in qc_results.py.
"""
import csv, os, psycopg2
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
ids = [int(r["result_id"]) for r in csv.DictReader(open(os.path.join(HERE, "qc_usa_usgs_ngdb_impossible_20261114_095917.csv"), encoding="utf-8"))
       if r["analyte_code"] in ("Hf", "Th", "U")]
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("""SELECT count(*) FROM geochem.analytical_results_usa_usgs_ngdb r JOIN geochem.samples s USING (sample_id)
             WHERE r.result_id = ANY(%s) AND s.created_by = 'migration_usgs_ngdb_conc_20261114'""", (ids,))
assert c.fetchone()[0] == len(ids) == 50
c.execute("""UPDATE geochem.result_classifications SET result_status = 'DETECTED', use_in_statistics = true
             WHERE source_system = 'USA_USGS_NGDB' AND result_status = 'SUSPECT' AND result_id = ANY(%s)""", (ids,))
print("restored", c.rowcount); assert c.rowcount == 50
g.commit()
