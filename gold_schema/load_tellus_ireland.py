"""Tellus geochemistry of Ireland -> interzona_cm gold, two new sources (own partitions; rollback = delete by created_by = TAG):
  IRELAND_GSI_TELLUS  Geological Survey Ireland (GSI) Tellus data, CC BY 4.0 - attribution: "Contains Irish Public Sector Data (Geological Survey
                      Ireland) licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence."
  NI_GSNI_TELLUS      Geological Survey of Northern Ireland (GSNI) Tellus soils, UK Open Government Licence v3.0 - attribution: "Contains UK public
                      sector information (Geological Survey of Northern Ireland) licensed under the UK Open Government Licence v3.0."
Licence text: GSI_Licence_CC_BY_40.txt in the GSI zips and the ISO metadata (.shp.xml) of the all-island IE32 layers. Files downloaded by the user
(Feb 2026) in D:/CriticalMineralsDB/Ireland, extracted to D:/CriticalMineralsDB/Ireland/_x.

GSI (spreadsheets, one per survey block; latest versions):
  58xxxxA-65xxxxA shallow topsoil v1.2 (pH, LOI, XRFS, ICPar; ICPar by SGS for 58xxxxA and ALS-OMAC for 61-65xxxxA), 6117xxA-6174xxA (G5) v1.1,
  G7/G9 South-East 6175xxA-6307xxA v1.0, G8 Dublin 670xxxA v1.0; deeper topsoil 58xxxxS-65xxxxS v2.2, 6117xxS-6174xxS (G5), G8 Dublin 670xxxS;
  stream sediment 58xxxxC-60xxxxC v1.1 (XRFS + fire assay ICP-MS Au/Pd/Pt, <150 um); SE Ireland lithogeochemistry 2021 (rocks; XRFS, INAA, AAS,
  compiled from published references). Stream water (58xxxxW) is NOT loaded (water), nor pH (no pH analyte in the schema).
  Censoring by GSI: "<LLD" replaced by HDL = 0.5 x LLD and ">URL" by the URL. A value equal to one of the column's published HDLs is classified
  BELOW_DL_PROBABLE (dl_value = that LLD; values below the LLD reported as detected were left uncensored by GSI, so equality is the test); a value
  equal to the column's URL is ABOVE_UDL. Neither is used in statistics.
  Data_Below_LLD sheets (B, Ta, Pd, Pt, Re, Au aqua regia - non-accredited, uncensored readings below the accredited LLD) -> package
  GSI_TELLUS_AR_BLD (priority 2, behind the accredited values).
NI (GSNI rows of the all-island IE32 shapefiles; DATASOURCE = GSNI, sampled 2004-2006): shallow topsoil A aqua regia ICP + XRFS + LOI, deeper
  topsoil S aqua regia ICP. The release is censored to half the detection limit ("..._HDL") but gives no limits, so (as for GEMAS) each column's
  minimum, where it makes up at least 1% of the samples, is BELOW_DL_PROBABLE with dl_value = 2 x that value (inferred).
Coordinates: ITM (EPSG:2157) where given, else Irish Grid (EPSG:29903, checked against ITM on rows that have both).
Usage: python load_tellus_ireland.py [--check]
"""
import os, re, sys, io, csv, glob, time, collections
import openpyxl, psycopg2
import geopandas as gpd
from pyproj import Transformer

CHECK = "--check" in sys.argv
TAG = "migration_tellus_ireland_20261115"
SRC_GSI, SRC_NI = "IRELAND_GSI_TELLUS", "NI_GSNI_TELLUS"
PART = {SRC_GSI: "ireland_gsi_tellus", SRC_NI: "ni_gsni_tellus"}
XID = {SRC_GSI: "GSI_TELLUS_SAMPLE_ID", SRC_NI: "GSNI_TELLUS_SAMPLE_ID"}
X = "D:/CriticalMineralsDB/Ireland/_x/"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


