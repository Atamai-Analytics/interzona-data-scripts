"""EMODnet Geology Marine Minerals (seabed mineral occurrences, CC BY 4.0) -> interzona_cm core.occurrences (+ commodities, external ids).

Source: EMODnet Geology WFS (drive.emodnet-geology.eu/geoserver/gsi), seven point layers downloaded 2026-11-07 as GeoJSON to
D:/CriticalMineralsDB/Seabed/download_20261107/emodnet (evidence: Documents/Licence_Evidence/EMODnet_Geology_Marine_Minerals/EVIDENCE.md):
polymetallic nodules, polymetallic sulphides, cobalt-rich ferromanganese crusts, marine placers, phosphorites, metal-rich sediments and
rock/pegmatite/vein-hosted. Aggregates, evaporites, sapropel and gas hydrates are not loaded.
Rules
  * The 1,169 Finnish Baltic nodule points (data provider Metsahallitus, 'Velmu' underwater-video concretion sightings, 'not assessed')
    are left out unless --include-velmu: they are seabed-cover observations, not mapped deposits.
  * status: identified / proven / reserve / indicated / inferred / probable -> PROSPECT (is_deposit); 'Under investigation' / 'Exploration' ->
    PROSPECT (not deposit); depleted mine -> PAST_PRODUCER; everything else (hypothetical, known occurrence, anomaly, none) -> OCCURRENCE.
  * jurisdiction: the record's 'code' is the CONTRIBUTING country, so it is used for the country only when the provider is not the ISA;
    ISA-supplied points (international seabed) get no jurisdiction. Codes without a country row stay NULL.
  * resource text ('units'), economic feasibility, setting, minerals, water depth, provider and references go to comments; no resource rows.
  * the data_cont field (personal e-mail contacts) is never loaded.
  * points within 1 km of an existing USGS MRDS occurrence (32 Caribbean/Central American ASGMI records: beach placers, Mona Island cave
    phosphate) are left out as duplicates; any other near match stops the load for review.
Usage: python load_emodnet_marine_minerals.py [--dry] [--include-velmu]
"""
import json, os, re, sys, time, glob, collections
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from scipy.spatial import cKDTree

DRY = "--dry" in sys.argv
VELMU = "--include-velmu" in sys.argv
TAG = "migration_emodnet_marine_20261107"
SRC = "EMODNET_GEOLOGY_MARINE_MINERALS"
HERE = os.path.dirname(os.path.abspath(__file__))
DIR = "D:/CriticalMineralsDB/Seabed/download_20261107/emodnet"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def clean(v):
    if v is None: return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return None if s.lower() in ("", "none", "n/a", "-", "not available", "not applicable", "no estimate", "no info on type or size", "null") else s


def note(*pairs):
    return "; ".join(f"{k}: {v}" for k, v in pairs if v not in (None, ""))


