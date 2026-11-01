#!/usr/bin/env python3
"""Copy detectionLimit into concentration for '<' ElementalConcentration / OxideConcentration rows (detectionLimit and the '<'
operator are kept; ND rows and '<' rows without any value are never touched).  Generalised from fix_geus_lt_concentration.py.

--set finland   LithoSurfer package 244688701 (GTK Finland Rock): elem/oxide main, extra128, flagD375 + 308M.  '<' rows whose
                result_id was moved to 308M (finland_fix_backups/analytical_results_icpms_moved_before.csv) were deleted from the 511P
                aliquot earlier and are excluded from the 511P expectation.
--set victoria  package 246454433 (Victoria soil).  '<' rows in the load file with an empty value (no number anywhere in the source)
                are expected to exist without a value and are left as they are.

Per aliquot (aliquotName.in batches) the '<' rows (operator 1, restricted to the package's data points) must equal, as a multiset of
(name, detection limit or None), the '<' rows of the load files, and none may hold a concentration different from its detection
limit - otherwise the aliquot is skipped and logged.  After the PUTs the batch is re-read and compared.  Backup lines are written
and flushed BEFORE the PUTs.  Resumable (progress file), idempotent.

--dry-run [--limit N]   read only (N aliquots per package file group)      --commit   write
"""
import argparse, collections, csv, json, os, random, sys, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
OUT = HERE / "lt_conc_backups"
BATCH = 20
WORKERS = 6
KINDS = {"elem": ("ElementalConcentration", "elementName", "element_symbol"),
         "oxide": ("OxideConcentration", "oxideName", "element_oxide")}
SETS = {
    "finland": {"pkg": 244688701, "exclude_moved": ("elem_finland_rock.tsv", "elem_finland_rock_extra128.tsv", "elem_finland_rock_flagD375.tsv",
                                                     "oxide_finland_rock.tsv", "oxide_finland_rock_extra128.tsv", "oxide_finland_rock_flagD375.tsv"),
                "files": [("elem", "elem_finland_rock.tsv"), ("elem", "elem_finland_rock_308M.tsv"), ("elem", "elem_finland_rock_extra128.tsv"),
                          ("elem", "elem_finland_rock_flagD375.tsv"), ("oxide", "oxide_finland_rock.tsv"), ("oxide", "oxide_finland_rock_extra128.tsv"),
                          ("oxide", "oxide_finland_rock_flagD375.tsv")]},
    "victoria": {"pkg": 246454433, "exclude_moved": (), "files": [("elem", "elem_victoria_soil.tsv")]},
}
lock = threading.Lock()
stats = collections.Counter()
CFG = {}


def norm(v):
    """6 significant digits: the load files carry float32 artefacts (288.100006) where LithoSurfer holds 288.1."""
    return float("%.6g" % float(v))


