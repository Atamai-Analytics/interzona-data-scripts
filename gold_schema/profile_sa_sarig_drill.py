"""Full-file profile of the DRILL rows of the SARIG rock-sample chemistry export (sarig_rs_chem_exp.csv, July 2025, CC BY 4.0) for phase 2
sizing. Read-only; one streaming pass. Counts holes, interval samples, results, elements per sample, samples per hole, depth checks,
portable XRF and derived 'log data' rows, top elements / methods / collectors, and what a per-hole max-grade summary would hold.
Usage: python profile_sa_sarig_drill.py <path to sarig_rs_chem_exp.csv> [out_dir]
"""
import csv, os, sys, time, collections, statistics

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
t0 = time.time()


def log(*a):
    print(f"{time.time() - t0:6.0f}s", *a, flush=True)


def is_pxrf(m, d):
    m, d = (m or "").upper(), (d or "").upper()
    return any(x in m for x in ("NITON", "XRFDELTA", "PXRF", "DELTA")) or any(x in d for x in ("PORTABLE", "HANDHELD", "HAND HELD", "NITON", "OLYMPUS"))


f = open(SRC, encoding="utf-8", errors="replace", newline="")
r = csv.reader(f)
H = next(r); ix = {h: i for i, h in enumerate(H)}
I = {k: ix[k] for k in ("SAMPLE_NO", "SAMPLE_SOURCE", "DRILLHOLE_NUMBER", "DH_NAME", "DH_DEPTH_FROM", "DH_DEPTH_TO", "LONGITUDE_GDA2020",
                        "LATITUDE_GDA2020", "COLLECTED_BY", "COLLECTED_DATE", "CHEM_CODE", "VALUE", "UNIT", "CHEM_METHOD_CODE", "CHEM_METHOD_DESC")}
tot = collections.Counter(); src = collections.Counter(); chem = collections.Counter(); meth = collections.Counter(); unit = collections.Counter()
el_id = {}
samp = {}                       # sample_no -> [hole, from, to, element bitmask]
hole = {}                       # hole no -> [name, lon, lat, max_to, collector, min year, max year]
hole_coll = collections.Counter()
bad_ft = 0
for row in r:
    tot["rows"] += 1
    if tot["rows"] % 5_000_000 == 0: log(f"{tot['rows']:,} rows, drill lab {tot['drill lab rows']:,}, samples {len(samp):,}, holes {len(hole):,}")
    if len(row) != len(H): tot["malformed"] += 1; continue
    dh = row[I["DRILLHOLE_NUMBER"]]
    if not dh: continue
    tot["drill rows"] += 1
    if is_pxrf(row[I["CHEM_METHOD_CODE"]], row[I["CHEM_METHOD_DESC"]]): tot["drill pXRF rows"] += 1; continue
    ss = row[I["SAMPLE_SOURCE"]]
    if ss.startswith("Drillhole log data"): tot["drill derived log-data rows"] += 1; continue
    tot["drill lab rows"] += 1
    if row[I["VALUE"]].startswith("<"): tot["drill lab '<' rows"] += 1
    el = row[I["CHEM_CODE"]]
    b = el_id.setdefault(el, len(el_id))
    src[ss] += 1; chem[el] += 1; meth[row[I["CHEM_METHOD_CODE"]]] += 1; unit[row[I["UNIT"]]] += 1
    sn = row[I["SAMPLE_NO"]]
    s = samp.get(sn)
    if s is None:
        a, z = row[I["DH_DEPTH_FROM"]], row[I["DH_DEPTH_TO"]]
        try:
            fa, fz = float(a), float(z)
            if fz <= fa: bad_ft += 1
        except ValueError:
            fa = fz = None
        samp[sn] = s = [dh, fa, fz, 0]
        h = hole.get(dh)
        yr = row[I["COLLECTED_DATE"]][-4:]
        yr = int(yr) if yr.isdigit() else None
        if h is None:
            hole[dh] = h = [row[I["DH_NAME"]], row[I["LONGITUDE_GDA2020"]], row[I["LATITUDE_GDA2020"]], fz or 0, row[I["COLLECTED_BY"]], yr, yr]
            hole_coll[row[I["COLLECTED_BY"]]] += 1
        else:
            if fz and fz > h[3]: h[3] = fz
            if yr: h[5] = min(h[5] or yr, yr); h[6] = max(h[6] or yr, yr)
    s[3] |= 1 << b
log("pass done")

n = len(samp)
els = [bin(v[3]).count("1") for v in samp.values()]
per_hole = collections.Counter(v[0] for v in samp.values()); ph = sorted(per_hole.values())
ft = [v for v in samp.values() if v[1] is not None]
L = [v[2] - v[1] for v in ft if v[2] > v[1]]
depth = [h[3] for h in hole.values() if h[3]]
lt = tot["drill lab '<' rows"]
lines = [
    f"file rows {tot['rows']:,}; malformed {tot['malformed']:,}",
    f"drill rows {tot['drill rows']:,}: pXRF {tot['drill pXRF rows']:,}, derived log data {tot['drill derived log-data rows']:,}, LAB {tot['drill lab rows']:,} (below detection {lt:,})",
    f"holes {len(hole):,}; interval samples {n:,}; distinct elements {len(el_id)}",
    f"elements per sample: median {statistics.median(els)}, mean {statistics.mean(els):.1f}; 1 element {sum(e == 1 for e in els) / n:.0%}; >=10 {sum(e >= 10 for e in els) / n:.0%}; >=30 {sum(e >= 30 for e in els) / n:.0%}",
    f"samples per hole: median {statistics.median(ph)}, mean {statistics.mean(ph):.0f}, p90 {ph[int(len(ph) * .9)]}, p99 {ph[int(len(ph) * .99)]}, max {ph[-1]}",
    f"from+to present {len(ft) / n:.1%}; to<=from {bad_ft:,}; interval length median {statistics.median(L):.2f} m, p99 {sorted(L)[int(len(L) * .99)]:.1f} m",
    f"hole max sampled depth: median {statistics.median(depth):.0f} m, p90 {sorted(depth)[int(len(depth) * .9)]:.0f} m, max {max(depth):.0f} m",
    "",
]
he = collections.defaultdict(int)
for v in samp.values(): he[v[0]] |= v[3]
lines[-1] = f"per-hole max-grade summary rows (hole x element): {sum(bin(m).count('1') for m in he.values()):,}"
for name, c in [("sample source", src), ("element", chem), ("method", meth), ("unit", unit)]:
    t = sum(c.values()); lines.append(f"{name}: " + ", ".join(f"{k or '(blank)'} {v / t:.1%}" for k, v in c.most_common(20)))
t = sum(hole_coll.values()); lines.append("holes by collector: " + ", ".join(f"{k or '(blank)'} {v:,}" for k, v in hole_coll.most_common(20)))
yrs = collections.Counter((h[5] // 10 * 10) for h in hole.values() if h[5])
lines.append("holes by first sample decade: " + ", ".join(f"{k}s {v:,}" for k, v in sorted(yrs.items())))
out = os.path.join(OUT, f"sa_sarig_drill_profile_{time.strftime('%Y%m%d_%H%M')}.txt")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
for l in lines: print(l)
with open(os.path.join(OUT, "sa_sarig_drill_holes.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["drillhole_number", "dh_name", "lon", "lat", "max_sampled_depth_m", "collector", "first_year", "last_year", "lab_samples"])
    for k, h in hole.items(): w.writerow([k, *h, per_hole[k]])
log("written", out)
