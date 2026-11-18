"""SA SARIG phase 2: extract the DRILL-HOLE laboratory assays from the full SARIG rock-sample chemistry export (sarig_rs_chem_exp.csv, July 2025,
CC BY 4.0) into load-ready files for load_sa_sarig_drill.py. Read-only on the database (only reads the analyte list).

Kept: rows with a DRILLHOLE_NUMBER. Left out: portable / in-house XRF (same codes as phase 1, plus any XRF method reported by an in-house lab),
CALC values, SARIG 'Drillhole log data - used in calculating values' (derived), QC material (duplicates, analytical standards), smelter slag,
analyte codes and units left out in phase 1 (sa_sarig_common). Values parsed as in phase 1 ('<x' below detection, '>x' above, zero dropped).
One sample per SARIG SAMPLE_NO (a downhole interval: DH_DEPTH_FROM - DH_DEPTH_TO); holes keyed by DRILLHOLE_NUMBER.
Outputs (in OUT): sa_drill_results.csv, sa_drill_samples.csv, sa_drill_holes.csv, sa_drill_packages.csv, sa_drill_extract.log
Usage: python extract_sa_sarig_drill.py <sarig_rs_chem_exp.csv> <out_dir>
"""
import csv, os, sys, time, datetime, collections
import psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # run with python -P, which leaves the script folder off the path
from sa_sarig_common import ANALYTE, SKIP_CODE, UNIT, PXRF, family, parse_value

SRCF, OUT = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
MD = "D:/CriticalMineralsDB/Australia/SA_SARIG/_slices/chem_method_code_desc.csv"
ENV = {}
for l in open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
N = "\\N"
t0 = time.time()
logf = open(os.path.join(OUT, "sa_drill_extract.log"), "w", encoding="utf-8")


def log(*a):
    s = f"{time.time() - t0:6.0f}s " + " ".join(str(x) for x in a)
    print(s, flush=True); logf.write(s + "\n"); logf.flush()


g = psycopg2.connect(host=ENV["LITHODAT_DB_HOST"], port=ENV["LITHODAT_DB_PORT"], dbname="interzona_cm", user=ENV["LITHODAT_DB_USER"], password=ENV["LITHODAT_DB_PASSWORD"])
c = g.cursor(); c.execute("SELECT analyte_code FROM geochem.analytes"); known = {r[0] for r in c.fetchall()}; g.close()
MDX, MDC = {}, {}
for r in csv.DictReader(open(MD, encoding="utf-8")):
    v = (r["CHEM_METHOD_DESC"], r["DIGESTION_DESC"], r["DETERMINATION_DESC"])
    MDX[(r["LABORATORY_NAME"].strip(), r["CHEM_METHOD"].strip())] = v; MDC.setdefault(r["CHEM_METHOD"].strip(), v)

STYPE = {"Drill cuttings": "CHIPS_SAMPLE", "Drill core": "CORE_SAMPLE", "Sawn half drill core": "CORE_HALF", "Sawn quarter drill core": "CORE_QUARTER",
         "A full face slice of core": "CORE_WHOLE", "Filleted, shaved or ground core sample": "CORE_SAMPLE", "Core sludge": "CHIPS_SAMPLE",
         "Aircore: consolidated sample from aircore drilling method": "CORE_AIRCORE", "Auger sample from near surface": "CHIPS_AUGER",
         "Drilled interval rock sample, type unspecified": "DRILL_SAMPLE", "Composite drill samples": "DRILL_SAMPLE",
         "Pulp / powdered rock of known origin, typically a lab return": "DRILL_SAMPLE"}
DROP_SRC = ("Drillhole log data", "Duplicate:", "Analytical standard", "Smelter slag")


def date(s):
    try:
        d = datetime.datetime.strptime(s.strip(), "%d/%m/%Y").date()
        return d.isoformat() if 1900 < d.year <= 2026 else None
    except ValueError:
        return None


def fnum(s):
    try:
        return float(s)
    except ValueError:
        return None


stats = collections.Counter(); pk_n = collections.Counter(); pkgs = {}
samples = {}       # SAMPLE_NO -> row for sa_drill_samples.csv
holes = {}         # DRILLHOLE_NUMBER -> [name, lat, lon, collector, first date, last date, max to]
fr = open(SRCF, encoding="utf-8", errors="replace", newline="", buffering=16 * 1024 * 1024)
rd = csv.reader(fr); H = next(rd); ix = {h: i for i, h in enumerate(H)}
I = lambda k: ix[k]
iSN, iSS, iDH, iDN, iFR, iTO, iLAT, iLON, iCB, iCN, iCD, iLAB, iCC, iV, iU, iM, iMD = (I(k) for k in (
    "SAMPLE_NO", "SAMPLE_SOURCE", "DRILLHOLE_NUMBER", "DH_NAME", "DH_DEPTH_FROM", "DH_DEPTH_TO", "LATITUDE_GDA2020", "LONGITUDE_GDA2020", "COLLECTED_BY",
    "COLLECTORS_NUMBER", "COLLECTED_DATE", "LABORATORY", "CHEM_CODE", "VALUE", "UNIT", "CHEM_METHOD_CODE", "CHEM_METHOD_DESC"))