# ---------------- packages: code -> (name, method_code, lab_code, basis, priority, description)
PKGS = {
    "GSI_TELLUS_ICPMS_AR": ("GSI Tellus - ICP-MS Aqua Regia (Topsoil)", "AR-ICPMS", "GSI_TELLUS", "P", 1,
                            "Aqua regia digestion, ICP-MS / ICP-ES finish, <2 mm soil (SGS for 58xxxx Border samples, ALS-OMAC Loughrea otherwise); GSI censored <LLD to half the LLD"),
    "GSI_TELLUS_AR_BLD": ("GSI Tellus - Aqua Regia readings below the accredited LLD (B, Ta, Au, Pd, Pt, Re)", "AR-ICPMS", "GSI_TELLUS", "P", 2,
                          "Non-accredited, uncensored aqua regia readings below the accredited LLD, provided by GSI for elements where >80% of samples fall below it"),
    "GSI_TELLUS_LOI": ("GSI Tellus - Loss on Ignition 450°C (Topsoil)", None, "GSI_TELLUS", "T", 5, "Loss on ignition at 450 °C, <2 mm soil"),
    "GSI_TELLUS_XRFS": ("GSI Tellus - XRF spectrometry (soil and stream sediment)", "NONE-XRF", "GSI_TELLUS", "T", 3,
                        "X-ray fluorescence spectrometry; soils <2 mm, stream sediments <150 um; correction factors applied to K2O, V, Co, Cu, Yb in topsoils"),
    "GSI_TELLUS_SED_FA": ("GSI Tellus - fire assay ICP-MS Au, Pd, Pt (stream sediment)", "FA-ICPMS", "GSI_TELLUS", "T", 1,
                          "Lead fire assay with ICP-MS finish, <150 um stream sediment"),
    "GSI_TELLUS_ROCK_XRF": ("GSI SE Ireland lithogeochemistry - XRF majors (compiled)", "NONE-XRF", "GSI_TELLUS", "T", 3,
                            "SE Ireland lithogeochemistry compilation 2021: XRF major oxides from the cited references"),
    "GSI_TELLUS_ROCK_INAA": ("GSI SE Ireland lithogeochemistry - INAA (compiled)", "NONE-INAA", "GSI_TELLUS", "T", 2,
                             "SE Ireland lithogeochemistry compilation 2021: instrumental neutron activation analysis"),
    "GSI_TELLUS_ROCK_AAS": ("GSI SE Ireland lithogeochemistry - AAS (compiled, digestion not recorded)", None, "GSI_TELLUS", "P", 4,
                            "SE Ireland lithogeochemistry compilation 2021: atomic absorption, digestion not recorded (treated as partial)"),
    "GSNI_TELLUS_AR": ("GSNI Tellus Northern Ireland - aqua regia ICP (soil)", "AR-ICPMS", "UNK", "P", 1,
                       "Tellus Northern Ireland regional soils (GSNI 2004-2006), aqua regia ICP; censored to half the detection limit (limits not published with the release)"),
    "GSNI_TELLUS_XRFS": ("GSNI Tellus Northern Ireland - XRF spectrometry (soil)", "NONE-XRF", "UNK", "T", 3,
                         "Tellus Northern Ireland regional shallow soils (GSNI 2004-2006), XRF spectrometry; censored to half the detection limit"),
    "GSNI_TELLUS_LOI": ("GSNI Tellus Northern Ireland - Loss on Ignition (soil)", None, "UNK", "T", 5, "Tellus Northern Ireland shallow soils, loss on ignition"),
}
FAM_PKG = {"ICPar": "GSI_TELLUS_ICPMS_AR", "XRFS": "GSI_TELLUS_XRFS", "FA_ICPMS": "GSI_TELLUS_SED_FA", "LOI": "GSI_TELLUS_LOI",
           "BLD": "GSI_TELLUS_AR_BLD", "R_XRFS": "GSI_TELLUS_ROCK_XRF", "R_INAA": "GSI_TELLUS_ROCK_INAA", "R_AAS": "GSI_TELLUS_ROCK_AAS"}
UNIT = {"%": "%", "mgkg": "ppm", "µgkg": "ppb", "ugkg": "ppb", "ppm": "ppm", "ppb": "ppb", "%wt": "%", "wt%": "%"}
FIX = {"AI2O3": "Al2O3"}


def norm(s):
    return re.sub(r"\s+", "", str(s)) if s is not None else ""


def parse_col(c, rock_units=None):
    """data column -> (analyte, unit, family) or None"""
    c = norm(c)
    if c.startswith("LOI"): return ("LOI", "%", "LOI")
    if c.startswith("pH") or c.startswith("Sample") or c.startswith(("Easting", "Northing", "X_ITM", "Y_ITM")): return None
    bld = c.endswith("_BLD")
    if bld: c = c[:-4]
    m = re.match(r"^([A-Za-z0-9]+)_(%|mgkg|.gkg)_(XRFS|ICPar|FA_ICPMS)$", c)
    if m:
        el, u, fam = m.groups()
        u = "ppb" if u.endswith("gkg") and u != "mgkg" else UNIT[u]
        return (FIX.get(el, el), u, "BLD" if bld else fam)
    m = re.match(r"^([A-Za-z0-9]+)_(XRFS|INAA|AAS)$", c)  # SE Ireland rocks
    if m and rock_units is not None:
        el, fam = m.groups(); el = FIX.get(el, el)
        # Se_INAA has no row in the limits table; every trace element there is ppm (only Au/Ir ppb, Fe/Na %), so ppm
        u = "%" if fam == "XRFS" else rock_units.get((el, fam), "ppm")
        return (el, u, "R_" + fam)
    return None