LAYERS = {  # layer: (label, occurrence type, default primary commodities)
    "PolymetallicNodulesPoint": ("Polymetallic nodules", "Nodule manganese", ["Mn", "Fe"]),
    "CobaltRichFerromanganeseCrustsPoint": ("Cobalt-rich ferromanganese crust", "Crust manganese", ["Mn", "Fe"]),
    "PolymetallicSulphidesPoint": ("Seafloor polymetallic sulphide / hydrothermal", None, []),
    "MarinePlacerDepositsPoint": ("Marine placer", None, []),
    "PhosphoritesPoint": ("Marine phosphorite", "Phosphorite", ["Phosphate Rock"]),
    "MetalRichSedimentsPoint": ("Metal-rich sediment", None, []),
    "RockPegVeinPoint": ("Rock, pegmatite or vein hosted (offshore)", None, []),
}
WORDS = [(r"rare earth", "REE"), (r"\bgold\b|native gold", "Au"), (r"\bsilver\b", "Ag"), (r"\bcopper\b", "Cu"), (r"molybden", "Mo"), (r"uranium|pechblende|pitchblende", "U"),
         (r"thorium", "Th"), (r"cerium", "Ce"), (r"ilmenite|ilmenourite", "Ilmenite"), (r"rutile", "Rutile"), (r"\bzircon\b", "Zircon"), (r"monazite", "Monazite"),
         (r"titanifer|titanium", "Ti"), (r"manganese|vernadite|birnessite|todorokite|pyrolusite", "Mn"), (r"\biron\b|goethite|magnetite|feroxyhyte", "Fe"),
         (r"platinum", "Pt"), (r"\bPGE\b", "PGE"), (r"selenium", "Se"), (r"tellur", "Te"), (r"cassiterite|\btin\b", "Sn"), (r"chromite", "Cr"),
         (r"beryl\b", "Be"), (r"garnet|\bgrt\b", "Garnet"), (r"barite|baryte", "Ba"), (r"\bzinc\b|sphalerite", "Zn"), (r"\blead\b|galena", "Pb"), (r"chalcopyrite", "Cu"),
         (r"cobalt", "Co"), (r"nickel", "Ni"), (r"tantal|ixiolite", "Ta"), (r"niob", "Nb")]
SYMS = {"Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Pb", "Au", "Ag", "Pt", "PGE", "Mo", "Ti", "V", "Cr", "Sn", "U", "Th", "Ce", "Zr", "Li", "Se", "Te", "REE", "W", "Ba"}


def commodities(layer, p):
    found = list(LAYERS[layer][2])
    if layer == "PhosphoritesPoint": return found   # dep_sub_ty there is a generic legend class (salts, nitrates ...), not the site's commodities
    txt = " ; ".join(x for x in (clean(p.get("prim_min")), clean(p.get("all_other")), clean(p.get("dep_sub_ty")), clean(p.get("units"))) if x)
    for rx, c in WORDS:
        if re.search(rx, txt, re.I) and c not in found: found.append(c)
    for t in re.findall(r"\b([A-Z][a-z]?|PGE|REE)\b", txt):
        if t in SYMS and t not in found: found.append(t)
    return found


def status(p):
    s = " ".join(x for x in (clean(p.get("status")), clean(p.get("econ_feas"))) if x).lower()
    if "depleted" in s: return "PAST_PRODUCER", True
    if re.search(r"identified deposit|proven|reserve|indicated|inferred|probable|prospected", s): return "PROSPECT", True
    if re.search(r"under investigation|exploration|potential resource", s): return "PROSPECT", False
    return "OCCURRENCE", False


# ------------------------------------------------------------------ read
recs, skipped = [], collections.Counter()
for layer, (label, otype, _) in LAYERS.items():
    feats = json.load(open(os.path.join(DIR, layer + ".geojson"), encoding="utf-8"))["features"]
    for f in feats:
        p = f["properties"]
        prov = clean(p.get("data_provi")) or ""
        if layer == "PolymetallicNodulesPoint" and prov.startswith("Mets") and not VELMU: skipped["Finnish Baltic video sightings (Velmu)"] += 1; continue
        if not f.get("geometry"): skipped["no geometry"] += 1; continue
        lon, lat = f["geometry"]["coordinates"][:2]
        st, dep = status(p)
        area, area_no = clean(p.get("area_name")), clean(p.get("area_no"))
        name = area or f"{label} ({prov or 'EMODnet'} #{p.get('id')})"
        if area and area_no and area_no not in area: name = f"{area} ({area_no})"
        isa = "international seabed authority" in prov.lower()
        try: akm = float(p.get("area_km2") or 0)
        except ValueError: akm = 0
        recs.append(dict(sid=f"{layer}:{p.get('id')}", layer=layer, name=name[:250], lon=float(lon), lat=float(lat), status=st, is_deposit=dep, otype=otype,
                         code=None if isa else clean(p.get("code")), com=commodities(layer, p), acc="AREA_CENTROID" if akm > 0 else None,
                         style=note(("Type", clean(p.get("deposit_ty"))), ("Sub-type", clean(p.get("dep_sub_ty")))) or None,
                         form=clean(p.get("main_morph")) or clean(p.get("morph")),
                         comments=note(("Source", "EMODnet Geology, Marine Minerals (CC BY 4.0)"), ("Data provider", prov or None),
                                       ("EMODnet layer and id", f"{layer} {p.get('id')}"), ("Contributing country code", clean(p.get("code"))),
                                       ("International seabed (ISA-supplied point)", "yes" if isa else None), ("Setting", clean(p.get("setting"))),
                                       ("Primary minerals/elements", clean(p.get("prim_min"))), ("Other minerals/elements", clean(p.get("all_other"))),
                                       ("Status (source)", clean(p.get("status"))), ("Economic feasibility (source)", clean(p.get("econ_feas"))),
                                       ("Resource / grade as reported", clean(p.get("units"))), ("Operator", clean(p.get("operator"))),
                                       ("Exploitation", clean(p.get("exploit_ty"))), ("Area km2", clean(p.get("area_km2")) if akm > 0 else None),
                                       ("Water depth to deposit (m)", clean(p.get("depth_to_d"))), ("Map scale", clean(p.get("scale"))),
                                       ("References", clean(p.get("references"))), ("Comments (source)", clean(p.get("comments"))))))
