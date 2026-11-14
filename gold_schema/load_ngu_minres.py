"""Load NGU's mineral resources register (Mineralressurser: industrimineral, naturstein og metaller; Geonorge uuid
5a887d78-07ef-44c6-8941-cb8017c6328c, data extract 2026-03-30, NLOD) into core.occurrences.
Input: D:/CriticalMineralsDB/Norway/ngu_mineralressurser_20261114/extracted/Mineralressurser.gdb (ordered 2026-11-14 from the Geonorge download
API, national extent, EPSG:4258 - ETRS89 lat/lon, treated as WGS84).
What is loaded: the POINT layers for metals (Malm*) and industrial minerals (Industrimineral*): Forekomst (deposit, is_deposit), Prospekt (prospect),
Registrering (registered occurrence). Natural stone (Naturstein*) and the polygon / province layers are left out (as in the MIN4EU load).
Status: Prospekt -> PROSPECT; records whose recorded activity is mining (Gruvedrift) or quarrying (Steinbrudd) -> UNKNOWN (the register does not say
whether the operation is current); other registrations -> OCCURRENCE; other deposits -> UNKNOWN. NGU's activity, importance (rastoffBetydning),
'historically important', position-verified flag, fact-sheet URL and dates go into comments.
Matching (same rule as load_min4eu.py): an existing active occurrence (not from this load) with a similar name within 2 km, or any within 150 m ->
ATTACH (external id, missing commodities as SECONDARY, NGU facts appended to comments); otherwise NEW.
Usage: python load_ngu_minres.py [--dry]   (the dry run writes ngu_minres_load_log_20261114_DRY.csv and changes nothing)
"""
import collections, csv, difflib, os, re, sys, unicodedata
import psycopg2, pyogrio
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_ngu_minres_20261114"
SRC = "NGU_MINRES"
G = "D:/CriticalMineralsDB/Norway/ngu_mineralressurser_20261114/extracted/Mineralressurser.gdb"
LAYERS = ["MalmForekomst", "MalmProspekt", "MalmRegistrering", "IndustrimineralForekomst", "IndustrimineralProspekt", "IndustrimineralRegistrering"]
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for line in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v.strip().strip('"')

# NGU resource subtype -> core.commodities names (None = kept in comments only)
CMAP = {
    "Kobber": ["Cu"], "Jern": ["Fe"], "Sulfider": ["Pyrite"], "Jern-titan": ["Fe", "Ti"], "Sink": ["Zn"], "Molybden": ["Mo"], "Nikkel": ["Ni"],
    "Bly": ["Pb"], "S\u00f8lv": ["Ag"], "Krom": ["Cr"], "Gull": ["Au"], "Mangan": ["Mn"], "Titan": ["Ti"], "Uran": ["U"], "Arsen": ["As"],
    "Kobolt": ["Co"], "REE-metaller": ["REE"], "Thorium": ["Th"], "Beryllium": ["Be"], "Vismut": ["Bi"], "Wolfram": ["W"], "PGE-elementer": ["PGE"],
    "Niob": ["Nb"], "Antimon": ["Sb"], "Tinn": ["Sn"], "Scandium": ["Sc"],
    "Pegmatittisk feltspat": ["Feldspar"], "Feltspat (uspes.)": ["Feldspar"], "K-feltspat": ["Feldspar"], "Kalk": ["Limestone"],
    "Kvartsitt": ["Quartz"], "Pegmatittisk kvarts": ["Quartz"], "Hydrotermal kvarts": ["Quartz"], "Kvarts (uspes.)": ["Quartz"],
    "Kvartssand": ["Silica Sand"], "Pegmatittisk muskovitt": ["Mica"], "Muskovitt (uspes.)": ["Mica"], "Muskovittskifer": ["Mica"],
    "Flogopitt": ["Mica"], "Grafitt": ["Graphite"], "Graphite omformet": ["Graphite"], "Olivin": ["Olivine"], "Apatitt": ["Apatite"],
    "Talk (Kleberstein)": ["Talc"], "Talk": ["Talc"], "Flusspat": ["Fluorite"], "Kyanitt": ["Kyanite"], "Beryll": ["Beryl", "Be"],
    "Wollastonitt": ["Wollastonite"], "Magnesitt": ["MgCO3"], "Asbest": ["Asbestos"], "Serpentin": ["Serpentine"],
    "Nefelinsyenitt": ["Nepheline Syenite"], "Granat": ["Garnet"], "Kiselgur": ["Diatomite"], "Kaolin": ["Kaolin"], "Barytt": ["Baryte"],
    "Zirkon": ["Zircon"], "Litium": ["Li"], "Fenakitt": ["Phenakite", "Be"], "Brucitt": ["Mg"],
    "Dolomitt": None, "Ultramafitt (uspes.)": None, "Anortositt": None, "Karbonat (uspes.)": None,
}
ACT = {1: "prospecting", 2: "trenching / test pits (r\u00f8sking)", 4: "trial mining (pr\u00f8vedrift)", 5: "mining (gruvedrift)", 41: "quarrying (steinbrudd)"}
KIND = {"Forekomst": "deposit", "Prospekt": "prospect", "Registrering": "registered occurrence"}
STOP = r"\b(gruve|gruver|gruvene|gruva|forekomst|forekomsten|skjerp|brudd|bruddet|mine|mines|deposit|prospect)\b"