def dl_tables(ws):
    """column name -> list of (lld, url, hdl) from a Units_Detection_Limits sheet (three layouts)."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    out = collections.defaultdict(list)
    num = lambda v: float(v) if isinstance(v, (int, float)) else None
    # transposed layout: a header row starting 'Sample_ID', then rows labelled LLD / URL / HDL
    for i, r in enumerate(rows):
        if r and norm(r[0]) == "Sample_ID":
            lab = {}
            for r2 in rows[i + 1:]:
                k = norm(r2[0]).upper() if r2 and r2[0] else ""
                # labels start with the quantity; footnote rows such as '<LLD replaced with HDL (0.5*LLD)' must not match
                if k.startswith("HDL"): lab["hdl"] = r2
                elif k.startswith(("LLD", "WORKINGLLD")): lab["lld"] = r2
                elif k.startswith("URL"): lab["url"] = r2
            for j, name in enumerate(r):
                if j == 0 or not name: continue
                g = lambda key: num(lab[key][j]) if key in lab and j < len(lab[key]) else None
                if g("lld") or g("hdl"): out[norm(name)].append((g("lld"), g("url"), g("hdl"), None))
            return out
    # vertical layout: header rows with 'Analyte' cells followed by LLD / URL / HDL (/100) columns
    hdr, scope = None, None
    for r in rows:
        cells = [norm(x) for x in r]
        if "Analyte" in cells:
            hdr = cells
            # a section label such as 'ICPar (58xxxxA; SGS_Lab_No)' or 'ICPar (61xxxxA-65xxxxA; ALS_OMAC_Lab_No)' limits the table to those sample IDs
            m = re.search(r"\((\d\d)xxxx\w?(?:-(\d\d)xxxx\w?)?;", cells[0])
            scope = tuple(str(x) for x in range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1)) if m else None
            continue
        if not hdr: continue
        for p, h in enumerate(hdr):
            if h != "Analyte" or p >= len(cells) or not cells[p]: continue
            q = {}
            for k in range(p + 1, min(len(hdr), p + 5)):
                if hdr[k] == "Analyte": break
                key = hdr[k].upper().split("/")[0]
                if key in ("LLD", "URL", "HDL") and key not in q: q[key] = num(r[k]) if k < len(r) else None
            name = cells[p]
            name = {"pH": "pH_CaCl2", "LOI": "LOI_450C_%"}.get(name, name)
            if q.get("LLD") or q.get("HDL"):
                lld = q.get("LLD"); hdl = q.get("HDL") if q.get("HDL") is not None else (lld / 2 if lld else None)
                out[name].append((lld, q.get("URL"), hdl, scope))
    return out


def rock_tables(ws):
    """SE Ireland rocks: 'Element' / 'Method' / 'Units' / 'LLD' / 'HDL' row blocks -> (units by (el, fam), dl by column)"""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    units, dls = {}, collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r and r[0] == "Element":
            els, meth, un, lld, hdl = r, rows[i + 1], rows[i + 2], rows[i + 3], rows[i + 4]
            for j in range(1, len(els)):
                if not els[j]: continue
                u = {"ppm": "ppm", "ppb": "ppb", "%wt": "%"}[norm(un[j])]
                units[(els[j], meth[j])] = u
                dls[f"{els[j]}_{meth[j]}"].append((float(lld[j]), None, float(hdl[j]), None))
    return units, dls


tr_itm = Transformer.from_crs(2157, 4326, always_xy=True)
tr_ing = Transformer.from_crs(29903, 4326, always_xy=True)
stats = collections.Counter()
samples = {SRC_GSI: {}, SRC_NI: {}}
results = {SRC_GSI: [], SRC_NI: []}
dl_used = collections.Counter()
ING_CHECK = []


def eq(a, b):
    return b is not None and abs(a - b) <= 1e-6 * max(abs(b), 1e-12)


def add_gsi(path, stype, local, fraction, ctx_note, rock=False):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    title = os.path.basename(path).replace(".xlsx", "")
    data_ws = [w for w in wb.worksheets if w.title not in ("Units_Detection_Limits", "Read_Me", "Data_Below_LLD", "Conditioned_pH_Data")][0]
    rock_units = None
    if rock:
        rock_units, dls = rock_tables(wb["Units_Detection_Limits"])
    else:
        dls = dl_tables(wb["Units_Detection_Limits"])
    readme = {}
    if "Read_Me" in wb.sheetnames:
        for r in wb["Read_Me"].iter_rows(values_only=True):
            if r and r[0] and len(r) > 1 and r[1]: readme[norm(r[0])] = str(r[1]).strip()
    doc = readme.get("Supportingdocumentation", "")
    sheets = [(data_ws, False)] + ([(wb["Data_Below_LLD"], True)] if "Data_Below_LLD" in wb.sheetnames else [])
    for ws, is_bld in sheets:
        it = ws.iter_rows(values_only=True)
        hdr = [norm(h) for h in next(it)]
        idx = {h: i for i, h in enumerate(hdr) if h}
        cols = [(i, h, parse_col(h + ("_BLD" if is_bld and not h.endswith("_BLD") else ""), rock_units)) for i, h in enumerate(hdr) if h]
        cols = [(i, h, p) for i, h, p in cols if p]
        for r in it:
            sid = r[0]
            if sid is None or (rock and not isinstance(sid, (int, float))): continue
            sid = str(int(sid)) if isinstance(sid, float) else str(sid).strip()
            if not is_bld:
                e = r[idx["Easting_ITM"]] if "Easting_ITM" in idx else (r[idx["X_ITM"]] if "X_ITM" in idx else None)
                n = r[idx["Northing_ITM"]] if "Northing_ITM" in idx else (r[idx["Y_ITM"]] if "Y_ITM" in idx else None)
                if e and n:
                    lon, lat = tr_itm.transform(float(e), float(n))
                    ei, ni = (r[idx["Easting_ING"]], r[idx["Northing_ING"]]) if "Easting_ING" in idx else (r[idx["Easting"]], r[idx["Northing"]]) if "Easting" in idx else (None, None)
                    if ei and ni and len(ING_CHECK) < 3000:
                        lo2, la2 = tr_ing.transform(float(ei), float(ni)); ING_CHECK.append(((lo2 - lon) * 70000, (la2 - lat) * 111000))
                else:
                    lon, lat = tr_ing.transform(float(r[idx["Easting_ING"]]), float(r[idx["Northing_ING"]]))
                assert 51 < lat < 55.6 and -11 < lon < -5.3, (sid, lat, lon)
                if sid in samples[SRC_GSI]:
                    stats["duplicate sample id across files (kept first)"] += 1; continue
                note = "; ".join(x for x in [f"GSI Tellus {title}", ctx_note, doc] if x)
                if rock:
                    lith = r[idx["Lithological Group"]] if "Lithological Group" in idx else None
                    unit = r[idx["UnitName_100K"]] if "UnitName_100K" in idx else None
                    refs = [r[idx[k]] for k in ("Reference 1", "Reference 2") if k in idx and r[idx[k]]]
                    note = "; ".join(str(x) for x in [note, f"lithological group {lith}" if lith else "", f"unit {unit}" if unit else "",
                                                       ("references: " + " | ".join(map(str, refs)))[:400] if refs else ""] if x)
                samples[SRC_GSI][sid] = [sid, stype, local, lat, lon, sid, sid, note[:1000], "SURFACE", None]
                stats[f"GSI samples {stype}"] += 1
            elif sid not in samples[SRC_GSI] or samples[SRC_GSI][sid][9] == "dup":
                continue
            for i, h, (el, unit, fam) in cols:
                v = r[i] if i < len(r) else None
                if v is None or isinstance(v, str): continue
                v = float(v)
                if v <= 0: stats["zero or negative"] += 1; continue
                key = h[:-4] if h.endswith("_BLD") else h
                entries = dls.get(key + "_BLD", []) if is_bld else dls.get(h, [])
                st, dl, ul, cmt = "D", None, None, None
                entries = [e for e in entries if e[3] is None or sid[:2] in e[3]]
                for lld, url, hdl, _ in entries:
                    if hdl is not None and eq(v, hdl):
                        st, dl, cmt = "B", lld, f"value = half the published LLD {lld:g} {unit}: GSI replaced '<LLD' by 0.5 x LLD"
                        break
                    if url is not None and eq(v, url):
                        st, ul, cmt = "A", url, f"value = the published upper limit {url:g} {unit}: GSI replaced '>URL' by the URL"
                        break
                if not entries: dl_used[("BLD " if is_bld else "") + "no DL entry: " + h] += 1
                pkg = FAM_PKG[fam]
                results[SRC_GSI].append([sid, pkg, el, unit, v, dl, ul, cmt, fraction, st])
                stats[f"GSI results {st}"] += 1


def add_gsni(shp, stype, local, pkg_of):
    d = gpd.read_file(shp)
    d = d[d.DATASOURCE.str.contains("Northern", na=False)]
    vcols = [c for c in d.columns if re.search(r"_(MGKG|PCT)$", c)]
    out = []
    for c in vcols:
        base, u = c.rsplit("_", 1)
        out.append((c, base, "%" if u == "PCT" else "ppm"))
    # inferred censoring: column minimum making up >= 1% of the rows
    cens = {}
    for c, _, _ in out:
        s = d[c][d[c] > 0]
        if len(s):
            mn = s.min(); share = (s == mn).mean()
            if share >= 0.01: cens[c] = mn
    for _, r in d.iterrows():
        sid = str(r.SAMPLE_ID).strip()
        lon, lat = tr_itm.transform(float(r.geometry.x), float(r.geometry.y))
        assert 53.9 < lat < 55.5 and -8.3 < lon < -5.3, (sid, lat, lon)
        if sid not in samples[SRC_NI]:
            samples[SRC_NI][sid] = [sid, stype, local, lat, lon, sid, sid,
                                    f"GSNI Tellus Northern Ireland regional soils (2004-2006), dataset {r.DATASET}; released in the GSI/GSNI all-island layers (IE32)",
                                    "SURFACE", None]
            stats[f"NI samples {stype}"] += 1
        for c, base, unit in out:
            v = r[c]
            if v is None or v != v: continue
            v = float(v)
            if v <= 0: stats["NI zero or negative"] += 1; continue
            el = ANALYTE_CI.get(base.upper())
            if not el: stats["NI unknown analyte " + base] += 1; continue
            st, dl, cmt = "D", None, None
            if c in cens and eq(v, cens[c]):
                st, dl, cmt = "B", 2 * v, f"value = the column minimum {v:g} {unit}, frequent: probably half an unpublished detection limit (GSNI release censored to HDL)"
            results[SRC_NI].append([sid, pkg_of(base), el, unit, v, dl, None, cmt, "<2 mm", st])
            stats[f"NI results {st}"] += 1


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"],
                     password=ENV["LITHODAT_DB_PASSWORD"], keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)
c = g.cursor()
c.execute("SELECT analyte_code FROM geochem.analytes")
ANALYTE_CI = {a.upper(): a for (a,) in c.fetchall()}
g.rollback()

F = lambda pat: glob.glob(X + "**/" + pat, recursive=True)[0]
SOIL_A = ("SOIL_A", "Tellus shallow topsoil (5-20 cm)", "<2 mm")
SOIL_S = ("SOIL_B", "Tellus deeper topsoil (35-50 cm, nominally B horizon)", "<2 mm")
add_gsi(F("58xxxxA-65xxxxA_Shallow_Topsoil_Download_v1.2.xlsx"), *SOIL_A, "Tellus Border, West, Dublin/Galway peri-urban surveys (shallow topsoil)")
add_gsi(F("6117xxA-6174xxA_Shallow_Topsoil_Download_v1.1.xlsx"), *SOIL_A, "Tellus North Midlands (G5) shallow topsoil")
add_gsi(F("IE_GSI_Geochemistry_Shallow_Topsoil_A_G7_G9_South_East_ITM_6175xxA-6307xxA_Download_v1.0.xlsx"), *SOIL_A, "Tellus South-East (G7/G9) shallow topsoil")
add_gsi(F("IE_GSI_Geochemistry_Shallow_Topsoil_A_ICPar_G8_Dublin_ITM_670xxxA-671xxxA_Download_v1.0.xlsx"), *SOIL_A, "Tellus Dublin (G8) shallow topsoil")
add_gsi(F("58xxxxS-65xxxxS_Deeper_Topsoil_Download_v2_2.xlsx"), *SOIL_S, "Tellus Border, West, Dublin/Galway peri-urban surveys (deeper topsoil)")
add_gsi(F("6117xxS-6174xxS_Deeper_Topsoil_Download.xlsx"), *SOIL_S, "Tellus North Midlands (G5) deeper topsoil")
add_gsi(F("IE_GSI_Geochemistry_Deeper_Topsoil_S_ICPar_G8_Dublin_ITM_670xxxS-671xxxS_Download_v1.0.xlsx"), *SOIL_S, "Tellus Dublin (G8) deeper topsoil")
add_gsi(F("58xxxxC-60xxxxC_Stream_Sediment_Download_v1.1.xlsx"), "SED_STREAM", "Tellus low-order stream sediment", "<150 um", "Tellus stream sediment survey")
add_gsi(F("Lithochem_SEIreland_Final_publication_v1_20210127.xlsx"), "ROCK_SAMPLE", "SE Ireland lithogeochemistry (compiled rock analyses)", None,
        "GSI SE Ireland lithogeochemistry compilation 2021", rock=True)
NI_AR = lambda b: "GSNI_TELLUS_AR"
add_gsni(F("IE_GSI_GSNI_Geochemistry_Shallow_Topsoil_A_ICPar_Sample_IE32_ITM.shp"), "SOIL_A", "Tellus NI shallow topsoil (5-20 cm)", NI_AR)
add_gsni(F("IE_GSI_GSNI_Geochemistry_Shallow_Topsoil_A_XRFS_Sample_IE32_ITM.shp"), "SOIL_A", "Tellus NI shallow topsoil (5-20 cm)", lambda b: "GSNI_TELLUS_XRFS")
add_gsni(F("IE_GSI_GSNI_Geochemistry_Shallow_Topsoil_A_pH_LOI_Sample_IE32_ITM.shp"), "SOIL_A", "Tellus NI shallow topsoil (5-20 cm)", lambda b: "GSNI_TELLUS_LOI")
add_gsni(F("IE_GSI_GSNI_Geochemistry_Deeper_Topsoil_S_ICPar_Sample_IE32_ITM.shp"), "SOIL_B", "Tellus NI deeper topsoil (35-50 cm, nominally B horizon)", NI_AR)
if ING_CHECK:
    dx = sorted(abs(a) for a, b in ING_CHECK); dy = sorted(abs(b) for a, b in ING_CHECK)
    log("Irish Grid vs ITM check (m, median/max):", round(dx[len(dx) // 2], 1), round(dx[-1], 1), round(dy[len(dy) // 2], 1), round(dy[-1], 1))
log("staged", {k: len(v) for k, v in samples.items()}, {k: len(v) for k, v in results.items()})
log(dict(stats))
if dl_used: log("columns without a DL entry:", dict(dl_used))
# analytes that would fail
for s in (SRC_GSI, SRC_NI):
    miss = sorted({r[2] for r in results[s]} - set(ANALYTE_CI.values()))
    assert not miss, (s, "unknown analytes", miss)

c.execute("SET statement_timeout = 0")
for s in (SRC_GSI, SRC_NI):
    c.execute("SELECT count(*) FROM geochem.samples WHERE source_system = %s", (s,))
    assert c.fetchone()[0] == 0, s + " already has samples: delete them by created_by first"
if not CHECK:
    g.commit(); g.autocommit = True
    for s in (SRC_GSI, SRC_NI):
        for t in ("analytical_results", "result_classifications"):
            g.cursor().execute(f"CREATE TABLE IF NOT EXISTS geochem.{t}_{PART[s]} PARTITION OF geochem.{t} FOR VALUES IN ('{s}')")
    g.autocommit = False
    c = g.cursor(); c.execute("SET statement_timeout = 0")

for pk, (name, mcode, lab, basis, prio, desc) in PKGS.items():
    c.execute("""INSERT INTO geochem.analytical_packages (package_code, package_name, lab_id, method_id, description, is_active, created_by, created_date)
                 VALUES (%s,%s,(SELECT lab_id FROM geochem.laboratories WHERE lab_code = %s),(SELECT method_id FROM geochem.analytical_methods WHERE method_code = %s),
                 %s,true,%s,now()) ON CONFLICT (package_code) DO NOTHING""", (pk, name, lab, mcode, desc, TAG))
    c.execute("""INSERT INTO geochem.package_wide_rules (package_id, basis, priority, note)
                 SELECT package_id, %s, %s, 'Tellus Ireland' FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""", (basis, prio, pk))
    src = SRC_NI if pk.startswith("GSNI") else SRC_GSI
    c.execute("""INSERT INTO geochem.source_package_rules (source_system, package_id, basis, priority, note)
                 SELECT %s, package_id, %s, %s, %s FROM geochem.analytical_packages WHERE package_code = %s
                 ON CONFLICT (source_system, package_id) DO UPDATE SET basis = excluded.basis, priority = excluded.priority, note = excluded.note""",
              (src, basis, prio, "Tellus Ireland " + TAG, pk))


def copy(table, cols_sql, data):
    c.execute(f"DROP TABLE IF EXISTS {table}")
    c.execute(f"CREATE TEMP TABLE {table} ({cols_sql})")
    buf = io.StringIO(); wr = csv.writer(buf)
    for r in data:
        wr.writerow([N if x is None or x == "" else x for x in r])
    buf.seek(0)
    c.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


for SRC in (SRC_GSI, SRC_NI):
    copy("st_sample", "k text, stype text, stype_local text, lat float8, lon float8, field_no text, sample_no text, comments text, ctx text, sdate date", samples[SRC].values())
    copy("st_result", "k text, pkg text, analyte text, unit text, val numeric, dl numeric, ul numeric, comment text, fraction text, st text", results[SRC])
    for label, sql in [("unit", "SELECT DISTINCT r.unit FROM st_result r LEFT JOIN geochem.units u ON u.unit_code = r.unit WHERE u.unit_id IS NULL"),
                       ("package", "SELECT DISTINCT r.pkg FROM st_result r LEFT JOIN geochem.analytical_packages p ON p.package_code = r.pkg WHERE p.package_id IS NULL"),
                       ("sample type", "SELECT DISTINCT s.stype FROM st_sample s LEFT JOIN geochem.sample_types t ON t.sample_type_code = s.stype WHERE t.sample_type_id IS NULL")]:
        c.execute(sql); miss = [r[0] for r in c.fetchall()]
        assert not miss, (SRC, label, miss)
    c.execute("DROP TABLE IF EXISTS st_map")
    c.execute("""CREATE TEMP TABLE st_map AS SELECT s.k, nextval('geochem.samples_sample_id_seq') AS sample_id FROM st_sample s
                 WHERE EXISTS (SELECT 1 FROM st_result r WHERE r.k = s.k)""")
    c.execute(f"""
    INSERT INTO geochem.samples (sample_id, geom, field_id, sample_number, sample_type_id, sample_type_local, sample_context, comments, sample_date, is_active,
      created_by, created_date, source_system)
    OVERRIDING SYSTEM VALUE
    SELECT m.sample_id, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.field_no, s.sample_no, t.sample_type_id, s.stype_local, s.ctx, s.comments, s.sdate, true,
      '{TAG}', now(), '{SRC}'
    FROM st_sample s JOIN st_map m USING (k) JOIN geochem.sample_types t ON t.sample_type_code = s.stype""")
    log(SRC, "samples inserted", c.rowcount, "| without results", len(samples[SRC]) - c.rowcount)
    c.execute(f"""INSERT INTO core.external_ids (entity_type, entity_id, source_system, source_id, created_by, created_date)
                  SELECT 'SAMPLE', sample_id, '{XID[SRC]}', k, '{TAG}', now() FROM st_map""")
    if CHECK:
        c.execute("SELECT pkg, st, count(*) FROM st_result GROUP BY 1, 2 ORDER BY 1, 2"); log(SRC, "per package/status", c.fetchall())
        continue
    c.execute(f"""
    INSERT INTO geochem.analytical_results (sample_id, occurrence_id, source_system, package_id, analyte_id, analyte_name, analyte_symbol,
      unit_id, unit_code, qualifier_id, qualifier_code, laboratory, method_code, method_name, digest_name,
      value, lower_detection_limit, upper_detection_limit, report_number, date_analysed, reviewed, is_active, created_by, created_date,
      source_result_id, fraction, result_comment)
    SELECT m.sample_id, NULL, '{SRC}', p.package_id, a.analyte_id, a.analyte_name, a.element_symbol, u.unit_id, u.unit_code, NULL, NULL,
      {"'Geological Survey Ireland - Tellus (SGS / ALS-OMAC)'" if SRC == SRC_GSI else "'GSNI Tellus Northern Ireland (laboratory not recorded)'"},
      meth.method_code, p.package_name, meth.digest_name, r.val, r.dl, r.ul, NULL, NULL, false, true, '{TAG}', now(),
      r.st, r.fraction, r.comment
    FROM st_result r
    JOIN st_map m ON m.k = r.k
    JOIN geochem.analytes a ON a.analyte_code = r.analyte
    JOIN geochem.units u ON u.unit_code = r.unit
    JOIN geochem.analytical_packages p ON p.package_code = r.pkg
    LEFT JOIN geochem.analytical_methods meth ON meth.method_id = p.method_id""")
    nins = c.rowcount
    log(SRC, "results inserted", nins, "of", len(results[SRC]))
    assert nins == len(results[SRC])
    c.execute(f"""
    INSERT INTO geochem.result_classifications (result_id, source_system, result_status, dl_value, dl_source, use_in_statistics)
    SELECT r.result_id, r.source_system,
      CASE r.source_result_id WHEN 'B' THEN 'BELOW_DL_PROBABLE' WHEN 'A' THEN 'ABOVE_UDL' ELSE 'DETECTED' END,
      CASE WHEN r.source_result_id = 'B' THEN r.lower_detection_limit END,
      CASE WHEN r.source_result_id = 'B' THEN {"'GSI_PUBLISHED_LLD'" if SRC == SRC_GSI else "'INFERRED_2X_FREQUENT_MIN'"} END,
      r.source_result_id = 'D'
    FROM geochem.analytical_results_{PART[SRC]} r""")
    log(SRC, "classified", c.rowcount)
    c.execute(f"UPDATE geochem.analytical_results_{PART[SRC]} SET source_result_id = NULL")
    c.execute("""INSERT INTO geochem.classification_batches (source_system, classified_by, first_classified_at, last_classified_at, n_rows, note)
     VALUES (%s, %s, now(), now(), %s, %s)
     ON CONFLICT (source_system, classified_by) DO UPDATE SET last_classified_at = now(), n_rows = excluded.n_rows""",
              (SRC, "rule_" + TAG, nins, "GSI: value = published HDL (0.5 x LLD) -> BELOW_DL_PROBABLE, = URL -> ABOVE_UDL" if SRC == SRC_GSI
               else "GSNI: frequent column minimum (>=1%) -> BELOW_DL_PROBABLE, dl = 2 x value"))

if CHECK:
    g.rollback(); g.close(); log("CHECK RUN - rolled back"); sys.exit(0)

for src, pub, name, lic, url, attr, status, cav in [
        (SRC_GSI, "Geological Survey Ireland (GSI) - Tellus programme",
         "Tellus geochemistry of Ireland: shallow and deeper topsoil (pH/LOI, XRFS, aqua regia ICP), stream sediment (XRFS, fire assay Au/Pd/Pt), SE Ireland lithogeochemistry",
         "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/",
         "Contains Irish Public Sector Data (Geological Survey Ireland) licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence.",
         "Cleared: GSI_Licence_CC_BY_40.txt shipped in the GSI downloads and the ISO metadata of the IE32/IE26 layers (CC BY 4.0, specific attribution statement). Checked 2026-11-15.",
         "<LLD values were replaced by GSI with half the LLD (flagged BELOW_DL_PROBABLE with the published LLD) and >URL by the URL (ABOVE_UDL); ICPar from two laboratories (SGS for the Border 58xxxx samples, ALS-OMAC otherwise) with different LLDs and no inter-laboratory levelling; XRFS correction factors on K2O, V, Co, Cu, Yb in topsoils; no sampling dates per sample (surveys 2011-2022); SE Ireland rocks are a compilation of published analyses. Stream water and pH not loaded."),
        (SRC_NI, "Geological Survey of Northern Ireland (GSNI) - Tellus Northern Ireland",
         "Tellus Northern Ireland regional soils (2004-2006): shallow topsoil aqua regia ICP, XRFS and LOI; deeper topsoil aqua regia ICP (from the GSI/GSNI all-island IE32 layers)",
         "UK Open Government Licence v3.0", "http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
         "Contains UK public sector information (Geological Survey of Northern Ireland) licensed under the UK Open Government Licence v3.0.",
         "Cleared: ISO metadata of the IE32 layers states GSNI data are free to use under the UK OGL v3.0 with the given attribution statement. Checked 2026-11-15.",
         "Values censored to half the detection limit, limits not published with the release: frequent column minima flagged BELOW_DL_PROBABLE with an inferred limit; laboratory not recorded; no sampling dates per sample (2004-2006).")]:
    c.execute("""INSERT INTO core.data_sources (source_system, publisher, dataset_name, licence, licence_url, attribution_required, attribution_text, is_loaded,
      licence_status, caveats, evidence_location, evidence_date, is_active, created_by, created_date)
     VALUES (%s, %s, %s, %s, %s, true, %s, true, %s, %s, %s, now(), true, %s, now()) ON CONFLICT (source_system) DO NOTHING""",
              (src, pub, name, lic, url, attr, status, cav, r"D:\CriticalMineralsDB\Documents\Licence_Evidence\TELLUS_IRELAND\ (licence text, metadata extract, EVIDENCE.md)", TAG))
for s in (SRC_GSI, SRC_NI):
    c.execute(f"""SELECT count(*) FROM geochem.samples s WHERE s.created_by = '{TAG}' AND s.source_system = '{s}'
                  AND NOT EXISTS (SELECT 1 FROM geochem.analytical_results r WHERE r.sample_id = s.sample_id AND r.source_system = '{s}')""")
    assert c.fetchone()[0] == 0
g.commit(); log("COMMITTED", TAG)
g.close()