log("records", len(recs), "| by layer", collections.Counter(r["layer"] for r in recs), "| skipped", dict(skipped))

# ------------------------------------------------------------------ gold
g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor()
c.execute("SET statement_timeout = 0")
c.execute("SELECT count(*) FROM core.external_ids WHERE source_system = %s", (SRC,))
assert c.fetchone()[0] == 0, "already loaded"
c.execute("SELECT iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code IS NOT NULL AND is_active")
JUR = {k.upper(): v for k, v in c.fetchall()}
nojur = collections.Counter(r["code"] for r in recs if r["code"] and r["code"].upper() not in JUR)
log("codes without a country row (jurisdiction NULL)", dict(nojur))
c.execute("SELECT commodity_name, commodity_id, commodity_symbol FROM core.commodities")
COM = {}
for nm, cid, sym in c.fetchall():
    COM[nm.lower()] = cid
    if sym: COM[sym.lower()] = cid
c.execute("SELECT type_name, occurrence_type_id FROM core.occurrence_types"); OTYPE = {k.lower(): v for k, v in c.fetchall()}
for t in {r["otype"] for r in recs if r["otype"]}: assert t.lower() in OTYPE, t

# possible duplicates of occurrences we already hold (report only; seabed points rarely overlap land inventories)
c.execute("SELECT occurrence_id, name, lat, lon, created_by FROM core.occurrences WHERE is_active AND lat IS NOT NULL")
ex = c.fetchall()
lat0 = np.radians(45)
xy = lambda la, lo: np.column_stack([np.radians(np.asarray(lo, float)) * np.cos(np.radians(np.asarray(la, float))) * 6371000, np.radians(np.asarray(la, float)) * 6371000])
tree = cKDTree(xy([e[2] for e in ex], [e[3] for e in ex]))
near = []
dd, jj = tree.query(xy([r["lat"] for r in recs], [r["lon"] for r in recs]), distance_upper_bound=1000)
for i, (d, j) in enumerate(zip(dd, jj)):
    if np.isfinite(d): near.append((recs[i]["name"], ex[j][1], ex[j][4], round(float(d))))
log("EMODnet points within 1 km of an existing occurrence", len(near), collections.Counter(n[2] for n in near))
for n in near: log("   near:", n)
# These are the same Caribbean / Central American sites (beach placers, Mona Island cave phosphate) that USGS MRDS already holds, contributed
# to EMODnet from the ASGMI metallogenic map: leave them out rather than load them twice.
dup = {i for i, (d, j) in enumerate(zip(dd, jj)) if np.isfinite(d) and ex[j][4] == "migration_mrds_20261014"}
assert len(dup) == len(near), "a near match is not MRDS - review before loading"
recs = [r for i, r in enumerate(recs) if i not in dup]
log("left out as MRDS duplicates", len(dup), "| loading", len(recs))

