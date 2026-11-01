#!/usr/bin/env python3
"""Independent read-only check of the Victoria DL replacement on random aliquots: every '<' row with a plan entry must have
detectionLimit == concentration == plan new_dl; operator still '<'."""
import collections, json, os, random, sys
from pathlib import Path
import update_finland_sample_weight as base
import fix_lt_concentration as fx
import fix_vic_dl as vd

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
random.seed(20261027)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
plan = vd.load_plan()
dpset = set(json.load(open(HERE / f"datapoint_ids_{vd.PKG}.json")).values())
sample = random.sample(sorted(plan), N)
bad, seen = collections.Counter(), collections.Counter()
for i in range(0, len(sample), 20):
    names = sample[i:i + 20]
    by = collections.defaultdict(list)
    for e in fx.fetch("elem", names):
        by[e["aliquotName"]].append(e)
    for a in names:
        lt = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and e["relativeOperatorId"] == 1]
        got = collections.Counter(e["elementName"] for e in lt if e["elementName"] in plan[a])
        if got != collections.Counter(plan[a].keys()):
            bad["planned_rows_missing_or_extra"] += 1
        for e in lt:
            pe = plan[a].get(e["elementName"])
            if pe is None:
                seen["unplanned_lt_rows_ignored"] += 1
                continue
            seen["planned_rows"] += 1
            if e["detectionLimit"] is None or not vd.same(e["detectionLimit"], pe[0]):
                bad["dl_ne_plan"] += 1
            if e["concentration"] is None or not vd.same(e["concentration"], pe[0]):
                bad["conc_ne_plan"] += 1
    print(f"{min(i + 20, len(sample))}/{len(sample)}", dict(seen), dict(bad))
print("SAMPLE RESULT", dict(seen), dict(bad))
