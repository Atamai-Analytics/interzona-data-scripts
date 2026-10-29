#!/usr/bin/env python3
"""Independent read-only check of the GEUS placeholder -> ND update on a random sample of aliquots (plus every aliquot named in a
BATCH ERROR / SKIP / VERIFY FAIL line of placeholder.log). Per aliquot (elements only - the plan has no oxides):
  * the ND rows are exactly the planned placeholder rows + the rows of the earlier ND job (nd_plan.csv) for that aliquot;
  * every planned placeholder row: operator ND, no concentration, detection limit == plan;
  * no '<' row with limit 10000 is left, except Cl (genuine '< 1 %' = 10000 ppm), which must still be '<' 10000.
Usage: python verify_placeholder_sample.py [N]"""
import collections, json, os, random, re, sys
from pathlib import Path
import pandas as pd
import update_finland_sample_weight as base
import fix_lt_concentration as fx
import fix_placeholder_nd as ph

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
random.seed(20261029)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
plan = ph.load_plan()
nd = pd.read_csv(HERE / "lt_conc_backups" / "nd_plan.csv")
nd = nd[nd.kind == "elem"]
nd_exp = collections.defaultdict(collections.Counter)
for a, n in zip(nd.aliquotName, nd.name):
    nd_exp[a][n] += 1
dpsets = {ds: set(json.load(open(HERE / f"datapoint_ids_{p}.json")).values()) for ds, p in ph.PKG.items()}

logged = set()
for line in open(ph.LOG, encoding="utf-8"):
    if line.startswith("=== FULL commit"):
        logged = set()                                          # only problems from the full run onwards
    if line.startswith(("BATCH ERROR", "SKIP", "VERIFY FAIL")):
        logged |= set(re.findall(r"'([^']+//[^']+)'", line)) | set(re.findall(r"elem (\S+ \[[^\]]*\])", line))
logged &= set(plan)
sample = sorted(set(random.sample(sorted(plan), min(N, len(plan)))) | logged)
print(f"checking {len(sample)} aliquots ({len(logged)} named in log problem lines)")
namef = fx.KINDS["elem"][1]
bad, seen = collections.Counter(), collections.Counter()
for i in range(0, len(sample), 20):
    names = sample[i:i + 20]
    by = collections.defaultdict(list)
    for e in fx.fetch("elem", names):
        by[e["aliquotName"]].append(e)
    for a in names:
        rows = [e for e in by.get(a, []) if e["gcdataPointId"] in dpsets[plan[a]["ds"]]]
        ndrows = [e for e in rows if e["relativeOperatorId"] == ph.ND_ID]
        if collections.Counter(e[namef] for e in ndrows) != plan[a]["elem"] + nd_exp.get(a, collections.Counter()):
            bad["nd_set_mismatch"] += 1
        for e in ndrows:
            if e[namef] in plan[a]["elem"]:
                seen["placeholder_nd"] += 1
                if e["concentration"] is not None:
                    bad["nd_with_concentration"] += 1
                if not ph.same(e["detectionLimit"], plan[a]["lim"]["elem"][e[namef]]):
                    bad["limit_ne_plan"] += 1
        for e in rows:
            if e["relativeOperatorId"] == 1 and e["detectionLimit"] is not None and ph.same(e["detectionLimit"], 10000):
                if e[namef] in ph.GENUINE_10000:
                    seen["cl_kept"] += 1
                    if not ph.same(e["concentration"], 10000):
                        bad["cl_changed"] += 1
                else:
                    bad["placeholder_left"] += 1
    print(f"{min(i + 20, len(sample))}/{len(sample)}", dict(seen), dict(bad))
print("SAMPLE RESULT", dict(seen), dict(bad))
