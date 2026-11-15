"""Czech Geological Survey register of reserved deposits and approved prognostic resources ("Výhradní ložiska a schválené prognózní zdroje
nerostných surovin v České republice", od.geology.cz/loziska_zdroje_ner_sur.zip; CC BY 4.0 per data.gov.cz and CGS) -> core.occurrences,
source CGS_DEPOSITS. The CGS open-data host od.geology.cz was unreachable on 2026-11-14 (also from the user's browser), so the file is the
Internet Archive copy of 30 April 2025 (web.archive.org/web/20250430103947/https://od.geology.cz/loziska_zdroje_ner_sur.zip) - the register
is updated weekly, so this is an April 2025 snapshot.
What is loaded: deposits whose raw material (surovina) is a metallic ore or an industrial mineral; construction stone, sand and gravel, brick
and ceramic clays, limestone, dolomite, gypsum, fuels, gem/decorative stone and technical soils are left out (as in the MIN4EU load).
Polygons with the same deposit key (klic) form one occurrence at ST_PointOnSurface of their union. subregistr B (reserved deposit) ->
is_deposit; P/R (approved prognostic resource) -> status PROSPECT. tezba (mining): current -> PRODUCER (as of April 2025), former -> PAST_PRODUCER,
not yet mined / occasional / not stated -> UNKNOWN. Czech raw-material text, mining type, operator and CGS registry IRI go into comments.
Matching: as load_ngu_minres.py (similar name within 2 km or any site within 150 m; one CGS deposit per existing site).
Usage: python load_cgs_deposits.py [--dry]
"""
import collections, csv, difflib, json, os, re, sys, unicodedata
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_cgs_deposits_20261114"
SRC = "CGS_DEPOSITS"
F = "D:/CriticalMineralsDB/Europe/Czechia_CGS_20261114/extracted/loziska_zdroje_ner_sur.geojson"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for line in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v.strip().strip('"')
# substring of a raw-material component (lower case) -> commodities
CMAP = [("lithi", ["Li"]), ("cín-wolfram", ["Sn", "W"]), ("cín - kov", ["Sn"]), ("wolfram", ["W"]), ("molybden", ["Mo"]), ("niob", ["Nb"]),
        ("rubidium", ["Rb"]), ("césium", ["Cs"]), ("zirkon", ["Zr"]), ("germanium", ["Ge"]), ("prvky vzácných zemin", ["REE"]),
        ("radioaktivní", ["U"]), ("uran", ["U"]), ("zlat", ["Au"]), ("stříbro", ["Ag"]), ("zinek", ["Zn"]), ("olovo", ["Pb"]), ("měď", ["Cu"]),
        ("měděná", ["Cu"]), ("arsén", ["As"]), ("indium", ["In"]), ("železné rudy", ["Fe"]), ("manganová", ["Mn"]), ("pyrit", ["Pyrite"]),
        ("grafit", ["Graphite"]), ("fluorit-barytová surovina/fluorit", ["Fluorite"]), ("fluorit-barytová surovina/baryt", ["Baryte"]),
        ("fluorit-barytová surovina", ["Fluorite", "Baryte"]), ("kaolin", ["Kaolin"]), ("bentonit", ["Bentonite"]), ("živc", ["Feldspar"]),
        ("křemenn", ["Quartz"]), ("písky sklářské", ["Silica Sand"]), ("wollastonit", ["Wollastonite"]), ("slída", ["Mica"]),
        ("diatomit", ["Diatomite"]), ("těžké minerály", ["Heavy Mineral Sand"]), ("bóru", ["B"]), ("staurolit", ["Staurolite"]),
        ("minerální barviva", ["Iron Oxide Pigments"])]
STOP = r"\b(dul|lom|lozisko|zlato|rudy|ruda)\b"


def comms(surovina):
    out = []
    for part in re.split(r",\s*", surovina or ""):
        p = part.strip().lower()
        if not p or p.startswith("polymetalické rudy") and p == "polymetalické rudy" or p == "stopové a vzácné prvky": continue
        for key, names in CMAP:
            if key in p:
                for n in names:
                    if n not in out: out.append(n)
                break
    return out


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()); s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", s))


def status(sub, tezba):
    if not sub.startswith("B"): return "PROSPECT"
    t = (tezba or "").lower()
    if t.startswith("současná"): return "PRODUCER"
    if t.startswith("dřívější"): return "PAST_PRODUCER"
    return "UNKNOWN"


feats = json.load(open(F, encoding="utf-8"))["features"]
groups = collections.OrderedDict()
for f in feats:
    p = f["properties"]
    groups.setdefault(p["klic"], []).append(f)
recs, skipped = [], collections.Counter()
for klic, fs in groups.items():
    p0 = fs[0]["properties"]
    surs = sorted({f["properties"]["surovina"] for f in fs if f["properties"]["surovina"]})
    cm = []
    for s in surs:
        for x in comms(s):
            if x not in cm: cm.append(x)
    if not cm: skipped["construction / fuel / other only"] += 1; continue
    recs.append(dict(klic=klic, name=p0["nazev"], sub=p0["subregistr"], tezba=p0["tezba"], org=p0.get("organizace"), iri=p0.get("iri"),
                     sur="; ".join(surs), char="; ".join(sorted({f["properties"]["charakteristika_suroviny"] for f in fs if f["properties"].get("charakteristika_suroviny")}))[:300],
                     comms=cm, geoms=[json.dumps(f["geometry"]) for f in fs]))
