"""USGS 2024 Minerals Yearbook vol. III global facilities table (doi:10.5066/P1KEQASH, CC0; data year 2024, currentness 2 Sep 2025) ->
core.facility_capacity / core.occurrence_ownership, with positions from myb2024_place.py (placement CSV):
  OCC / REG  -> ATTACH the 2024 capacity rows and owners to that existing occurrence (missing commodities added as SECONDARY)
  TOWN       -> an existing occurrence within 5 km with a matching name -> ATTACH; else a NEW occurrence at the GeoNames town point
               (position_accuracy TOWN_CENTROID; the facility is somewhere near that town)
  unplaced   -> not loaded (province only)
United States and the 10 oil/gas refinery features left out. Capacity rows: one per published row (Global Entry), measure from 'Commodity Unit
Classification' (Gross weight -> GROSS_WEIGHT, Elemental content -> ELEMENTAL_CONTENT, Compound content -> COMPOUND_WEIGHT), the 'X content'
unit as descriptor, stage from Level 3 / feature type, -999 = not published, shared capacities from 'Shared Capacity' (more than one entry).
Usage: python -P load_myb2024.py [--dry]
"""
import collections, csv, difflib, os, re, sys, time, unicodedata
import pandas as pd, psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
SRC, TAG = "USGS_MYB2024", "migration_usgs_myb2024_20261111"
W = "D:/CriticalMineralsDB/World/usgs_facilities_20261110"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v.strip().strip('"')
CITE = "U.S. Geological Survey, 2024 Minerals Yearbook, vol. III (Area Reports: International), facilities table, doi:10.5066/P1KEQASH (CC0)"


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def s(v):
    v = ("" if v is None else str(v)).strip()
    return None if v in ("", "nan", "None", "-999", "-999.0", "NA") else v


def num(v):
    try:
        x = float(str(v).replace(",", "")); return None if (x != x or x < 0) else x
    except (TypeError, ValueError):
        return None


def fold(t):
    t = unicodedata.normalize("NFKD", str(t or "")).lower(); return "".join(ch for ch in t if not unicodedata.combining(ch))


STOP = r"\b(mine|mines|plant|plants|smelter|refinery|works|quarry|quarries|deposit|project|operation|complex|facility|factory|open|pit|underground)\b"
norm = lambda x: re.sub(r"[^a-z0-9]", "", re.sub(STOP, "", fold(x)))
UNIT = {"metric tons": "mt", "carats": "carats", "cubic meters": "m3"}
BASIS = {"gross weight": "GROSS_WEIGHT", "elemental content": "ELEMENTAL_CONTENT", "compound content": "COMPOUND_WEIGHT", "gross volume": None}
STATUS = {"assumed active": "PRODUCER", "inactive": "UNKNOWN"}
# Level 2 commodity names -> core.commodities (metals by symbol); None = no commodity link (capacity row still kept with its name)
ALIAS = {"aluminum": "Al", "alumina": "Alumina", "bauxite": "Bauxite", "antimony": "Sb", "arsenic": "As", "barite": "Baryte", "beryllium": "Be",
         "bismuth": "Bi", "boron": "B", "bromine": "Br", "cadmium": "Cd", "cesium": "Cs", "chromium": "Cr", "chromite": "Cr", "cobalt": "Co", "copper": "Cu",
         "diamond": "Diamond", "fluorspar": "Fluorite", "gallium": "Ga", "germanium": "Ge", "gold": "Au", "graphite": "Graphite", "gypsum": "Gypsum",
         "hafnium": "Hf", "helium": "He", "indium": "In", "iodine": "I", "iron ore": "Fe", "iron": "Fe", "pig iron": "Fe", "steel": "Fe", "raw steel": "Fe",
         "direct-reduced iron": "Direct-Reduced Iron", "lead": "Pb", "lithium": "Li", "magnesium": "Mg", "magnesite": "Mg", "manganese": "Mn",
         "mercury": "Hg", "molybdenum": "Mo", "nickel": "Ni", "niobium": "Nb", "columbium": "Nb", "palladium": "Pd", "platinum": "Pt",
         "platinum-group metals": "PGE", "rhodium": "Rh", "ruthenium": "Ru", "iridium": "Ir", "phosphate rock": "Phosphate Rock", "phosphate": "Phosphate Rock",
         "potash": "Potash", "rare earths": "REE", "rare-earth oxides": "REE", "rhenium": "Re", "selenium": "Se", "silicon": "Si", "silver": "Ag",
         "strontium": "Sr", "sulfur": "S", "tantalum": "Ta", "tellurium": "Te", "thorium": "Th", "tin": "Sn", "titanium": "Ti", "ilmenite": "Ti",
         "rutile": "Ti", "tungsten": "W", "uranium": "U", "vanadium": "V", "zinc": "Zn", "zirconium": "Zr", "zircon": "Zr", "salt": "Salt",
         "soda ash": "Soda Ash", "kaolin": "Kaolin", "bentonite": "Bentonite", "talc": "Talc", "feldspar": "Feldspar", "mica": "Mica",
         "perlite": "Perlite", "vermiculite": "Vermiculite", "wollastonite": "Wollastonite", "diatomite": "Diatomite", "zeolites": "Zeolite",
         "ferroalloys": "Ferroalloys", "ferrochromium": "Cr", "ferromanganese": "Mn", "silicomanganese": "Mn", "ferronickel": "Ni", "ferrosilicon": "Si",
         "ferromolybdenum": "Mo", "ferrovanadium": "V", "ferroniobium": "Nb", "nickel pig iron": "Ni", "lime": "Lime", "limestone": "Limestone",
         "marble": "Marble", "granite": "Granite", "sand and gravel": "Sand and Gravel", "silica": "Silica Sand", "clays": "Clay", "clay": "Clay",
         "nepheline syenite": "Nepheline Syenite", "olivine": "Olivine", "pumice": "Pumice", "kyanite": "Kyanite", "sillimanite": "Sillimanite",
         "andalusite": "Andalusite", "garnet": "Garnet", "asbestos": "Asbestos", "sepiolite": "Sepiolite", "attapulgite": "Palygorskite",
         "talc and related materials": "Talc", "pumice and related materials": "Pumice", "niobium and tantalum": "Nb", "ball clay": "Clay",
         "fire clay": "Clay", "iron oxide pigments": "Iron Oxide Pigments", "kyanite and related materials": "Kyanite", "scandium": "Sc",
         "beryl": "Beryl", "celestite": "Sr", "arsenic trioxide": "As", "peat": "Peat"}