iLN, iLM, iRG, iST = I("LITHOLOGY_NAME"), I("LITHOLOGY_MODIFIER"), I("ROCK_GROUP"), I("STRAT_NAME")
nres = 0
with open(os.path.join(OUT, "sa_drill_results.csv"), "w", newline="", encoding="utf-8", buffering=16 * 1024 * 1024) as out:
    w = csv.writer(out)
    for r in rd:
        stats["rows"] += 1
        if stats["rows"] % 5_000_000 == 0: log(f"rows {stats['rows']:,} results {nres:,} samples {len(samples):,} holes {len(holes):,}")
        if len(r) != len(H): stats["malformed row"] += 1; continue
        dh = r[iDH].strip()
        if not dh: continue
        stats["drill rows"] += 1
        src = r[iSS]
        if src.startswith(DROP_SRC): stats["left out: " + src[:40]] += 1; continue
        lab, meth = r[iLAB].strip(), r[iM].strip()
        if meth in PXRF or ("in-house" in lab.lower() and "xrf" in meth.lower()): stats["left out: portable / in-house XRF"] += 1; continue
        if meth == "CALC": stats["left out: calculated"] += 1; continue
        code = ANALYTE.get(r[iCC].strip(), r[iCC].strip())
        if code in SKIP_CODE or code not in known: stats["left out: analyte " + code] += 1; continue
        u = UNIT.get(r[iU].strip())
        if u is None: stats["left out: unit " + r[iU].strip()] += 1; continue
        pv = parse_value(r[iV], code, u[1])
        if isinstance(pv, str): stats["left out: " + pv] += 1; continue
        q, val, ldl, udl, st = pv
        k = r[iSN].strip()
        if k not in samples:
            lat, lon = fnum(r[iLAT]), fnum(r[iLON])
            if lat is None or lon is None: stats["left out: no position"] += 1; continue
            fa, fz = fnum(r[iFR]), fnum(r[iTO])
            stype = STYPE.get(src, "DRILL_SAMPLE")
            hn = r[iDN].strip()
            note = "; ".join(x for x in [
                f"SARIG sample {k}", f"drill hole {hn or dh} (SARIG drillhole no. {dh})",
                f"interval {r[iFR]}-{r[iTO]} m" if r[iFR] or r[iTO] else "", f"source: {src}" if src else "",
                f"collected by {r[iCB]}" if r[iCB] else "", f"collector no. {r[iCN]}" if r[iCN] else "",
                f"lithology {r[iLN]}{' ' + r[iLM] if r[iLM] else ''}" if r[iLN] else "", f"rock group {r[iRG]}" if r[iRG] else "",
                f"stratigraphy {r[iST]}" if r[iST] else ""] if x)
            sd = date(r[iCD])
            samples[k] = (k, stype, f"SARIG {src.lower()}"[:100] if src else "SARIG drill sample", lat, lon, r[iCN] or None, note[:1000], sd, dh,
                          fa, fz)
            stats["samples " + stype] += 1
            h = holes.get(dh)
            if h is None:
                holes[dh] = [hn or None, lat, lon, r[iCB] or None, sd, sd, fz or 0]
            else:
                if fz and fz > h[6]: h[6] = fz
                if sd and (h[4] is None or sd < h[4]): h[4] = sd
                if sd and (h[5] is None or sd > h[5]): h[5] = sd
        desc = MDX.get((lab, meth)) or MDC.get(meth) or (r[iMD], "", "")
        d, e = family(meth, *desc)
        pk = f"SA-{d}-{e}"
        pkgs.setdefault(pk, (d, e)); pk_n[pk] += 1
        w.writerow([k, pk, code, u[0], q or N, val, N if ldl is None else ldl, N if udl is None else udl, lab[:100] or "Not recorded",
                    f"SARIG method {meth}: {desc[0][:150]}", st])
        nres += 1
log(f"pass done: rows {stats['rows']:,}, results {nres:,}, samples {len(samples):,}, holes {len(holes):,}")
with open(os.path.join(OUT, "sa_drill_samples.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for s in samples.values(): w.writerow([N if x is None or x == "" else x for x in s])
with open(os.path.join(OUT, "sa_drill_holes.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for dh, h in holes.items(): w.writerow([dh] + [N if x is None or x == "" else x for x in h])
with open(os.path.join(OUT, "sa_drill_packages.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for pk, (d, e) in pkgs.items(): w.writerow([pk, d, e, pk_n[pk]])
for k in sorted(stats): log(f"  {k}: {stats[k]:,}")
for pk, n in pk_n.most_common(): log(f"  package {pk}: {n:,}")
log("DONE")
