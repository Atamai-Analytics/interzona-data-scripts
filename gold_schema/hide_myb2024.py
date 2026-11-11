"""Hide (or restore) the USGS 2024 Minerals Yearbook load (source USGS_MYB2024, tag migration_usgs_myb2024_20261111) from answers.
Hidden 2026-11-11 on the user's OK because answers listed the same plant twice (older regional row + 2024 row on different sites) until a
'superseded by' link is built. Hide = move the capacity and ownership rows into holding tables core.hold_myb2024_facility_capacity /
core.hold_myb2024_occurrence_ownership (the app's SQL never sees them), deactivate the 2024-only sites and the commodities the load added.
Restore = the reverse. Usage: python hide_myb2024.py hide|restore
"""
import os, sys, psycopg2

MODE = sys.argv[1]
TAG = "migration_usgs_myb2024_20261111"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
if MODE == "hide":
    c.execute("CREATE TABLE IF NOT EXISTS core.hold_myb2024_facility_capacity (LIKE core.facility_capacity INCLUDING DEFAULTS)")
    c.execute("CREATE TABLE IF NOT EXISTS core.hold_myb2024_occurrence_ownership (LIKE core.occurrence_ownership INCLUDING DEFAULTS)")
    c.execute("INSERT INTO core.hold_myb2024_facility_capacity SELECT * FROM core.facility_capacity WHERE source_system = 'USGS_MYB2024'"); a = c.rowcount
    c.execute("DELETE FROM core.facility_capacity WHERE source_system = 'USGS_MYB2024'"); b = c.rowcount
    c.execute("INSERT INTO core.hold_myb2024_occurrence_ownership SELECT * FROM core.occurrence_ownership WHERE source_system = 'USGS_MYB2024'"); d = c.rowcount
    c.execute("DELETE FROM core.occurrence_ownership WHERE source_system = 'USGS_MYB2024'"); e = c.rowcount
    assert a == b and d == e, (a, b, d, e)
    c.execute("UPDATE core.occurrence_commodities SET is_active = false WHERE created_by IN (%s, %s) AND is_active", (TAG, TAG + "_dedupe")); f = c.rowcount
    c.execute("UPDATE core.occurrences SET is_active = false WHERE created_by = %s AND is_active", (TAG,)); h = c.rowcount
    # older rows must not stay superseded by 2024 rows nobody can see
    c.execute("SELECT to_regclass('core.facility_superseded')")
    if c.fetchone()[0]:
        c.execute("TRUNCATE core.facility_superseded")
    print(f"held capacity rows {a}, owner rows {d}; commodities deactivated {f}; 2024-only sites deactivated {h}; supersede list cleared")
elif MODE == "restore":
    # identity columns are GENERATED ALWAYS: keep the original ids
    c.execute("INSERT INTO core.facility_capacity OVERRIDING SYSTEM VALUE SELECT * FROM core.hold_myb2024_facility_capacity"); a = c.rowcount
    c.execute("INSERT INTO core.occurrence_ownership OVERRIDING SYSTEM VALUE SELECT * FROM core.hold_myb2024_occurrence_ownership"); d = c.rowcount
    c.execute("TRUNCATE core.hold_myb2024_facility_capacity, core.hold_myb2024_occurrence_ownership")
    c.execute("UPDATE core.occurrence_commodities SET is_active = true WHERE created_by IN (%s, %s) AND NOT is_active", (TAG, TAG + "_dedupe")); f = c.rowcount
    # 2024-only sites that were NOT merged into another site (merged ones stay inactive)
    c.execute("UPDATE core.occurrences SET is_active = true WHERE created_by = %s AND NOT is_active AND comments NOT LIKE %s", (TAG, "%MERGED 2026-11-11 into occurrence%")); h = c.rowcount
    print(f"restored capacity rows {a}, owner rows {d}; commodities {f}; sites {h}")
else:
    sys.exit("hide|restore")
g.commit()
if MODE == "restore":
    import subprocess
    for s in ("build_facility_clusters.py", "build_facility_supersede.py"):
        subprocess.run([sys.executable, os.path.join(HERE, s)], check=True)