print("deposits", len(groups), "kept", len(recs), dict(skipped))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = 'Czechia'"); CZ = c.fetchone()[0]
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,)); DONE = {x[0] for x in c.fetchall()}
for r in recs:
    c.execute("SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_PointOnSurface(ST_Union(ST_SetSRID(ST_GeomFromGeoJSON(x), 4326))) p FROM unnest(%s::text[]) x) q", (r["geoms"],))
    r["lon"], r["lat"] = c.fetchone()
    assert 48 < r["lat"] < 51.2 and 12 < r["lon"] < 19, r["klic"]


def match(name, lon, lat):
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND created_by <> %s AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 2000) ORDER BY d LIMIT 8""",
              (lon, lat, TAG, lon, lat))
    near = c.fetchall(); nm = norm(name)
    for oid, n2, d in near:
        if d < 150: return oid, n2, round(d)
        n2n = norm(n2)
        if nm and n2n and (difflib.SequenceMatcher(None, nm, n2n).ratio() > 0.8 or (len(nm) > 4 and len(n2n) > 4 and (nm in n2n or n2n in nm))):
            return oid, n2, round(d)
    return None, (near[0][1] if near else None), (round(near[0][2]) if near else None)


def facts(r):
    parts = [f"Czech Geological Survey register of reserved deposits and approved prognostic resources (April 2025 snapshot): {r['sub']}",
             f"raw material: {r['sur']}"]
    if r["char"]: parts.append(f"characteristics: {r['char']}")
    if r["tezba"]: parts.append(f"mining: {r['tezba']}")
    if r["org"]: parts.append(f"organisation: {r['org']}")
    parts.append(f"CGS key {r['klic']} {r['iri'] or ''}".strip())
    return " | ".join(parts) + " | Source: (cc) Czech Geological Survey, CC BY 4.0."


todo = [r for r in recs if r["klic"] not in DONE]
cand = {}
for r in todo:
    oid, nn, dist = match(r["name"], r["lon"], r["lat"]); r["near"], r["dist"] = nn, dist
    if oid: cand.setdefault(oid, []).append(r)
for oid, rs in cand.items():
    rs.sort(key=lambda r: (norm(r["name"]) != norm(r["near"]), r["dist"])); rs[0]["oid"] = oid
stats, logrows, ext = collections.Counter(), [], []
for r in todo:
    cids = [GN[n.lower()] for n in r["comms"]]
    oid = r.get("oid")
    if oid:
        act = "ATTACH"
        if not DRY:
            c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,)); have = {x[0] for x in c.fetchall()}
            for cid in cids:
                if cid not in have:
                    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'SECONDARY',true,%s)", (oid, cid, TAG))
            c.execute("UPDATE core.occurrences SET comments = coalesce(comments || ' | ', '') || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
                      (facts(r), TAG, oid))
    else:
        act = "NEW"
        if not DRY:
            c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, comments, is_active, created_by, created_date)
                         VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,true,%s,now()) RETURNING occurrence_id""",
                      (r["name"][:300], r["sub"].startswith("B"), CZ, float(r["lon"]), float(r["lat"]), status(r["sub"], r["tezba"]), facts(r), TAG))
            oid = c.fetchone()[0]
            for i, cid in enumerate(cids):
                c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                          (oid, cid, "PRIMARY" if i == 0 else "SECONDARY", TAG))
    stats[act] += 1; stats[f"{act} {status(r['sub'], r['tezba'])}"] += 1
    ext.append(("OCCURRENCE", oid, SRC, r["klic"], "MEDIUM" if act == "ATTACH" else "EXACT", TAG))
    logrows.append([act, r["klic"], r["name"], ",".join(r["comms"]), status(r["sub"], r["tezba"]), oid, r["near"], r["dist"]])
with open(os.path.join(HERE, f"cgs_deposits_log_20261114{'_DRY' if DRY else ''}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["action", "klic", "name", "commodities", "status", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)
print(dict(stats))
print("commodities", collections.Counter(x for r in recs for x in r["comms"]).most_common(30))
if DRY:
    g.rollback(); print("DRY RUN - nothing written"); sys.exit()
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s ON CONFLICT DO NOTHING", ext)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'Czech Geological Survey (CGS / ČGS)','Registered reserved deposits and approved prognostic resources of minerals in the Czech Republic (od.geology.cz/loziska_zdroje_ner_sur.zip)',
             'CC BY 4.0','https://creativecommons.org/licenses/by/4.0/',true,'(cc) Czech Geological Survey, register of reserved deposits and approved prognostic resources, CC BY 4.0 (April 2025 version via the Internet Archive).',true,
             'Cleared: data.gov.cz distribution licence CC BY 4.0 and the CGS open-data notice - checked 2026-11-14. od.geology.cz unreachable 2026-11-14; file = Internet Archive copy of 30 Apr 2025.',
             'April 2025 snapshot of a weekly-updated register; metals and industrial minerals only; Czech-language attributes; status from the register mining field (current / former).',
             'D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\CGS_Czechia\\','2026-11-14',true,%s,now()) ON CONFLICT DO NOTHING""", (SRC, TAG))
g.commit()
c.execute("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); print(c.fetchall())
