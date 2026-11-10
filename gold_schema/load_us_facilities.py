"""USGS 'Mines, smelters, refineries, and recycling facilities in the United States' (2026, CC0, DOI 10.5066/P1BUPUAM) -> interzona_cm.

Reads D:/CriticalMineralsDB/Processing/facilities_placement_proposal.csv (from place_us_facilities.py) and the worksheet, then
  * ATTACH facilities: use the existing occurrence (nothing on it is changed); NEW_* facilities: a new core.occurrences row
    (is_deposit = false, workings_type 'Processing plant' for processing plants, position_accuracy TOWN_CENTROID / AREA_CENTROID / COUNTY_CENTROID,
    status from the facility status, commodities from the sheet); UNPLACED facilities are NOT loaded (listed in _facilities_unplaced.csv);
  * core.external_ids: OCCURRENCE / USGS_US_FACILITIES / USGS facility id (USA0001 ...);
  * core.facility_capacity: one row per worksheet row (annual capacity, stage, form, basis, shared-capacity partners ...);
  * core.occurrence_ownership: operator + equity owners, de-duplicated per facility; company_id only for an exact (suffix-stripped) match to core.companies.
Status mapping: Assumed active -> PRODUCER, In development -> DEVELOPMENT, Care and maintenance -> CARE_AND_MAINTENANCE, Inactive -> CLOSED.
Idempotent: facility ids already in core.external_ids are skipped.  Usage: python load_us_facilities.py [--dry]   (--dry = load, verify, ROLLBACK)
"""
import os, re, sys, time, csv, collections
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DRY = "--dry" in sys.argv
TAG = "migration_usgs_facilities_20261015"
SRC = "USGS_US_FACILITIES"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
XLSX = r"D:\CriticalMineralsDB\Processing\Mines, smelters, refineries, and recycling facilities in the United States_worksheet.xlsx"
PROP = os.environ.get("PROP_IN", r"D:\CriticalMineralsDB\Processing\facilities_placement_proposal.csv")
STATUS = {"assumed active": "PRODUCER", "in development": "DEVELOPMENT", "care and maintenance": "CARE_AND_MAINTENANCE", "inactive": "CLOSED"}
BASIS = {"elemental content": "ELEMENTAL_CONTENT", "gross weight": "GROSS_WEIGHT", "compounds weight": "COMPOUND_WEIGHT", "compound weight": "COMPOUND_WEIGHT"}
ALIAS = {"rare earths": "REE", "phosphate": "Phosphate Rock", "iron ore": "Fe", "aluminum": "Al", "alumina": "Alumina", "lime": "Lime", "barite": "Baryte", "fluorspar": "Fluorite", "sulfur": "S",
         "gypsum": "Gypsum", "graphite": "Graphite", "coal": "Coal", "helium": "He", "potash": "Potash", "boron": "B", "silicon": "Si", "quartz": "Quartz", "magnesium": "Mg", "platinum": "Pt", "palladium": "Pd"}
