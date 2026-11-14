"""Load the Mauritanian National Mineral Deposits Database (USGS OFR 2013-1280 chapter S, Mineral_Deposits_Database.accdb table Indice_combin,
853 records; public domain, USGS acknowledgement) into core.occurrences, source PRISM_MRT_DEPOSITS.
Left out: construction / ornamental stone, peat, organic matter, oil, bituminous shale, salt, gypsum and gems (as in the MIN4EU load).
Status from Taille (2012 size/status field): 'Mine en activite' -> PRODUCER (status as of 2012), 'Mine abandonnee' -> PAST_PRODUCER,
'Projet minier' -> EXPLORATION, small artisanal deposits / 'Gisement' / 'Deposit' -> UNKNOWN (is_deposit), 'Indice' or blank -> OCCURRENCE.
Positions flagged by PRISM ('non positionne - erreur XY', 'XY imprecis') -> position_accuracy UNRELIABLE.
Matching: same rule as load_ngu_minres.py (similar name within 2 km or any site within 150 m; one PRISM record per existing site).
Usage: python load_prism_mauritania_deposits.py [--dry]
"""
import collections, csv, difflib, os, re, sys, unicodedata
import psycopg2, pyodbc
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_prism_mrt_deposits_20261114"
SRC = "PRISM_MRT_DEPOSITS"
F = "D:/CriticalMineralsDB/Africa/Mauritania_PRISM2_20261114/Mineral_Deposits_Database.accdb"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for line in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v.strip().strip('"')
SKIP = {"marble", "marbre", "peat", "organic matter", "oil", "bituminous shales", "salt", "gypsum", "gem", "material ornamentation", "granite"}
CMAP = {"Cu": ["Cu"], "U": ["U"], "Fe": ["Fe"], "Au": ["Au"], "Cr": ["Cr"], "Mn": ["Mn"], "P": ["Phosphate Rock"], "Pb": ["Pb"], "Ba": ["Baryte"],
        "Zn": ["Zn"], "Be": ["Be"], "W": ["W"], "Ti": ["Ti"], "Rare Earth": ["REE"], "Rare Earths": ["REE"], "Mo": ["Mo"], "F": ["Fluorite"],
        "Ni": ["Ni"], "kaolin": ["Kaolin"], "As": ["As"], "Sn": ["Sn"], "Th": ["Th"], "Asbestos": ["Asbestos"], "Sr": ["Sr"], "Sulfur": ["S"],
        "Wo": ["Wollastonite"], "?": []}
STATUS = {"Mine en activité": ("PRODUCER", True), "Mine abandonnée": ("PAST_PRODUCER", True), "Projet minier": ("EXPLORATION", True),
          "Petit gisement - Exploitation artisanale": ("UNKNOWN", True), "Gisement": ("UNKNOWN", True), "Deposit": ("UNKNOWN", True)}
STOP = r"\b(mine|deposit|gisement|indice|prospect)\b"


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()); s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", s))


c0 = pyodbc.connect(r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + F + ";ReadOnly=1").cursor()
c0.execute("SELECT * FROM Indice_combin"); cols = [d[0] for d in c0.description]
rows = [dict(zip(cols, r)) for r in c0.fetchall()]
recs, skipped = [], collections.Counter()
for r in rows:
    sub = (r["Substance_Principale_PRISM_II"] or "?").strip()
    if sub.lower() in SKIP: skipped[sub] += 1; continue
    assert sub in CMAP, sub
    lon, lat = r["X_WGS84_PRISMII"], r["Y_WGS84_PRISMII"]
    assert 14 < lat < 28 and -18 < lon < -4, (r["IndiceClassement"], lat, lon)
    nm = (r["Nom"] or "").strip() or f"Unnamed {sub if sub != '?' else 'mineral'} occurrence ({r['IndiceClassement']})"
    st, dep = STATUS.get((r["Taille"] or "").strip(), ("OCCURRENCE", False))
    pos = (r["Statut_2003_PRISM"] or "")
    recs.append(dict(r=r, sid=r["IndiceClassement"], name=nm, sub=sub, lon=lon, lat=lat, status=st, dep=dep,
                     unreliable="erreur XY" in pos or "imprécis" in pos))
print("records", len(recs), "skipped", dict(skipped))

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND name = 'Mauritania'"); MRT = c.fetchone()[0]
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,)); DONE = {x[0] for x in c.fetchall()}


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


def txt(x, n=300):
    return re.sub(r"\s+", " ", str(x)).strip()[:n] if x not in (None, "") else ""


