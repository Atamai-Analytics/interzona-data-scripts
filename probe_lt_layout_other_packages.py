#!/usr/bin/env python3
"""Read-only: how are '<' values stored in LithoSurfer for the Finland Rock and Victoria soil packages? (random aliquot sample per load file)"""
import collections, csv, os, random, sys
from pathlib import Path
import update_finland_sample_weight as base
import fix_geus_lt_concentration as fx

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
random.seed(20261016)
base.load_dotenv()
base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                   user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
FILES = [("Finland extra128 (elem)", "elem_finland_rock_extra128.tsv", "elem", 20), ("Victoria soil (elem)", "elem_victoria_soil.tsv", "elem", 60)]
for label, fn, kind, n in FILES:
    namef, symf = fx.KINDS[kind][1], fx.KINDS[kind][2]
    exp = collections.defaultdict(collections.Counter)
    for r in csv.DictReader(open(HERE / fn, encoding="utf-8"), delimiter="\t"):
        if r["qualifier_code"] == "<":
            exp[r["aliquotName"]][(r[symf], round(float(r["Conc"]), 9) if r["Conc"] else None)] += 1
    names = random.sample(sorted(exp), min(n, len(exp)))
    layout = collections.Counter()
    found = notfound = mism = 0
    for i in range(0, len(names), 20):
        chunk = names[i:i + 20]
        by = collections.defaultdict(list)
        for e in fx.fetch(kind, chunk):
            by[e["aliquotName"]].append(e)
        for a in chunk:
            lt = [e for e in by.get(a, []) if e["relativeOperatorId"] == 1]
            if not lt:
                notfound += 1          # aliquot has no '<' row in LithoSurfer (e.g. rows removed/moved, or different name)
                continue
            found += 1
            for e in lt:
                layout[("concentration set" if e["concentration"] is not None else "concentration empty",
                        "DL set" if e["detectionLimit"] is not None else "DL empty")] += 1
            val = lambda e: e["detectionLimit"] if e["detectionLimit"] is not None else e["concentration"]
            got = collections.Counter((e[namef], round(float(val(e)), 9) if val(e) is not None else None) for e in lt)
            if got != exp[a]:
                mism += 1
                print("   DIFF", a, "| in load file only:", dict(exp[a] - got), "| in LithoSurfer only:", dict(got - exp[a]))
    print(f"{label}: sampled {len(names)} aliquots; with '<' rows in LithoSurfer {found}, none {notfound}, '<' set differs from load file {mism}; layouts {dict(layout)}")