# ------------------------------------------------------------------ read
f = pd.read_csv(f"{W}/myb2024/2024MYBv3_Facilities_table.csv", dtype=str, encoding="utf-8-sig")
f = f.astype(object).where(f.notna(), None)
pl = pd.read_csv(f"{W}/myb2024_placement.csv", dtype={"fid": str, "iso2": str}, keep_default_na=False, na_values=[""]).set_index("fid")  # Namibia = NA
log("rows", len(f), "| placement methods", pl.method.fillna("NONE").value_counts().to_dict())

g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SET statement_timeout = 0")
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
c.execute("SELECT iso_code, jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY'"); JI = dict(c.fetchall())
c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,)); DONE = {x[0] for x in c.fetchall()}
unmapped = collections.Counter()


def cid_of(name):
    if not name: return None
    k = fold(name).strip()
    nm = ALIAS.get(k) or ALIAS.get(re.sub(r"\s*\(.*\)$", "", k))
    if nm is None: unmapped[name] += 1; return None
    return GN.get(nm.lower())


def match(name, lon, lat):
    c.execute("""SELECT occurrence_id, name, ST_Distance(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) d FROM core.occurrences
                 WHERE is_active AND created_by <> %s AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, 5000) ORDER BY d LIMIT 8""",
              (lon, lat, TAG, lon, lat))
    near = c.fetchall(); nm = norm(name)
    for oid, n2, d in near:
        n2n = norm(n2)
        if nm and n2n and (difflib.SequenceMatcher(None, nm, n2n).ratio() > 0.85 or (len(nm) > 5 and len(n2n) > 5 and (nm in n2n or n2n in nm))):
            return oid, n2, round(d)
    return None, (near[0][1] if near else None), (round(near[0][2]) if near else None)


def stage_of(r):
    t = (r["Level 3 (Type)"] or "").lower(); ft = (r["Feature Type"] or "").lower()
    if t == "mine" or "mines and quarries" in ft or ft == "brine": return "Mine"
    if t == "refinery": return "Refinery"
    if t == "smelter": return "Smelter"
    p = " ".join(x for x in [r["Level 5 (Form)"], r["Level 2 (Commodity)"]] if x).lower()
    if "concentrat" in p: return "Concentrator"
    return None


