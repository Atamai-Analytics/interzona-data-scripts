#!/usr/bin/env python3
"""Victoria soil (LithoSurfer package 246454433): replace the ESTIMATED '<' limits with GSV's own method-level detection limits.

For every '<' ElementalConcentration (operator 1) in the package whose source assay has a positive GSV method detection limit
(victoria_dl_plan.csv, built by victoria_dl_plan.py; ppm) set  detectionLimit = concentration = that limit.  Operator unchanged.
Rows without a plan entry (142 with no source match, 1 with a zero source limit) are left exactly as they are.

Per aliquot (aliquotName.in batches) ALL of these must hold or the aliquot is skipped and logged:
  * the '<' rows of the package's data points number exactly as in the load file (elem_victoria_soil.tsv)
  * every '<' row with a plan entry shows a detection limit equal (6 significant digits) to the old estimate, to the new limit, or empty
    (the 9,491 value-less rows), and its concentration is empty or equal to that detection limit
After the PUTs the batch is re-read: same row set, planned rows hold the new limit in both fields, everything else unchanged.
Backup lines (old concentration / detectionLimit per row id) are written and flushed BEFORE the PUTs.  Resumable (progress file).

--dry-run [--limit N]   read only        --commit   write
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
PKG = 246454433
BATCH = 20
WORKERS = 6
lock = threading.Lock()
stats = collections.Counter()
LOG = OUT / "victoria_dl.log"
PROGRESS = OUT / "victoria_dl_progress.txt"
BACKUP = OUT / "victoria_dl_before.csv"


def log(msg):
    with lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def load_plan():
    p = pd.read_csv(OUT / "victoria_dl_plan.csv")
    p = p[p.new_dl > 0]
    plan = collections.defaultdict(dict)      # aliquot -> {element: (new_dl, old_est or None)}
    for r in p.itertuples():
        plan[r.aliquotName][r.element_symbol] = (float(r.new_dl), None if pd.isna(r.old_est) else float(r.old_est))
    return plan


def same(a, b):
    return a is not None and b is not None and fx.norm(a) == fx.norm(b)


def process_batch(names, plan, expected_n, dpset, commit, wr, fh):
    skipped = set()
    try:
        by = collections.defaultdict(list)
        for e in fx.fetch("elem", names):
            by[e["aliquotName"]].append(e)
        changed = []
        for a in names:
            lt = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and e["relativeOperatorId"] == 1]
            if len(lt) != expected_n[a]:
                stats["skip_count"] += 1
                log(f"SKIP {a}: expected {expected_n[a]} '<' rows, got {len(lt)}")
                skipped.add(a)
                continue
            todo, bad = [], False
            for e in lt:
                pe = plan[a].get(e["elementName"])
                if pe is None:
                    continue                                   # row without a plan entry: untouched
                new, old = pe
                dl, conc = e["detectionLimit"], e["concentration"]
                dl_ok = dl is None or same(dl, new) or (old is not None and same(dl, old))
                conc_ok = conc is None or (dl is not None and same(conc, dl)) or same(conc, new)
                if not (dl_ok and conc_ok):
                    bad = True
                    log(f"SKIP {a} {e['elementName']}: unexpected state concentration={conc} detectionLimit={dl} (plan new={new}, old={old})")
                    break
                if not (dl is not None and conc is not None and same(dl, new) and same(conc, new)):
                    todo.append((e, new))
            if bad:
                stats["skip_state"] += 1
                skipped.add(a)
                continue
            stats["rows_already_new"] += sum(1 for e in lt if plan[a].get(e["elementName"]) is not None) - len(todo)
            if not commit:
                stats["would_change"] += len(todo)
                stats["would_fill_empty"] += sum(1 for e, n in todo if e["detectionLimit"] is None)
                stats["would_alter_value"] += sum(1 for e, n in todo if e["detectionLimit"] is not None and not same(e["detectionLimit"], n))
                continue
            if todo:
                with lock:
                    for e, n in todo:
                        wr.writerow([e["id"], a, e["elementName"], e["concentration"], e["detectionLimit"], e["relativeOperatorId"], e["gcdataPointId"], n])
                    fh.flush()                                 # backup is on disk before any PUT
                for e, n in todo:
                    body = dict(e)
                    body["detectionLimit"] = n
                    body["concentration"] = n
                    base.api("PUT", "/api/geochem/ElementalConcentration", body)
                    stats["rows_changed"] += 1
                changed.append((a, {e["id"]: n for e, n in todo}))
        if changed:
            arows = collections.defaultdict(dict)
            for e in fx.fetch("elem", [a for a, _ in changed]):
                arows[e["aliquotName"]][e["id"]] = e
            for a, newmap in changed:
                before = {e["id"]: e for e in by[a]}
                after = arows.get(a, {})
                ok = set(after) == set(before)
                for i, b0 in before.items():
                    want = dict(b0)
                    if i in newmap:
                        want["detectionLimit"] = newmap[i]
                        want["concentration"] = newmap[i]
                    ok = ok and after.get(i) == want
                if not ok:
                    stats["verify_fail"] += 1
                    log(f"VERIFY FAIL {a}")
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
    info, _ = fx.plan("victoria")
    expected_n = {k: sum(v["elem"].values()) for k, v in info.items()}
    dpset = set(json.load(open(HERE / f"datapoint_ids_{PKG}.json")).values())
    done = set(PROGRESS.read_text(encoding="utf-8").splitlines()) if PROGRESS.exists() else set()
    todo = sorted(x for x in plan if x not in done)
    print(f"plan: {sum(len(v) for v in plan.values())} rows in {len(plan)} aliquots; already finished {len(done)}; to process {len(todo)}")
    if a.limit:
        random.seed(20261023)
        todo = random.sample(todo, min(a.limit, len(todo)))
    new_file = not BACKUP.exists()
    fh = open(BACKUP, "a", newline="", encoding="utf-8")
    wr = csv.writer(fh)
    if new_file:
        wr.writerow(["id", "aliquotName", "element", "concentration_before", "detectionLimit_before", "relativeOperatorId", "gcdataPointId", "new_limit"])
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    ctr = {"n": 0}

    def run(b):
        process_batch(b, plan, expected_n, dpset, a.commit, wr, fh)
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
