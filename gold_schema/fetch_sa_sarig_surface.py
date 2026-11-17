"""Stream South Australia's SARIG rock-sample chemistry export (sarig_rs_chem_exp.csv, ~23.4 GB, CC BY 4.0, Government of South Australia)
straight from the public bucket and keep only SURFACE samples with LABORATORY assays (phase 1, user decision 2026-11-16).

Kept: rows with no drill hole whose SAMPLE_SOURCE is a surface medium (soil, calcrete, rock outcrop / float, channel, costean, stream and lake
sediment, gravel, lag, auger, vegetation). Dropped: drill samples (phase 2), mine stockpile / tailings / mullock / mine rock, standards, pulps,
blank source; and portable-XRF determinations (SARIG method codes for Niton, Olympus, Innov-X and the pXRF family - field readings, not lab
assays; the plain lab 'XRF' code is kept). The full file is never stored.
Output: D:/CriticalMineralsDB/Australia/SA_SARIG/sarig_surface_lab.csv (same columns) + a counts log.
Usage: python fetch_sa_sarig_surface.py [--local D:/CriticalMineralsDB/Australia/SA_SARIG/sarig_rs_chem_exp.csv]   (the local copy is deleted afterwards)
"""
import csv, io, sys, time, collections, urllib.request

URL = "https://dem-sdp.s3-ap-southeast-2.amazonaws.com/sarig_rs_chem_exp.csv"
OUT = "D:/CriticalMineralsDB/Australia/SA_SARIG/sarig_surface_lab.csv"
SURFACE = {"Soil", "Calcrete", "Rock outcrop / float", "Stream sediment", "Auger sample from near surface",
           "Channel (linear rock chip/outcrop sampling)", "Gravel", "Costean (trench)", "Lake floor sediment", "Vegetation",
           "Lag sample, surface sample consisting of gravelly material.", "Loam", "Magnetic lag fraction",
           "Sample specifically for bulk leach extractable gold analysis", "Rock outcrop sample", "Rock float sample (not in situ)",
           "Rock subcrop sample (in situ, not attached to bedrock)"}
PXRF = {"P-XRF", "XRFInnovX", "XRFNiton", "XRFOlympus", "pXRF", "pXRF-30", "pXRF-30NDL", "pXRF-30RT", "pXRF-34", "pXRF-NQ", "pXRF-corr", "pXRF34"}
csv.field_size_limit(10_000_000)
t0 = time.time()
kept, seen = collections.Counter(), collections.Counter()
nrows = 0
LOCAL = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None   # a full local copy (the stream over one connection was reset by the server)
if LOCAL:
    src_file = open(LOCAL, encoding="utf-8", errors="replace", newline="", buffering=8 * 1024 * 1024)
else:
    resp = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "geodata-loader"}), timeout=120)
    src_file = io.TextIOWrapper(io.BufferedReader(resp, buffer_size=8 * 1024 * 1024), encoding="utf-8", errors="replace", newline="")
with src_file, open(OUT, "w", newline="", encoding="utf-8") as out:
    rd = csv.reader(src_file)
    hdr = next(rd)
    ix = {c: i for i, c in enumerate(hdr)}
    w = csv.writer(out); w.writerow(hdr)
    SRC, DH, METH = ix["SAMPLE_SOURCE"], ix["DRILLHOLE_NUMBER"], ix["CHEM_METHOD_CODE"]
    for r in rd:
        nrows += 1
        src = r[SRC]
        if r[DH].strip():
            seen["drill (phase 2)"] += 1
        elif src not in SURFACE:
            seen["other source: " + (src or "(blank)")] += 1
        elif r[METH] in PXRF:
            seen["portable XRF: " + src] += 1
        else:
            w.writerow(r); kept[src] += 1
        if nrows % 5_000_000 == 0:
            print(f"{time.time() - t0:6.0f}s rows {nrows:,} kept {sum(kept.values()):,}", flush=True)
print(f"done in {time.time() - t0:.0f}s; rows {nrows:,}; kept {sum(kept.values()):,}")
print("kept by source", dict(kept.most_common()))
print("dropped", dict(seen.most_common(40)))
