"""Merge 2024 Minerals Yearbook sites that duplicate an existing USGS facility site (regional release or US facilities).
The 2024 table renamed many facilities ('Plant in Hechi' -> 'Site in Hechi', 'Linzhou Smelter' -> 'Site in Linzhou'), so load_myb2024.py created
a new town-placed site for them. Here a NEW 2024 site is merged into an existing site when: another USGS facility source has a capacity row of
the SAME commodity at that site, it lies within 50 km, and the place-name cores of the two names match (generic words stripped; equal, or
one contains the other, at least 4 letters). The nearest qualifying site wins. Merge = move capacity rows, owners and the external id to the
existing site, add missing commodities as SECONDARY, deactivate the duplicate (comment says where it went).
Usage: python dedupe_myb2024_sites.py [--dry]
"""
import os, re, sys, unicodedata, collections
import psycopg2

DRY = "--dry" in sys.argv
TAG = "migration_usgs_myb2024_20261111"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')
GENERIC = r"\b(site|sites|plant|plants|mine|mines|smelter|smelters|refinery|refineries|works|quarry|quarries|complex|facility|facilities|factory|" \
          r"in|at|near|of|the|county|city|district|province|prefecture|autonomous|banner|miao|division|and|area|industrial|zone|park|" \
          r"sx|ew|sxew|plants?|mill|concentrator|open|pit|underground|no|new|old|operation|operations|project|deposit|field|company|co|ltd|" \
          r"cement|gypsum|grinding|integrated|polymetallic|processing|petrochemical|brines?|copper|gold|iron|steel|nickel|zinc|lead|salt|lime|clinker)\b"


def core(n):
    n = unicodedata.normalize("NFKD", n or "").lower(); n = "".join(ch for ch in n if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", re.sub(GENERIC, " ", re.sub(r"[-/]", " ", n)))   # digits kept: Meghnaghat 1 is not Meghnaghat 2


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("""
WITH n AS (SELECT occurrence_id, name, geog FROM core.occurrences WHERE created_by = %s AND is_active),
nc AS (SELECT DISTINCT occurrence_id, lower(commodity_name) cm FROM core.facility_capacity WHERE source_system = 'USGS_MYB2024')
SELECT n.occurrence_id, n.name, r.occurrence_id, r.name, ST_Distance(n.geog, r.geog) d
FROM n JOIN core.occurrences r ON r.is_active AND r.occurrence_id <> n.occurrence_id AND r.created_by <> %s AND ST_DWithin(n.geog, r.geog, 50000)
WHERE EXISTS (SELECT 1 FROM core.facility_capacity f WHERE f.occurrence_id = r.occurrence_id AND f.source_system LIKE 'USGS_%%'
              AND f.source_system <> 'USGS_MYB2024' AND lower(f.commodity_name) IN (SELECT cm FROM nc WHERE nc.occurrence_id = n.occurrence_id))
ORDER BY n.occurrence_id, d""", (TAG, TAG))
best = {}
for nid, nname, rid, rname, d in c.fetchall():
    if nid in best: continue
    a, b = core(nname), core(rname)
    if len(a) >= 4 and len(b) >= 4 and (a == b or a in b or b in a):
        best[nid] = (nname, rid, rname, round(d / 1000, 1))
print("2024 sites to merge:", len(best))
for nid, (nn, rid, rn, km) in list(best.items())[:25]:
    print(f"  {nn[:40]:40} -> {rn[:40]:40} {km} km")
if DRY:
    sys.exit("DRY RUN - nothing written")
n = collections.Counter()
for nid, (nn, rid, rn, km) in best.items():
    c.execute("UPDATE core.facility_capacity SET occurrence_id = %s WHERE occurrence_id = %s AND source_system = 'USGS_MYB2024'", (rid, nid)); n["capacity rows moved"] += c.rowcount
    c.execute("""UPDATE core.occurrence_ownership o SET occurrence_id = %s WHERE o.occurrence_id = %s AND o.source_system = 'USGS_MYB2024'
                 AND NOT EXISTS (SELECT 1 FROM core.occurrence_ownership x WHERE x.occurrence_id = %s AND x.source_system = o.source_system
                                 AND x.ownership_role = o.ownership_role AND x.owner_name = o.owner_name)""", (rid, nid, rid)); n["owner rows moved"] += c.rowcount
    c.execute("DELETE FROM core.occurrence_ownership WHERE occurrence_id = %s AND source_system = 'USGS_MYB2024'", (nid,))   # same owner already on the target
    c.execute("UPDATE core.external_ids SET entity_id = %s, match_confidence = 'MEDIUM' WHERE entity_type = 'OCCURRENCE' AND entity_id = %s AND source_system = 'USGS_MYB2024'", (rid, nid))
    c.execute("""INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by)
                 SELECT %s, oc.commodity_id, 'SECONDARY', true, %s FROM core.occurrence_commodities oc WHERE oc.occurrence_id = %s AND oc.is_active
                 AND NOT EXISTS (SELECT 1 FROM core.occurrence_commodities x WHERE x.occurrence_id = %s AND x.commodity_id = oc.commodity_id AND x.is_active)""",
              (rid, TAG + "_dedupe", nid, rid))
    c.execute("UPDATE core.occurrences SET is_active = false, modified_by = %s, modified_date = now(), comments = comments || %s WHERE occurrence_id = %s",
              (TAG + "_dedupe", f" | MERGED 2026-11-11 into occurrence {rid} ({rn}, {km} km away): same USGS facility under a 2024 name", nid))
    n["sites merged"] += 1
g.commit(); print(dict(n))
