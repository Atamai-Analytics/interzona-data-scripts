"""Victoria (AUSTRALIA_VIC_GSV_GEOCHEMISTRY): retype panned-concentrate samples from 'Stream Sediment' to 'Heavy Mineral Concentrate'.

Evidence: 656 samples have sample_type_local 'SED | PAN2 | Stream sediment' (GSV sample-method code PAN); their sample weight is ~0.07 kg and many carry the comment
'Alluv/PC <n>m section' (pan concentrate from alluvial drill sections). Their gold is a concentrate assay (median ~770 ppm, max 434,700 ppm) and was inflating
the Stream Sediment statistics (bulk stream sediment: 95th percentile ~3 ppm Au).  Nothing is deleted or recalculated: only samples.sample_type_id changes
(sample_type_local keeps the original GSV code) and the wide table's sample_type_name is updated to match what a rebuild would produce.
Tag for rollback: samples.modified_by = 'fix_vic_pan_20261015'
   rollback:  UPDATE geochem.samples SET sample_type_id = <stream sediment id>, modified_by = NULL, modified_date = NULL WHERE modified_by = 'fix_vic_pan_20261015';
              UPDATE geochem.sample_chemistry_wide w SET sample_type_name = 'Stream Sediment' FROM geochem.samples s WHERE s.sample_id = w.sample_id AND s.modified_by = 'fix_vic_pan_20261015';  (run BEFORE clearing modified_by)
Usage: python fix_vic_pan_concentrates.py [--dry]   (--dry = apply, verify, ROLLBACK)
"""
import os, sys, time
import psycopg2

DRY = "--dry" in sys.argv
SRC = "AUSTRALIA_VIC_GSV_GEOCHEMISTRY"
FIXTAG = "fix_vic_pan_20261015"
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


hmc = one("SELECT sample_type_id FROM geochem.sample_types WHERE sample_type_name = 'Heavy Mineral Concentrate'")[0][0]
ss = one("SELECT sample_type_id FROM geochem.sample_types WHERE sample_type_name = 'Stream Sediment'")[0][0]
log("Heavy Mineral Concentrate id", hmc, "| Stream Sediment id", ss)
WHERE = "source_system = %s AND sample_type_local ILIKE %s AND sample_type_id = %s"
PAT = "SED | PAN%"
n = one(f"SELECT count(*) FROM geochem.samples WHERE {WHERE}", (SRC, PAT, ss))[0][0]
log("samples to retype", n, "| other PAN-coded samples not currently Stream Sediment (left alone)", one("SELECT count(*) FROM geochem.samples WHERE source_system = %s AND sample_type_local ILIKE %s AND sample_type_id <> %s", (SRC, PAT, ss))[0][0])
log("already carry a modified_by (must be 0)", one(f"SELECT count(*) FROM geochem.samples WHERE {WHERE} AND modified_by IS NOT NULL", (SRC, PAT, ss))[0][0])
log("before: Victoria stream sediment (n, Au_t p95, max) in wide", one("SELECT count(au_t), round(percentile_cont(0.95) WITHIN GROUP (ORDER BY au_t)::numeric, 2), round(max(au_t)::numeric, 1) FROM geochem.sample_chemistry_wide WHERE source_system = %s AND sample_type_name = 'Stream Sediment'", (SRC,)))
c.execute(f"UPDATE geochem.samples SET sample_type_id = %s, modified_by = %s, modified_date = now() WHERE {WHERE}", (hmc, FIXTAG, SRC, PAT, ss))
log("samples updated", c.rowcount)
c.execute("UPDATE geochem.sample_chemistry_wide w SET sample_type_name = 'Heavy Mineral Concentrate' FROM geochem.samples s WHERE s.sample_id = w.sample_id AND s.modified_by = %s", (FIXTAG,))
log("wide rows updated", c.rowcount)
log("after: Victoria Stream Sediment in wide (n, Au_t p95, max)", one("SELECT count(au_t), round(percentile_cont(0.95) WITHIN GROUP (ORDER BY au_t)::numeric, 2), round(max(au_t)::numeric, 1) FROM geochem.sample_chemistry_wide WHERE source_system = %s AND sample_type_name = 'Stream Sediment'", (SRC,)))
log("after: Victoria Heavy Mineral Concentrate in wide (rows, with Au, Au_t median, max)", one("SELECT count(*), count(au_t), round(percentile_cont(0.5) WITHIN GROUP (ORDER BY au_t)::numeric, 1), round(max(au_t)::numeric, 1) FROM geochem.sample_chemistry_wide WHERE source_system = %s AND sample_type_name = 'Heavy Mineral Concentrate'", (SRC,)))
log("consistency: wide sample_type_name vs samples type (mismatches, must be 0)", one("""SELECT count(*) FROM geochem.sample_chemistry_wide w JOIN geochem.samples s USING (sample_id) JOIN geochem.sample_types t ON t.sample_type_id = s.sample_type_id
   WHERE w.source_system = %s AND w.sample_type_name IS DISTINCT FROM t.sample_type_name""", (SRC,))[0][0])
log("other sources touched (must be 0)", one("SELECT count(*) FROM geochem.samples WHERE modified_by = %s AND source_system <> %s", (FIXTAG, SRC))[0][0])
log("tagged samples", one("SELECT count(*) FROM geochem.samples WHERE modified_by = %s", (FIXTAG,))[0][0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
    log("after rollback: tagged samples (must be 0)", one("SELECT count(*) FROM geochem.samples WHERE modified_by = %s", (FIXTAG,))[0][0])
else:
    g.commit(); log("COMMITTED")
g.close()
