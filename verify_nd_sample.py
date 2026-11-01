#!/usr/bin/env python3
"""Independent read-only check of the GEUS ND update on a random sample of aliquots: every planned ND row must have operator ND (267070200),
no concentration and the planned detection limit; no row that is not a planned ND row may carry operator ND."""
import collections, json, os, random, sys
from pathlib import Path
import update_finland_sample_weight as base
import fix_lt_concentration as fx
import fix_nd_operator as nd

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
random.seed(20261027)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
plan = nd.load_plan()
dpsets = {ds: set(json.load(open(HERE / f"datapoint_ids_{p}.json")).values()) for ds, p in nd.PKG.items()}
sample = random.sample(sorted(plan), N)
bad = collections.Counter()
seen = collections.Counter()
for i in range(0, len(sample), 20):
    names = sample[i:i + 20]
    for kind in ("elem", "oxide"):
        want = [a for a in names if plan[a][kind]]
        if not want:
            continue
        namef = fx.KINDS[kind][1]
        by = collections.defaultdict(list)
        for e in fx.fetch(kind, want):
            by[e["aliquotName"]].append(e)
        for a in want:
            dpset = dpsets[plan[a]["ds"]]
            ndrows = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and e["relativeOperatorId"] == nd.ND_ID]
            got = collections.Counter(e[namef] for e in ndrows)
            seen[kind] += len(ndrows)
            if got != plan[a][kind]:
                bad["nd_multiset_mismatch"] += 1
            for e in ndrows:
                lim = plan[a]["lim"][kind].get(e[namef])
                if e["concentration"] is not None:
                    bad["nd_with_concentration"] += 1
                if not nd.same(e["detectionLimit"], lim):
                    bad["nd_limit_ne_plan"] += 1
                if lim is None:
                    seen["nd_without_limit"] += 1
                if e.get("relativeOperatorName") != "ND":
                    bad["operator_name_not_ND"] += 1
    print(f"{min(i + 20, len(sample))}/{len(sample)}", dict(seen), dict(bad))
print("SAMPLE RESULT", dict(seen), dict(bad))