def norm(s):
    s = (s or "").lower().replace("\u00e6", "ae").replace("\u00f8", "o").replace("\u00e5", "a")
    s = unicodedata.normalize("NFKD", s.replace("ae", "a").replace("oe", "o"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", s))


recs = []
for lay in LAYERS:
    df = pyogrio.read_dataframe(G, layer=lay)
    grp = "metals" if lay.startswith("Malm") else "industrial minerals"
    kind = next(v for k, v in KIND.items() if lay.endswith(k))
    for _, r in df.iterrows():
        act = r.get("typeRastoffVirksomhet")
        act = None if act is None or act != act else int(float(act))
        recs.append(dict(layer=lay, grp=grp, kind=kind, sid=f"{r['objekttype']}:{r['lokalid']}", nr=r["forekomstNummer"],
                         name=(r["navnRastoffobj"] or "").strip() or f"Unnamed NGU {grp} {kind}", lon=r.geometry.x, lat=r.geometry.y,
                         rtype=r["ressursType_tekst"], sub=r["ressursUndertype"], act=act, imp=r.get("rastoffBetydning_tekst"),
                         hist=r.get("historiskViktig"), verified=r.get("stedfestingVerifisert"), url=r.get("faktaark_url"),
                         first=r.get("f\u00f8rsteDatafangstdato"), upd=r.get("oppdateringsdato"), n_an=r.get("antallAnalyser")))
print("records", len(recs), collections.Counter(r["layer"] for r in recs))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"],
                     keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = 'Norway'"); NOR = c.fetchone()[0]
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,)); DONE = {x[0] for x in c.fetchall()}
unmapped, stats, logrows, ext = collections.Counter(), collections.Counter(), [], []


def cids(sub):
    names = CMAP.get(sub, "missing")
    if names == "missing" or names is None:
        unmapped[sub] += 1; return []
    out = []
    for nm in names:
        cid = GN.get(nm.lower()); assert cid, nm
        out.append(cid)
    return out


