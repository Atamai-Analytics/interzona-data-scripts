#!/usr/bin/env python3
"""GEUS Rock / HMC / Soil: give the blank "ND" rows (no operator, no concentration, no detection limit) the relative operator ND (id 267070200),
keep the concentration blank, and set the detection limit from nd_plan.csv (lowest source limit for the element/oxide + method, else the Actlabs
catalogue, else none).  Elements AND oxides.

Per aliquot (aliquotName.in batches), ALL of these must hold or the aliquot is skipped and logged:
  * the rows of the package's data points that are either 'blank' (operator, concentration and detection limit all empty) or already ND
    carry exactly the element/oxide names of the ND rows in the load files
  * an already-ND row has no concentration
After the PUTs the batch is re-read: same rows, planned rows hold operator ND + the planned limit + no concentration, all others unchanged.
Backup lines (before-state of each row) are written and flushed BEFORE the PUTs.  Resumable (progress file), idempotent.

--dry-run [--limit N]   read only        --commit [--limit N]   write (use --limit 1 first as the one-row test)
"""
import argparse, collections, csv, json, os, random, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import update_finland_sample_weight as base
import fix_lt_concentration as fx

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
OUT = HERE / "lt_conc_backups"
ND_ID = 267070200
PKG = {"rock": 205700763, "hmc": 205700762, "soil": 205700764}
BATCH = 20
WORKERS = 6
lock = threading.Lock()
stats = collections.Counter()
LOG = OUT / "nd.log"
PROGRESS = OUT / "nd_progress.txt"
BACKUP = OUT / "nd_before.csv"


def log(msg):
    with lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def load_plan():
    p = pd.read_csv(OUT / "nd_plan.csv")
    plan = {}
    for r in p.itertuples():
        a = plan.setdefault(r.aliquotName, {"ds": r.dataset, "elem": collections.Counter(), "oxide": collections.Counter(), "lim": {"elem": {}, "oxide": {}}})
        assert a["ds"] == r.dataset, f"aliquot {r.aliquotName} in two datasets"
        a[r.kind][r.name] += 1
        lim = None if pd.isna(r.limit) else float(r.limit)
        prev = a["lim"][r.kind].get(r.name, "unset")
        assert prev in ("unset", lim) or (prev is not None and lim is not None and fx.norm(prev) == fx.norm(lim)), f"two limits for {r.aliquotName} {r.name}"
        a["lim"][r.kind][r.name] = lim
    return plan


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return fx.norm(a) == fx.norm(b)


