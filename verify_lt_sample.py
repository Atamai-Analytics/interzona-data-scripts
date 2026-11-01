#!/usr/bin/env python3
"""Independent read-only check of the '<' concentration update on a random sample of aliquots (finland | victoria)."""
import collections, json, os, random, sys
from pathlib import Path
import update_finland_sample_weight as base
import fix_lt_concentration as fx

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
setname = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 400
random.seed(20261020)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
info, _ = fx.plan(setname)
dpset = set(json.load(open(HERE / f"datapoint_ids_{fx.SETS[setname]['pkg']}.json")).values())
sample = random.sample(sorted(info), N)
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
            lt = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and e["relativeOperatorId"] == 1]
            got = collections.Counter((e[namef], fx.norm(e["detectionLimit"]) if e["detectionLimit"] is not None else None) for e in lt)
            seen[kind] += len(lt)
            if got != exp:
                bad["multiset_mismatch"] += 1
            for e in lt:
                if e["detectionLimit"] is None:
                    seen["no_value_rows_left_alone"] += 1
                    if e["concentration"] is not None:
                        bad["no_value_row_got_concentration"] += 1
                elif e["concentration"] is None:
                    bad["lt_without_concentration"] += 1
                elif abs(e["concentration"] - e["detectionLimit"]) > 1e-12:
                    bad["lt_concentration_ne_dl"] += 1
    print(f"{min(i + 20, len(sample))}/{len(sample)}", dict(seen), dict(bad))
print("SAMPLE RESULT", setname, dict(seen), dict(bad))