ELEM = {"Lithium": "Li", "Beryllium": "Be", "Boron": "B", "Magnesium": "Mg", "Aluminum": "Al", "Silicon": "Si", "Sulfur": "S", "Titanium": "Ti", "Vanadium": "V", "Chromium": "Cr", "Manganese": "Mn", "Cobalt": "Co",
        "Nickel": "Ni", "Copper": "Cu", "Zinc": "Zn", "Gallium": "Ga", "Germanium": "Ge", "Arsenic": "As", "Selenium": "Se", "Bromine": "Br", "Zirconium": "Zr", "Niobium": "Nb", "Molybdenum": "Mo",
        "Ruthenium": "Ru", "Rhodium": "Rh", "Palladium": "Pd", "Silver": "Ag", "Cadmium": "Cd", "Indium": "In", "Tin": "Sn", "Antimony": "Sb", "Tellurium": "Te", "Hafnium": "Hf", "Tantalum": "Ta",
        "Tungsten": "W", "Rhenium": "Re", "Iridium": "Ir", "Platinum": "Pt", "Gold": "Au", "Lead": "Pb", "Bismuth": "Bi", "Uranium": "U", "Scandium": "Sc", "Iron": "Fe"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def clean(v):
    v = (v or "").strip()
    return None if v in ("", "NA", "N/A", "-999") else v


def fnum(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return None if x == -999 else x
    except Exception:
        return None


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
g.autocommit = False
c = g.cursor(); c.execute("SET statement_timeout = 0")

prop = pd.read_csv(PROP, dtype=str, encoding="utf-8-sig").fillna("")
df = pd.read_excel(XLSX, sheet_name=0, dtype=str).fillna("")
df = df.loc[:, [x for x in df.columns if x.strip()]]
log("proposal rows", len(prop), "| worksheet rows", len(df), "| actions", prop["action"].value_counts().to_dict())

c.execute("SELECT jurisdiction_id FROM core.jurisdictions WHERE level = 'COUNTRY' AND iso_code = 'US'"); US_JID = c.fetchone()[0]
c.execute("SELECT lower(commodity_name), commodity_id FROM core.commodities"); GN = dict(c.fetchall())
_cm = {}


def commodity_id(name):
    n = name.strip()
    if n in _cm: return _cm[n]
    out = None
    for cand in (n.lower(), ALIAS.get(n.lower(), "").lower(), (ELEM.get(n, "")).lower()):
        if cand and cand in GN: out = GN[cand]; break
    _cm[n] = out
    return out


c.execute("SELECT source_id FROM core.external_ids WHERE entity_type = 'OCCURRENCE' AND source_system = %s", (SRC,))
done = {x[0] for x in c.fetchall()}
log("facilities already loaded (skipped)", len(done))

placed = prop[(prop["action"] != "UNPLACED") & (~prop["facility_id"].isin(done))].copy()
unplaced = prop[prop["action"] == "UNPLACED"]
unplaced[["facility_id", "name", "town_text", "st", "feature", "commodities"]].to_csv(os.path.join(HERE, "_facilities_unplaced.csv"), index=False, encoding="utf-8")
log("to load", len(placed), "| unplaced (not loaded)", len(unplaced))

fac_rows = {fid: grp for fid, grp in df.groupby("USGS Facility ID")}


def comment(p, grp):
    f = grp.iloc[0]
    parts = [f"USGS facility {p['facility_id']} (O'Brien and others, 2026, doi:10.5066/P1BUPUAM)"]
    parts.append("Location (as published): " + p["town_text"])
    if p["action"].startswith("NEW"):
        if p.get("position_note"):  # hand-checked placements (round 3, 2026-10-31) say exactly how the position was found
            how = p["position_note"]
        elif p["town_match"].startswith("gnis"):
            how = f"USGS GNIS feature '{p['gaz_place']}' ({p['town_match'].replace('gnis:', '')}), a locality point"
        else:
            how = {"NEW_TOWN": f"centre of {p['gaz_place'] or p['town_text']} (Census 2026 Gazetteer place)", "NEW_AREA": f"centre of the Census county subdivision {p['gaz_place']}",
                   "NEW_COUNTY": "centre of the MRDS sites recorded for that county"}[p["action"]]
        if p["position_accuracy"]:
            parts.append(f"POSITION IS APPROXIMATE ({p['position_accuracy']}): {how}; the source gives only town and state")
        else:  # round 4: a site-specific point (permit, EPA facility record or geocoded street address)
            parts.append(f"Position: {how}")
    parts.append("Feature type: " + f["Feature Type"])
    types = sorted({x for x in grp["Level 3 (Type)"] if x})
    if types: parts.append("Facility type: " + ", ".join(types))
    parts.append("Commodities (as published): " + p["commodities"])
    parts.append("Facility status (as published): " + f["Facility Status"])
    if p["review_candidate"]:
        parts.append("Possible match not applied: " + p["review_candidate"])
    parts.append("Source: U.S. Geological Survey, Mines, smelters, refineries, and recycling facilities in the United States (CC0). Load tag " + TAG)
    return " | ".join(parts)


# ---------------------------------------------------------------- occurrences
new_rows, new_meta, occ_of = [], [], {}
for _, p in placed.iterrows():
    grp = fac_rows[p["facility_id"]]
    if p["action"] == "ATTACH":
        occ_of[p["facility_id"]] = int(p["occ_id"]); continue
    f = grp.iloc[0]
    st = STATUS.get(f["Facility Status"].strip().lower(), "UNKNOWN")
    work = "Processing plant" if f["Feature Type"] == "Mineral Processing Plant" else None
    new_rows.append((f["Facility Name"].strip()[:300], False, US_JID, float(p["lon"]), float(p["lat"]), st, work, comment(p, grp), p["position_accuracy"] or None))
    new_meta.append(p)
tmpl = "(%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, 'UNKNOWN', %s, %s, true, '" + TAG + "', now(), %s)"
ids = execute_values(c, "INSERT INTO core.occurrences (name, is_deposit, jurisdiction_id, geom, status, size_category, workings_type, comments, is_active, created_by, created_date, position_accuracy) VALUES %s RETURNING occurrence_id",
                     new_rows, template=tmpl, page_size=1000, fetch=True)
for (oid,), p in zip(ids, new_meta):
    occ_of[p["facility_id"]] = oid
log("occurrences inserted", len(ids), "| attached to existing", sum(1 for _, p in placed.iterrows() if p["action"] == "ATTACH"))

# commodity links for NEW occurrences only (first listed = PRIMARY)
links, unmapped = {}, collections.Counter()
for p in new_meta:
    grp = fac_rows[p["facility_id"]]
    names = list(dict.fromkeys(x.strip() for x in grp["Level 2 (Commodity)"] if x.strip()))
    for i, n in enumerate(names):
        cid = commodity_id(n)
        if cid is None: unmapped[n] += 1; continue
        k = (occ_of[p["facility_id"]], cid)
        if k not in links: links[k] = "PRIMARY" if i == 0 else "SECONDARY"
execute_values(c, "INSERT INTO core.occurrence_commodities (occurrence_id, commodity_id, commodity_role, is_active, created_by) VALUES %s",
               [(o, cid, role, True, TAG) for (o, cid), role in links.items()], template="(%s, %s, %s, %s, %s)", page_size=2000)
log("commodity links (new occurrences)", len(links), "| unmapped commodity names", dict(unmapped))

# external ids
ext = []
for _, p in placed.iterrows():
    conf = "EXACT" if p["action"].startswith("NEW") else ("HIGH" if p["comm_match"] in ("True", "true", "TRUE") and float(p["name_sim"] or 0) >= 0.9 else "MEDIUM")
    ext.append(("OCCURRENCE", occ_of[p["facility_id"]], SRC, p["facility_id"], conf, TAG))
execute_values(c, "INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, match_confidence, created_by) VALUES %s", ext, page_size=2000)
log("external ids", len(ext))

# ---------------------------------------------------------------- capacity rows
cap = []
for fid, oid in occ_of.items():
    for _, r in fac_rows[fid].iterrows():
        shared = [x.strip() for x in re.split(r"[,;]", r["Shared Capacity"]) if x.strip() and x.strip() != r["Global entry"].strip()]
        urls = [clean(r[k]) for k in ("Data Source 1", "Data Source 2", "Data Source 3", "Data Source 4")]
        urls = [u for u in urls if u]
        cap_val = fnum(r["Annual Production Capacity"])
        unit = clean(r["Capacity Unit"])
        feature_stage = clean(r["Level 3 (Type)"]) or ("Mine" if r["Feature Type"] == "Mines and Quarries" else None)
        cap.append((oid, commodity_id(r["Level 2 (Commodity)"]), r["Level 2 (Commodity)"].strip(), clean(r["Level 1 (Commodity group)"]), r["Feature Type"].strip() or None, feature_stage,
                    clean(r["Level 4 (Phase)"]), clean(r["Level 5 (Form)"]), clean(r["GMAS Descriptor"]), cap_val, unit if cap_val is not None else None,
                    BASIS.get(r["Commodity Unit classification"].strip().lower()), clean(r["Capacity Notes"]), shared or None, clean(r["Facility Status"]),
                    r["Multiple Commodities"].strip().upper() == "Y" if r["Multiple Commodities"].strip() else None, r["Multiple Products"].strip().upper() == "Y" if r["Multiple Products"].strip() else None,
                    int(r["Date Updated"]) if r["Date Updated"].strip().isdigit() else None, SRC, r["Global entry"].strip(), clean(r["Commodity Footnote"]), urls or None, TAG))
execute_values(c, """INSERT INTO core.facility_capacity (occurrence_id, commodity_id, commodity_name, commodity_group, feature_type, facility_stage, phase, product_form, product_descriptor, annual_capacity,
                     capacity_unit, capacity_basis, capacity_notes, shared_with_rows, facility_status, multiple_commodities, multiple_products, data_year, source_system, source_row_id, footnote, source_urls, created_by)
                     VALUES %s""", cap, page_size=1000)
log("capacity rows", len(cap))

# ---------------------------------------------------------------- ownership
c.execute("SELECT company_id, name, short_name FROM core.companies WHERE is_active")
SUFFIX = r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|plc|company|co|holdings|group|the|lp|sa|nv|ag)\b"
nz = lambda s: re.sub(r"\s+", " ", re.sub(SUFFIX, " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()))).strip()
comp = {}
for cid, nm, sn in c.fetchall():
    for x in (nm, sn):
        if nz(x): comp[nz(x)] = cid
own = []
# owners already recorded for these occurrences (several facilities can attach to one occurrence, and re-runs add to earlier loads)
c.execute("SELECT occurrence_id, ownership_role, owner_name FROM core.occurrence_ownership WHERE source_system = %s", (SRC,))
seen = {(o, r, n) for o, r, n in c.fetchall()}
for fid, oid in occ_of.items():
    for _, r in fac_rows[fid].iterrows():
        op = clean(r["Major Operating Company"])
        entries = [("OPERATOR", op, None)] if op else []
        for i in range(1, 10):
            nm = clean(r[f"Equity Owner {i}"])
            if nm:
                sh = fnum(r[f"Share of Equity Owner {i}"])
                entries.append(("EQUITY_OWNER", nm, sh if sh is not None and 0 <= sh <= 100 else None))
        for role, nm, sh in entries:
            k = (oid, role, nm)
            if k in seen: continue
            seen.add(k)
            own.append((oid, nm[:300], comp.get(nz(nm)), role, sh, 2026, SRC, clean(r["Company Footnote"]), TAG))
execute_values(c, "INSERT INTO core.occurrence_ownership (occurrence_id, owner_name, company_id, ownership_role, share_pct, as_of_year, source_system, footnote, created_by) VALUES %s", own, page_size=1000)
log("ownership rows", len(own), "| matched to core.companies", sum(1 for o in own if o[2]))

# ---------------------------------------------------------------- verification
def one(sql, p=None):
    c.execute(sql, p); return c.fetchall()


log("new occurrences: count / is_deposit / with commodities", one("SELECT count(*), count(*) FILTER (WHERE is_deposit), count(*) FILTER (WHERE array_length(commodities, 1) > 0) FROM core.occurrences WHERE created_by = %s", (TAG,)))
log("new occurrences by position_accuracy", one("SELECT position_accuracy, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)))
log("new occurrences by status", one("SELECT status, count(*) FROM core.occurrences WHERE created_by = %s GROUP BY 1 ORDER BY 2 DESC", (TAG,)))
log("country / state sanity: new occurrences outside the US (must be 0)", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s AND country_name IS DISTINCT FROM 'United States'", (TAG,))[0][0])
log("facility ids with an external id vs placed facilities", one("SELECT count(DISTINCT source_id) FROM core.external_ids WHERE source_system = %s", (SRC,))[0][0], len(placed) + len(done))
log("capacity rows: total / with a capacity / mt", one("SELECT count(*), count(annual_capacity), count(*) FILTER (WHERE capacity_unit = 'mt') FROM core.facility_capacity WHERE source_system = %s", (SRC,)))
log("capacity rows by basis", one("SELECT capacity_basis, count(*) FROM core.facility_capacity WHERE source_system = %s GROUP BY 1 ORDER BY 2 DESC", (SRC,)))
log("commodity_id mapped vs not", one("SELECT count(*) FILTER (WHERE commodity_id IS NOT NULL), count(*) FILTER (WHERE commodity_id IS NULL) FROM core.facility_capacity WHERE source_system = %s", (SRC,)))
log("rows with shared partners", one("SELECT count(*) FROM core.facility_capacity WHERE source_system = %s AND shared_with_rows IS NOT NULL", (SRC,))[0][0])
log("lithium capacity rows", one("""SELECT o.name, fc.facility_stage, fc.annual_capacity, fc.capacity_basis, fc.facility_status FROM core.facility_capacity fc JOIN core.occurrences o USING (occurrence_id)
   WHERE fc.source_system = %s AND fc.commodity_name = 'Lithium' ORDER BY fc.annual_capacity DESC NULLS LAST LIMIT 6""", (SRC,)))
log("ownership roles", one("SELECT ownership_role, count(*), count(share_pct), count(company_id) FROM core.occurrence_ownership WHERE source_system = %s GROUP BY 1", (SRC,)))
log("owners matched to core.companies", one("SELECT DISTINCT owner_name, company_id FROM core.occurrence_ownership WHERE source_system = %s AND company_id IS NOT NULL LIMIT 12", (SRC,)))
log("core.occurrences total", one("SELECT count(*) FROM core.occurrences")[0][0])
if DRY:
    g.rollback(); log("DRY RUN - rolled back")
    log("after rollback: tagged occurrences (must be 0)", one("SELECT count(*) FROM core.occurrences WHERE created_by = %s", (TAG,))[0][0])
else:
    c.execute("UPDATE core.data_sources SET is_loaded = true, licence_status = 'Cleared: CC0 1.0 (ScienceBase and USGS release page, 2026-10-15). Loaded 2026-10-15.' WHERE source_system = %s", (SRC,))
    g.commit(); log("COMMITTED")
g.close()
