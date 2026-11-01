import os, sys, random, collections, urllib.parse
sys.path.insert(0, '.')
import verify_finland_icpms_final as V
base = V.base
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"), user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
base.login()
db = V.load_db()
labels = sorted(db[115]); random.seed(7)
pick = random.sample(labels[500:], 60)
bad = []; ok = 0
for i in range(0, 60, 10):
    chunk = pick[i:i + 10]
    names = [f"{l} 511P [ppm]" for l in chunk] + [f"{l} 308M [ppm]" for l in chunk if l in db[111]]
    q = urllib.parse.quote(",".join(names), safe="")
    rows = base.api("GET", f"/api/geochem/ElementalConcentration?aliquotName.in={q}&size=20000&sort=id,asc") or []
    by = collections.defaultdict(list)
    for r in rows: by[r['aliquotName']].append(r)
    for l in chunk:
        for pkg, suf in ((115, "511P"), (111, "308M")):
            exp = db[pkg].get(l, [])
            st = by.get(f"{l} {suf} [ppm]", [])
            miss, extra = V.compare(st, exp)
            if miss == 0 and extra == 0 and len(st) == len(exp): ok += 1
            else: bad.append((l, suf, len(st), len(exp), miss, extra))
    print(f"  chunk {i // 10 + 1}/6 done: ok={ok} bad={len(bad)}", flush=True)
print("FINAL random 60 samples x 2 aliquots exact value match:", ok, "ok,", len(bad), "bad", bad[:5])
