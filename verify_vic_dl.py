#!/usr/bin/env python3
"""Independent read-only check of the Victoria detection-limit update: on a random sample of aliquots plus the aliquots named in the BATCH ERROR log lines,
every planned '<' row must hold the planned GSV limit in BOTH detectionLimit and concentration, keep operator 1, and the aliquot's '<' row count must equal the load file's."""
import collections, json, os, random, re, sys
from pathlib import Path
import update_finland_sample_weight as base
import fix_lt_concentration as fx
import fix_vic_dl as vd

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
random.seed(20261028)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
plan = vd.load_plan()
info, _ = fx.plan("victoria")
expected_n = {k: sum(v["elem"].values()) for k, v in info.items()}
dpset = set(json.load(open(HERE / f"datapoint_ids_{vd.PKG}.json")).values())
err_names = set()
for line in open(vd.LOG, encoding="utf-8"):
    if line.startswith("BATCH ERROR"):
        err_names.update(re.findall(r"'(\d+ [^']+)'", line))
err_names &= set(plan)
sample = sorted(set(random.sample(sorted(plan), min(N, len(plan)))) | err_names)
print(f"checking {len(sample)} aliquots ({len(err_names)} from error batches)")
bad = collections.Counter(); seen = collections.Counter(); examples = []
for i in range(0, len(sample), 20):
    names = sample[i:i + 20]
    by = collections.defaultdict(list)
    for e in fx.fetch("elem", names):
        by[e["aliquotName"]].append(e)
    for a in names:
        lt = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and e["relativeOperatorId"] == 1]
        seen["aliquots"] += 1
        if len(lt) != expected_n[a]:
            bad["lt_count_mismatch"] += 1; examples.append((a, "count", len(lt), expected_n[a])); continue
        for e in lt:
            pe = plan[a].get(e["elementName"])
            if pe is None:
                continue
            new = pe[0]; seen["planned_rows"] += 1
            if not (vd.same(e["detectionLimit"], new) and vd.same(e["concentration"], new)):
                bad["row_not_new"] += 1
                if len(examples) < 10: examples.append((a, e["elementName"], e["concentration"], e["detectionLimit"], new))
print("seen", dict(seen)); print("bad", dict(bad) or "none")
for x in examples[:10]: print("  ", x)