ext, cap, own, logrows, stats = [], [], [], [], collections.Counter()
for fid, grp in f.groupby("USGS Facility ID", sort=False):
    r0 = grp.iloc[0]
    if (r0["Country (Short Form) or Locality"] or "").strip().lower() == "united states": continue
    if any("oil and gas" in (x or "").lower() for x in grp["Feature Type"]): stats["oil/gas left out"] += 1; continue
    sid = "fac2024:" + fid
    if sid in DONE: stats["already loaded"] += 1; continue
    if fid not in pl.index or not isinstance(pl.at[fid, "method"], str): stats["unplaced (not loaded)"] += 1; continue
    p = pl.loc[fid]; method = p["method"]; name = r0["Facility Name"]; country = r0["Country (Short Form) or Locality"]
    comms = list(dict.fromkeys(x for x in grp["Level 2 (Commodity)"] if x))
    oid = int(p["occurrence_id"]) if method in ("OCC", "REG") else None
    near = dist = None
    if oid is None:
        oid, near, dist = match(name, float(p["lon"]), float(p["lat"]))
        if oid: method = "TOWN+NAME"
    status_pub = (r0["Facility Status"] or "").strip()
    if oid:
        act = "ATTACH"
        if not DRY:
            c.execute("SELECT commodity_id FROM core.occurrence_commodities WHERE occurrence_id = %s AND is_active", (oid,)); have = {x[0] for x in c.fetchall()}
            for cm in comms:
                ci = cid_of(cm)
                if ci and ci not in have:
                    have.add(ci); c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,'SECONDARY',true,%s)", (oid, ci, TAG))
    else:
        act = "NEW"
        is_dep = any("mines and quarries" in (x or "").lower() or (x or "").lower() == "brine" for x in grp["Feature Type"])
        com = " | ".join(x for x in [
            f"USGS Minerals Yearbook 2024 facility {fid} ({CITE})",
            f"Feature type: {', '.join(sorted(set(x for x in grp['Feature Type'] if x)))}",
            f"Commodities (as published): {', '.join(comms)}",
            f"Facility status (as published, 2024): {status_pub}" + (" - assumed (not verified) by USGS" if status_pub.lower().startswith("assumed") else ""),
            f"Location (as published): {r0['Location Description']}" if r0["Location Description"] else None,
            f"POSITION IS APPROXIMATE: placed at the GeoNames town point ({p['detail']}); the facility is somewhere near that town",
            f"Operator: {r0['Major Operating Company']}" if r0["Major Operating Company"] else None,
            f"Nearest existing occurrence: {near} ({dist} m), name differs - not merged" if near else None,
            f"Source: U.S. Geological Survey (CC0); position: GeoNames (CC BY 4.0). Load tag {TAG}"] if x)
        if not DRY:
            c.execute("""INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, comments, is_active,
                         created_by, created_date, position_accuracy) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,'UNKNOWN',%s,%s,true,%s,now(),'TOWN_CENTROID')
                         RETURNING occurrence_id""",
                      (name[:300], is_dep, JI.get(p["iso2"]), float(p["lon"]), float(p["lat"]), STATUS.get(status_pub.lower(), "UNKNOWN"),
                       None if is_dep else "Processing plant", com, TAG))
            oid = c.fetchone()[0]
            for i, cm in enumerate(comms):
                ci = cid_of(cm)
                if ci: c.execute("INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES (%s,%s,%s,true,%s) ON CONFLICT DO NOTHING",
                                 (oid, ci, "PRIMARY" if i == 0 else "SECONDARY", TAG))
        else:
            oid = -1
    stats[f"{act} via {method}"] += 1
    ext.append(("OCCURRENCE", oid, SRC, sid, {"OCC": "MEDIUM", "REG": "HIGH", "TOWN+NAME": "MEDIUM"}.get(method, "EXACT"), TAG))
    logrows.append([fid, name, country, method, act, oid, near, dist])
    seen = set()
    for _, r in grp.iterrows():
        capv = num(r["Annual Production Capacity"]); unit = UNIT.get((r["Capacity Unit"] or "").lower(), s(r["Capacity Unit"]))
        notes = [x for x in [s(r["Capacity Notes"]), "estimated" if "E" in (r["Capacity Code"] or "") else None, s(r["Commodity Footnote"])] if x]
        if capv is not None and unit == "mt" and (capv >= 1e9 or ("sand" not in (r["Level 2 (Commodity)"] or "").lower() and capv >= 1.5e8)):
            notes.append(f"published capacity {capv:g} t is implausible as an annual capacity - not loaded"); capv = None
        shared = [x.strip() for x in (r["Shared Capacity"] or "").split(",") if x.strip()]
        cu = s(r["Commodity Unit"])
        desc = "; ".join(x for x in [s(r["Descriptor"]), cu if cu and cu.lower() != "gross weight" else None] if x) or None
        cap.append((oid, cid_of(r["Level 2 (Commodity)"]), r["Level 2 (Commodity)"], (r["Level 1 (Commodity Group)"] or "")[:40] or None,
                    (r["Feature Type"] or "")[:40] or None, stage_of(r), (r["Level 4 (Phase)"] or None),
                    r["Level 5 (Form)"] or r["Level 3 (Type)"], desc, capv, unit if capv is not None else None,
                    BASIS.get((r["Commodity Unit Classification"] or "").lower()), "; ".join(notes) or None, shared if len(shared) > 1 else None,
                    (status_pub or None) and status_pub[:30], (r["Multiple Commodities"] or "").upper().startswith("Y") if r["Multiple Commodities"] else None,
                    (r["Multiple Products"] or "").upper().startswith("Y") if r["Multiple Products"] else None, 2024, SRC, r["Global Entry"],
                    s(r["Location Footnote"]), None, TAG))
        opn = s(r["Major Operating Company"])
        ents = ([("OPERATOR", opn, None)] if opn else []) + [("EQUITY_OWNER", s(r[f"Equity Owner {i}"]), num(r[f"Share of Equity Owner {i}"])) for i in range(1, 9) if s(r[f"Equity Owner {i}"])]
        for role, nm_, sh in ents:
            if (role, nm_) in seen: continue
            seen.add((role, nm_)); own.append((oid, nm_[:300], role, sh if sh is not None and sh <= 100 else None, 2024, SRC, None, TAG))