def facts(p):
    r = p["r"]
    parts = [f"Mauritanian National Mineral Deposits Database (PRISM-II) no. {r['IndiceClassement']}", f"main substance: {p['sub']}"]
    for k, lab in [("Taille", "size/status (2012)"), ("Typologie", "type"), ("Classification_des_Gisements", "deposit model"),
                   ("ContexteLitho", "host rock"), ("ContexteStrati", "age"), ("Paragenèse_Terrain", "paragenesis"),
                   ("OrganismeDecouv", "found by"), ("DateDecouverte", "discovered"), ("DegreMiseEnValeur", "work done"),
                   ("Commentaire", "notes"), ("Commentaire_PRISM_II", "PRISM-II note"), ("Statut_2003_PRISM", "2003 field check")]:
        v = r.get(k)
        if v not in (None, ""): parts.append(f"{lab}: {txt(int(v) if isinstance(v, float) and v.is_integer() else v)}")
    return " | ".join(parts) + " | Source: USGS OFR 2013-1280 (PRISM-II) with the Ministry of Petroleum, Energy and Mines of Mauritania."


todo = [p for p in recs if p["sid"] not in DONE]
cand = {}
for p in todo:
    oid, nn, dist = match(p["name"], p["lon"], p["lat"]); p["near"], p["dist"] = nn, dist
    if oid: cand.setdefault(oid, []).append(p)
for oid, ps in cand.items():
    ps.sort(key=lambda p: (norm(p["name"]) != norm(p["near"]), p["dist"])); ps[0]["oid"] = oid
stats, logrows, ext = collections.Counter(), [], []
for p in todo:
    cids = [GN[n.lower()] for n in CMAP[p["sub"]]]
    oid = p.get("oid")
    if oid:
        act = "ATTACH"
        if not DRY:
            c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,)); have = {x[0] for x in c.fetchall()}
            for cid in cids:
                if cid not in have:
                    c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'SECONDARY',true,%s)", (oid, cid, TAG))
            c.execute("UPDATE core.occurrences SET comments = coalesce(comments || ' | ', '') || %s, modified_by = %s, modified_date = now() WHERE occurrence_id = %s",
                      (facts(p), TAG, oid))
    else:
        act = "NEW"
        if not DRY:
            c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, position_accuracy, comments, is_active,
                         created_by, created_date) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,%s,true,%s,now()) RETURNING occurrence_id""",
                      (p["name"][:300], p["dep"], MRT, float(p["lon"]), float(p["lat"]), p["status"], "UNRELIABLE" if p["unreliable"] else None, facts(p), TAG))
            oid = c.fetchone()[0]
            for i, cid in enumerate(cids):
                c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s)",
                          (oid, cid, "PRIMARY" if i == 0 else "SECONDARY", TAG))
    stats[act] += 1; stats[f"{act} {p['status']}"] += 1
    ext.append(("OCCURRENCE", oid, SRC, p["sid"], "MEDIUM" if act == "ATTACH" else "EXACT", TAG))
    logrows.append([act, p["sid"], p["name"], p["sub"], p["status"], oid, p["near"], p["dist"]])
with open(os.path.join(HERE, f"prism_mrt_deposits_log_20261114{'_DRY' if DRY else ''}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["action", "source_id", "name", "substance", "status", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)
print(dict(stats))
if DRY:
    g.rollback(); print("DRY RUN - nothing written"); sys.exit()
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s ON CONFLICT DO NOTHING", ext)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'U.S. Geological Survey with the Ministry of Petroleum, Energy and Mines of Mauritania (PRISM-II)',
             'Database of mineral deposits in the Islamic Republic of Mauritania (USGS OFR 2013-1280, chapter S)',
             'US public domain for the most part (USGS release; acknowledgement of the USGS appreciated)','https://doi.org/10.3133/ofr20131280',true,
             'Source: U.S. Geological Survey Open-File Report 2013-1280 (PRISM-II), with the Ministry of Petroleum, Energy and Mines of Mauritania.',true,
             'Cleared: USGS release, metadata Mineral_Deposits_Index_IRM.xml; checked 2026-11-14.',
             'Status as of 2012 (PRODUCER only where PRISM-II recorded an active mine); construction stone, peat, oil, salt, gypsum and gems left out; 197 records have no main substance; PRISM flagged some positions as wrong or imprecise (position_accuracy UNRELIABLE).',
             'D:\\CriticalMineralsDB\\Documents\\Licence_Evidence\\USGS_PRISM_MAURITANIA\\','2026-11-14',true,%s,now()) ON CONFLICT DO NOTHING""", (SRC, TAG))
g.commit()
c.execute("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); print(c.fetchall())