def log(msg):
    with lock, open(CFG["log"], "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def plan(setname):
    s = SETS[setname]
    moved = {r["result_id"] for r in csv.DictReader(open(HERE / "finland_fix_backups/analytical_results_icpms_moved_before.csv", encoding="utf-8"))} \
        if s["exclude_moved"] else set()
    out = {}
    excl = 0
    for kind, fn in s["files"]:
        for r in csv.DictReader(open(HERE / fn, encoding="utf-8"), delimiter="\t"):
            if r["qualifier_code"] != "<":
                continue
            if fn in s["exclude_moved"] and r["result_id"] in moved:
                excl += 1
                continue
            a = r["aliquotName"]
            assert "," not in a, a
            d = out.setdefault(a, {"elem": collections.Counter(), "oxide": collections.Counter()})
            d[kind][(r[KINDS[kind][2]], norm(r["Conc"]) if r["Conc"] else None)] += 1
    return out, excl


def fetch(kind, names):
    return base.api("GET", f"/api/geochem/{KINDS[kind][0]}?aliquotName.in=%s&size=20000" % urllib.parse.quote(",".join(names))) or []


def process_batch(names, info, dpset, commit, wr, fh):
    try:
        for kind in ("elem", "oxide"):
            ep, namef, _ = KINDS[kind]
            if not any(info[a][kind] for a in names):
                continue
            by = collections.defaultdict(list)
            for e in fetch(kind, names):
                by[e["aliquotName"]].append(e)
            changed = []
            for a in names:
                exp = info[a][kind]
                if not exp:
                    continue
                lt = [e for e in by.get(a, []) if e["gcdataPointId"] in dpset and e["relativeOperatorId"] == 1]
                got = collections.Counter((e[namef], norm(e["detectionLimit"]) if e["detectionLimit"] is not None else None) for e in lt)
                if got != exp:
                    stats["skip_mismatch"] += 1
                    log(f"SKIP {kind} {a}: expected {sum(exp.values())} '<' rows, got {len(lt)}; load-file only {dict(exp - got)} | LithoSurfer only {dict(got - exp)}")
                    info[a]["bad"] = True
                    continue
                if any(e["concentration"] is not None and (e["detectionLimit"] is None or abs(e["concentration"] - e["detectionLimit"]) > 1e-12) for e in lt):
                    stats["skip_conflict"] += 1
                    log(f"SKIP {kind} {a}: '<' row with a different concentration")
                    info[a]["bad"] = True
                    continue
                valueless = [e for e in lt if e["detectionLimit"] is None]
                todo = [e for e in lt if e["concentration"] is None and e["detectionLimit"] is not None]
                stats[f"{kind}_no_value_left_alone"] += len(valueless)
                stats[f"{kind}_already"] += len(lt) - len(todo) - len(valueless)
                if not commit:
                    stats[f"{kind}_would_change"] += len(todo)
                    continue
                if todo:
                    with lock:
                        for e in todo:
                            wr.writerow([kind, e["id"], a, e[namef], e["concentration"], e["detectionLimit"], e["relativeOperatorId"], e["gcdataPointId"]])
                        fh.flush()                       # backup is on disk before any PUT
                    for e in todo:
                        n = dict(e)
                        n["concentration"] = e["detectionLimit"]
                        base.api("PUT", f"/api/geochem/{ep}", n)
                        stats[f"{kind}_changed"] += 1
                    changed.append(a)
            if changed:
                arows = collections.defaultdict(dict)
                for e in fetch(kind, changed):
                    arows[e["aliquotName"]][e["id"]] = e
                for a in changed:
                    before = {e["id"]: e for e in by[a]}
                    after = arows.get(a, {})
                    ok = set(after) == set(before)
                    for i, b0 in before.items():
                        want = dict(b0)
                        if b0["relativeOperatorId"] == 1 and b0["gcdataPointId"] in dpset and b0["detectionLimit"] is not None:
                            want["concentration"] = b0["detectionLimit"]
                        ok = ok and after.get(i) == want
                    if not ok:
                        stats["verify_fail"] += 1
                        log(f"VERIFY FAIL {kind} {a}")
                        info[a]["bad"] = True
        for a in names:
            if not info[a].get("bad"):
                stats["aliquots_done"] += 1
                if commit:
                    with lock, open(CFG["progress"], "a", encoding="utf-8") as f:
                        f.write(a + "\n")
    except Exception as ex:
        stats["batch_error"] += 1
        log(f"BATCH ERROR {names[:2]}...: {ex!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, choices=SETS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, help="random sample of N aliquots (dry run)")
    a = ap.parse_args()
    if a.commit == a.dry_run:
        raise SystemExit("choose exactly one of --dry-run / --commit")
    base.check_no_other_instance()
    base.load_dotenv()
    base._creds.update(host=os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io"),
                       user=os.environ["LITHOSURFER_USER"], pw=os.environ["LITHOSURFER_PASSWORD"])
    OUT.mkdir(exist_ok=True)
    CFG.update(log=OUT / f"{a.set}.log", progress=OUT / f"{a.set}_progress.txt", backup=OUT / f"{a.set}_before.csv")
    s = SETS[a.set]
    info, excl = plan(a.set)
    tot = collections.Counter()
    for v in info.values():
        for k in ("elem", "oxide"):
            for (nm, val), n in v[k].items():
                tot[k] += n
                if val is None:
                    tot[k + "_no_value"] += n
    print(f"plan {a.set}: {len(info)} aliquots; '<' rows in load files: {dict(tot)}; excluded as moved to 308M: {excl}")
    dpset = set(json.load(open(HERE / f"datapoint_ids_{s['pkg']}.json")).values())
    done = set(CFG["progress"].read_text(encoding="utf-8").splitlines()) if CFG["progress"].exists() else set()
    todo = sorted(x for x in info if x not in done)
    if a.limit:
        random.seed(20261016)
        todo = random.sample(todo, min(a.limit, len(todo)))
    print(f"aliquots already finished: {len(done)}; to process now: {len(todo)}")
    new_file = not CFG["backup"].exists()
    fh = open(CFG["backup"], "a", newline="", encoding="utf-8")
    wr = csv.writer(fh)
    if new_file:
        wr.writerow(["kind", "id", "aliquotName", "name", "concentration", "detectionLimit", "relativeOperatorId", "gcdataPointId"])
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    ctr = {"n": 0}

    def run(b):
        process_batch(b, info, dpset, a.commit, wr, fh)
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