def match(name, lon, lat):
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND created_by <> %s AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 2000) ORDER BY d LIMIT 8""",
              (lon, lat, TAG, lon, lat))
    near = c.fetchall(); nm = norm(name)
    for oid, n2, d in near:
        if d < 150:
            return oid, n2, round(d)
        n2n = norm(n2)
        if nm and n2n and (difflib.SequenceMatcher(None, nm, n2n).ratio() > 0.8 or (len(nm) > 4 and len(n2n) > 4 and (nm in n2n or n2n in nm))):
            return oid, n2, round(d)
    return None, (near[0][1] if near else None), (round(near[0][2]) if near else None)


def d(x):
    return x.strftime("%Y-%m-%d") if x is not None and x == x and hasattr(x, "strftime") else None


def facts(r):
    parts = [f"NGU mineral resources register: {r['grp']} {r['kind']} no. {r['nr']}", f"resource: {r['rtype']} / {r['sub']}"]
    if r["act"]: parts.append(f"activity recorded: {ACT.get(r['act'], r['act'])}")
    if r["imp"] and r["imp"] == r["imp"] and r["imp"] not in ("Ikke vurdert", "ikkeVurdert"): parts.append(f"importance (NGU): {r['imp']}")
    if r["hist"] == "Ja": parts.append("historically important")
    if r["verified"] == "Nei": parts.append("position not verified by NGU")
    if r["n_an"] and r["n_an"] == r["n_an"] and r["n_an"] > 0: parts.append(f"{int(r['n_an'])} analyses at NGU")
    dt = "; ".join(x for x in [f"registered {d(r['first'])}" if d(r["first"]) else "", f"updated {d(r['upd'])}" if d(r["upd"]) else ""] if x)
    if dt: parts.append(dt)
    if r["url"]: parts.append(f"fact sheet {r['url']}")
    return " | ".join(parts) + " | Source: NGU (Geological Survey of Norway), NLOD."


def status(r):
    if r["kind"] == "prospect": return "PROSPECT"
    if r["act"] in (5, 41): return "UNKNOWN"
    return "OCCURRENCE" if r["kind"] == "registered occurrence" else "UNKNOWN"


# pass 1: candidate match per record; each existing occurrence goes to ONE record only (same name first, then the nearest), so two distinct
# NGU registrations are never merged into one existing occurrence - the others load as NEW
todo = [r for r in recs if r["sid"] not in DONE]
stats["already loaded"] = len(recs) - len(todo)
cand = {}
for r in todo:
    oid, near_name, dist = match(r["name"], r["lon"], r["lat"])
    r["near"], r["dist"] = near_name, dist
    if oid: cand.setdefault(oid, []).append(r)
for oid, rs in cand.items():
    rs.sort(key=lambda r: (norm(r["name"]) != norm(r["near"]), r["dist"]))
    rs[0]["oid"] = oid
    stats["lost a contested match"] += len(rs) - 1

for r in todo:
    comm_ids = cids(r["sub"])
    oid, near_name, dist = r.get("oid"), r["near"], r["dist"]
    if oid:
        act = "ATTACH"
        if not DRY:
            c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,)); have = {x[0] for x in c.fetchall()}
            for cid in comm_ids:
                if cid not in have:
                    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'SECONDARY',true,%s)", (oid, cid, TAG))
            c.execute("UPDATE core.occurrences SET comments = coalesce(comments || ' | ', '') || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
                      (facts(r), TAG, oid))
    else:
        act = "NEW"
        if not DRY:
            c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, comments, is_active,
                         created_by, created_date) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,%s,true,%s,now()) RETURNING occurrence_id""",
                      (r["name"][:300], r["kind"] == "deposit", NOR, float(r["lon"]), float(r["lat"]), status(r),
                       "Quarry" if r["act"] == 41 else None, facts(r), TAG))
            oid = c.fetchone()[0]
            for i, cid in enumerate(comm_ids):
                c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                          (oid, cid, "PRIMARY" if i == 0 else "SECONDARY", TAG))
    stats[act] += 1; stats[f"{act} {r['layer']}"] += 1
    ext.append(("OCCURRENCE", oid, SRC, r["sid"], "MEDIUM" if act == "ATTACH" else "EXACT", TAG))
    logrows.append([r["layer"], act, r["sid"], r["nr"], r["name"], r["sub"], oid, near_name, dist])

with open(os.path.join(HERE, f"ngu_minres_load_log_20261114{'_DRY' if DRY else ''}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["layer", "action", "source_id", "ngu_number", "name", "subtype", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)
print(dict(stats))
print("subtypes without a commodity:", dict(unmapped))
if DRY:
    g.rollback(); print("DRY RUN - nothing written"); sys.exit()
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s ON CONFLICT DO NOTHING", ext, page_size=2000)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'Geological Survey of Norway (NGU)','Mineralressurser: industrimineral, naturstein og metaller (NGU mineral resources register; metals and industrial minerals, point layers)',
             'NLOD (Norwegian Licence for Open Government Data)','https://data.norge.no/nlod/en/2.0/',true,
             'Contains data under the Norwegian licence for Open Government data (NLOD) made available by the Geological Survey of Norway (NGU).',true,
             'Cleared: NGU data policy (NLOD, commercial use allowed) and the Geonorge metadata use constraint NLOD - checked 2026-11-14.',
             'Metals and industrial minerals only (natural stone left out). No operating status in the register: records with mining recorded have status UNKNOWN; NGU importance, activity and position-verified flag are in comments. Many registrations are small historical showings; about 40 percent of positions are not verified by NGU.',
             'D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\NGU_Norway\\','2026-11-14',true,%s,now()) ON CONFLICT DO NOTHING""", (SRC, TAG))
g.commit()
c.execute("SELECT count(*), count(*) FILTER (WHERE is_deposit), count(*) FILTER (WHERE array_length(commodities,1) > 0) FROM core.occurrences WHERE created_by = %s", (TAG,))
print("new occurrences / deposits / with commodities:", c.fetchone())
c.execute("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); print(c.fetchall())