def process_batch(names, plan, dpsets, commit, wr, fh):
    skipped = set()
    try:
        for kind in ("elem", "oxide"):
            ep, namef, _ = fx.KINDS[kind]
            want = [a for a in names if plan[a][kind]]
            if not want:
                continue
            by = collections.defaultdict(list)
            for e in fx.fetch(kind, want):
                by[e["aliquotName"]].append(e)
            changed = []
            for a in want:
                exp = plan[a][kind]
                dpset = dpsets[plan[a]["ds"]]
                cand = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and
                        ((e["relativeOperatorId"] is None and e["concentration"] is None and e["detectionLimit"] is None) or e["relativeOperatorId"] == ND_ID)]
                got = collections.Counter(e[namef] for e in cand)
                if got != exp:
                    stats["skip_mismatch"] += 1
                    log(f"SKIP {kind} {a}: expected {dict(exp)} got {dict(got)}")
                    skipped.add(a)
                    continue
                if any(e["relativeOperatorId"] == ND_ID and e["concentration"] is not None for e in cand):
                    stats["skip_state"] += 1
                    log(f"SKIP {kind} {a}: ND row with a concentration")
                    skipped.add(a)
                    continue
                todo = []
                for e in cand:
                    lim = plan[a]["lim"][kind][e[namef]]
                    if e["relativeOperatorId"] == ND_ID and same(e["detectionLimit"], lim):
                        continue
                    todo.append((e, lim))
                stats[f"{kind}_already"] += len(cand) - len(todo)
                if not commit:
                    stats[f"{kind}_would_change"] += len(todo)
                    stats[f"{kind}_would_get_limit"] += sum(1 for e, l in todo if l is not None)
                    continue
                if todo:
                    with lock:
                        for e, lim in todo:
                            wr.writerow([e["id"], kind, a, e[namef], e["relativeOperatorId"], e["concentration"], e["detectionLimit"], ND_ID, lim])
                        fh.flush()                                 # backup is on disk before any PUT
                    for e, lim in todo:
                        body = dict(e)
                        body["relativeOperatorId"] = ND_ID
                        body["relativeOperatorName"] = "ND"
                        body["detectionLimit"] = lim
                        body["concentration"] = None
                        base.api("PUT", f"/api/geochem/{ep}", body)
                        stats[f"{kind}_changed"] += 1
                    changed.append((a, {e["id"]: lim for e, lim in todo}))
            if changed:
                arows = collections.defaultdict(dict)
                for e in fx.fetch(kind, [a for a, _ in changed]):
                    arows[e["aliquotName"]][e["id"]] = e
                for a, newmap in changed:
                    before = {e["id"]: e for e in by[a]}
                    after = arows.get(a, {})
                    ok = set(after) == set(before)
                    for i, b0 in before.items():
                        if i in newmap:
                            x = after.get(i)
                            ok = ok and x is not None and x["relativeOperatorId"] == ND_ID and x["concentration"] is None and same(x["detectionLimit"], newmap[i])
                            for k in b0:                           # nothing else may have changed
                                if k not in ("relativeOperatorId", "relativeOperatorName", "detectionLimit", "concentration"):
                                    ok = ok and x is not None and x.get(k) == b0[k]
                        else:
                            ok = ok and after.get(i) == b0
                    if not ok:
                        stats["verify_fail"] += 1
                        log(f"VERIFY FAIL {kind} {a}")
                        skipped.add(a)
        finished = [a for a in names if a not in skipped]
        stats["aliquots_done"] += len(finished)
        if commit and finished:
            with lock, open(PROGRESS, "a", encoding="utf-8") as f:
                for a in finished:
                    f.write(a + chr(10))
    except Exception as ex:
        stats["batch_error"] += 1
        log(f"BATCH ERROR {names[:2]}...: {ex!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.commit == a.dry_run:
        raise SystemExit("choose exactly one of --dry-run / --commit")
    base.check_no_other_instance()
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    plan = load_plan()
    dpsets = {ds: set(json.load(open(HERE / f"datapoint_ids_{p}.json")).values()) for ds, p in PKG.items()}
    done = set(PROGRESS.read_text(encoding="utf-8").splitlines()) if PROGRESS.exists() else set()
    todo = sorted(x for x in plan if x not in done)
    tot = sum(sum(v["elem"].values()) + sum(v["oxide"].values()) for v in plan.values())
    print(f"plan: {tot} ND rows in {len(plan)} aliquots; already finished {len(done)}; to process {len(todo)}")
    if a.limit:
        random.seed(20261026)
        todo = random.sample(todo, min(a.limit, len(todo)))
    new_file = not BACKUP.exists()
    fh = open(BACKUP, "a", newline="", encoding="utf-8")
    wr = csv.writer(fh)
    if new_file:
        wr.writerow(["id", "kind", "aliquotName", "name", "operator_before", "concentration_before", "detectionLimit_before", "operator_after", "detectionLimit_after"])
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    ctr = {"n": 0}

    def run(b):
        process_batch(b, plan, dpsets, a.commit, wr, fh)
        with lock:
            ctr["n"] += 1
            if ctr["n"] % 25 == 0:
                print(f"{ctr['n']}/{len(batches)} batches", dict(stats))

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(run, batches))
    fh.close()
    print("FINISHED", dict(stats))


if __name__ == "__main__":
    main()