vals = [(r["name"], r["is_deposit"], JUR.get((r["code"] or "").upper()), f"SRID=4326;POINT({r['lon']} {r['lat']})", r["status"], OTYPE.get((r["otype"] or "").lower()),
         r["form"], r["style"], r["comments"], True, TAG, r["acc"]) for r in recs]
ids = execute_values(c, """INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, occurrence_type_id, deposit_form,
                           mineralization_style, comments, is_active, created_by, created_date, position_accuracy)
                           VALUES %s RETURNING occurrence_id""", vals,
                     template="(%s,%s,%s,ST_GeomFromEWKT(%s),%s,%s,%s,%s,%s,%s,%s,now(),%s)", fetch=True, page_size=2000)
newid = [x[0] for x in ids]
log("new occurrences", len(newid))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by) VALUES %s",
               [("OCCURRENCE", newid[i], SRC, r["sid"], TAG) for i, r in enumerate(recs)])
links, seen, unmapped = [], set(), collections.Counter()
for i, r in enumerate(recs):
    for k, t in enumerate(r["com"]):
        v = COM.get(t.lower())
        if v is None: unmapped[t] += 1; continue
        if (newid[i], v) in seen: continue
        seen.add((newid[i], v)); links.append((newid[i], v, "PRIMARY" if k == 0 else "SECONDARY", True, TAG))
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s", links)
log("commodity links", len(links), "| unmapped", dict(unmapped))

c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,%s,%s,%s,%s,true,%s,true,%s,%s,%s,'2026-11-07',true,%s,now()) ON CONFLICT DO NOTHING""",
          (SRC, "EMODnet Geology (European Commission)", "Marine Minerals point layers (nodules, sulphides, Co-rich crusts, placers, phosphorites, metal-rich sediments, vein-hosted), WFS, metadata 2026-09-09",
           "CC BY 4.0 (EMODnet terms; layer metadata: no conditions apply)", "https://emodnet.ec.europa.eu/en/terms-use-emodnet-online-services-data-and-data-products",
           "Source: EMODnet Geology, Marine Minerals (European Commission), CC BY 4.0, with the data provider named in each record.",
           "Cleared: EMODnet terms of use (CC BY 4.0 unless indicated) and layer metadata (no conditions apply), checked 2026-11-07. Loaded 2026-11-07.",
           "European seas plus Caribbean/Central American contributions; a few ISA-supplied points in international waters. Country = contributing survey's country, not a legal EEZ test. "
           "Resource text is as reported (mixed units), not structured estimates. Finnish Baltic video sightings (1,169) not loaded.",
           "D:/CriticalMineralsDB/Documents/Licence_Evidence/EMODnet_Geology_Marine_Minerals/EVIDENCE.md", TAG))

c.execute("SELECT status, is_deposit, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1, 2 ORDER BY 3 DESC", (TAG,)); log("status", c.fetchall())
c.execute("SELECT coalesce(country_name, '(none)'), count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)); log("country", c.fetchall())
c.execute("SELECT x, count(*) FROM core.occurrences, unnest(commodities) x WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC LIMIT 20", (TAG,)); log("commodities", c.fetchall())
c.execute("SELECT count(*) FILTER (WHERE array_length(commodities,1) > 0), count(*) FROM core.occurrences WHERE created_by = %s", (TAG,)); log("with commodities / all", c.fetchone())
c.execute("SELECT name, status, country_name, commodities FROM core.occurrences WHERE created_by = %s ORDER BY random() LIMIT 6", (TAG,)); log("sample", c.fetchall())
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
else:
    g.commit(); log("COMMITTED")
