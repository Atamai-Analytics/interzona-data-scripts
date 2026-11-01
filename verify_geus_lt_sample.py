#!/usr/bin/env python3
"""Independent read-only check of the GEUS '<' concentration update on a random sample of aliquots (+ Stream Sediment spot check)."""
import collections, csv, json, os, random, sys, urllib.parse
from pathlib import Path
import update_finland_sample_weight as base
import fix_geus_lt_concentration as fx

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
random.seed(20261016)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
info = fx.plan()
dpsets = {p: set(json.load(open(HERE / f"datapoint_ids_{p}.json")).values()) for p in fx.PACKAGES}
sample = random.sample(sorted(info), 400)
bad = collections.Counter()
seen = collections.Counter()
for i in range(0, len(sample), 20):
    names = sample[i:i + 20]
    for kind in ("elem", "oxide"):
        if not any(info[a][kind] for a in names):
            continue
        namef = fx.KINDS[kind][1]
        by = collections.defaultdict(list)
        for e in fx.fetch(kind, names):
            by[e["aliquotName"]].append(e)
        for a in names:
            exp = info[a][kind]
            if not exp:
                continue
            lt = [e for e in by.get(a, []) if e["gcdataPointId"] in dpsets[info[a]["pkg"]] and e["relativeOperatorId"] == 1]
            got = collections.Counter((e[namef], round(float(e["detectionLimit"]), 9)) for e in lt if e["detectionLimit"] is not None)
            seen[kind] += len(lt)
            if got != exp:
                bad["multiset_mismatch"] += 1
            bad["lt_without_concentration"] += sum(1 for e in lt if e["concentration"] is None)
            bad["lt_concentration_ne_dl"] += sum(1 for e in lt if e["concentration"] is not None and abs(e["concentration"] - e["detectionLimit"]) > 1e-12)
            # ND rows (no operator) must still have no concentration
            nd = [e for e in by.get(a, []) if e["relativeOperatorId"] is None and e["concentration"] is None]
            seen["nd_rows_untouched"] += len(nd)
    print(f"{i + 20}/{len(sample)}", dict(seen), dict(bad))
print("SAMPLE RESULT", dict(seen), dict(bad))

# Stream Sediment: any '<' rows?
st = sorted({r["aliquotName"] for r in csv.DictReader(open(HERE / "elem_stream.tsv", encoding="utf-8"), delimiter="\t")})
names = random.sample(st, 20)
rows = fx.fetch("elem", names)
print("STREAM spot check:", len(names), "aliquots,", len(rows), "rows,", sum(1 for e in rows if e["relativeOperatorId"] is not None), "with an operator")