with open(os.path.join(HERE, f"myb2024_load_log_20261111{'_DRY' if DRY else ''}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["fid", "name", "country", "method", "action", "occurrence_id", "nearest_existing", "distance_m"]); w.writerows(logrows)
log(dict(stats)); log("capacity rows", len(cap), "| ownership rows", len(own), "| unmapped commodity names (top 25)", dict(unmapped.most_common(25)))
log("by country (top 25):", collections.Counter(r[2] for r in logrows).most_common(25))
if DRY:
    g.rollback(); log("DRY RUN - nothing written"); sys.exit()
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s ON CONFLICT DO NOTHING", ext, page_size=2000)
execute_values(c, """INSERT INTO core.facility_capacity (occurrence_id, commodity_id, commodity_name, commodity_group, feature_type, facility_stage, phase, product_form,
                     product_descriptor, annual_capacity, capacity_unit, capacity_basis, capacity_notes, shared_with_rows, facility_status, multiple_commodities,
                     multiple_products, data_year, source_system, source_row_id, footnote, source_urls, created_by) VALUES %s""", cap, page_size=1000)
c.execute("SELECT company_id, name, short_name FROM core.companies WHERE is_active")
SUFFIX = r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|plc|company|co|holdings|group|the|lp|sa|nv|ag|pty|spa|s a)\b"
nz = lambda v: re.sub(r"\s+", " ", re.sub(SUFFIX, " ", re.sub(r"[^a-z0-9 ]+", " ", (v or "").lower()))).strip()
comp = {}
for ci, nm, sn in c.fetchall():
    for v in (nm, sn):
        if nz(v) and len(nz(v)) > 3: comp[nz(v)] = ci
_seen, _own = set(), []
for row in own:
    if (row[0], row[2], row[1]) not in _seen: _seen.add((row[0], row[2], row[1])); _own.append(row)
execute_values(c, "INSERT INTO core.occurrence_ownership (occurrence_id, owner_name, company_id, ownership_role, share_pct, as_of_year, source_system, footnote, created_by) VALUES %s",
               [(o, n, comp.get(nz(n)), role, sh, yr, src, fn, tg) for o, n, role, sh, yr, src, fn, tg in _own], page_size=1000)
c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
             licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
             VALUES (%s,'U.S. Geological Survey','2024 Minerals Yearbook, vol. III (Area Reports: International) - global mineral facilities table (157 countries)',
             'CC0 1.0 (USGS data release)','https://creativecommons.org/publicdomain/zero/1.0/',true,%s,true,
             'Cleared: USGS data release doi:10.5066/P1KEQASH, CC0 - checked 2026-11-10. Positions from GeoNames cities500 (CC BY 4.0). Loaded 2026-11-11.',
             'Data year 2024 (currentness 2 Sep 2025); status Assumed active = USGS assumption. The table has NO coordinates: facilities are attached to existing sites by name or by the USGS regional GIS points, or placed at the GeoNames town named in the location text (position_accuracy TOWN_CENTROID, approximate); about 45%% of facilities (located only to a province) were not loaded. United States and oil/gas refineries left out.',
             'https://doi.org/10.5066/P1KEQASH','2026-11-11',true,%s,now()) ON CONFLICT DO NOTHING""", (SRC, f"Source: {CITE}.", TAG))
g.commit()
c.execute("SELECT count(*), count(*) FILTER (WHERE jurisdiction_id IS NULL) FROM core.occurrences WHERE created_by = %s", (TAG,)); log("new occurrences / no jurisdiction", c.fetchone())
c.execute("SELECT count(*), count(DISTINCT occurrence_id) FROM core.facility_capacity WHERE source_system = %s", (SRC,)); log("capacity rows / facilities", c.fetchone())
