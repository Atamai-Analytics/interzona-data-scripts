"""core.facility_capacity_published: label the CRM_ATLAS_FORLINI rows correctly (2026-11-23, with the Atlas load).
  - stage_group 'Recycling plant' for facility_stage 'Recycling' (was 'Other processing plant');
  - release 'Critical Raw Materials Atlas (V. Forlini; status checked 2026)' instead of '<source> (Minerals Yearbook 2026 data)';
  - measure 'no capacity in source' instead of 'measure not stated by USGS' for that source.
Rows of every other source are unchanged (checked: same stage_group / release / measure counts before and after).
The old definition is saved to facility_capacity_published_viewdef_before_20261123.sql. Rollback: run that file.
Usage: python fix_facility_view_atlas.py [--dry]
"""
import os, sys, psycopg2

DRY = "--dry" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SELECT pg_get_viewdef('core.facility_capacity_published'::regclass, true)")
old = c.fetchone()[0]
open(os.path.join(HERE, "facility_capacity_published_viewdef_before_20261123.sql"), "w", encoding="utf-8").write(
    "CREATE OR REPLACE VIEW core.facility_capacity_published AS\n" + old)
reps = [
    ("""                    WHEN fc.facility_stage::text ~~* '%Smelter%'::text THEN 'Smelter'::character varying
                    ELSE 'Other processing plant'::character varying""",
     """                    WHEN fc.facility_stage::text ~~* '%Smelter%'::text THEN 'Smelter'::character varying
                    WHEN fc.facility_stage::text = 'Recycling'::text THEN 'Recycling plant'::character varying
                    ELSE 'Other processing plant'::character varying"""),
    ("""                    WHEN fc.product_form IS NULL THEN 'measure not stated by USGS'::text""",
     """                    WHEN fc.source_system::text = 'CRM_ATLAS_FORLINI'::text THEN 'no capacity in source'::text
                    WHEN fc.product_form IS NULL THEN 'measure not stated by USGS'::text"""),
    ("""                    WHEN 'USGS_MYB2024'::text THEN 'USGS 2024 Minerals Yearbook global facilities table'::character varying""",
     """                    WHEN 'USGS_MYB2024'::text THEN 'USGS 2024 Minerals Yearbook global facilities table'::character varying
                    WHEN 'CRM_ATLAS_FORLINI'::text THEN 'Critical Raw Materials Atlas (V. Forlini; status checked 2026)'::character varying"""),
    ("""                    WHEN fc.source_system::text = 'USGS_US_FACILITIES'::text THEN ''::text""",
     """                    WHEN fc.source_system::text = ANY (ARRAY['USGS_US_FACILITIES'::text, 'CRM_ATLAS_FORLINI'::text]) THEN ''::text"""),
]
new = old
for a, b in reps:
    assert new.count(a) == 1, ("pattern not found once", a[:80])
    new = new.replace(a, b)
q = """SELECT source_system = 'CRM_ATLAS_FORLINI' atlas, stage_group, release, measure, count(*) FROM core.facility_capacity_published GROUP BY 1,2,3,4 ORDER BY 1,2,3,4"""
c.execute(q); before = c.fetchall()
c.execute("CREATE OR REPLACE VIEW core.facility_capacity_published AS\n" + new)
c.execute(q); after = c.fetchall()
assert [r for r in before if not r[0]] == [r for r in after if not r[0]], "non-Atlas rows changed"
print("Atlas rows after:", [r[1:] for r in after if r[0]])
if DRY:
    g.rollback(); print("DRY - rolled back")
else:
    g.commit(); print("COMMITTED")
