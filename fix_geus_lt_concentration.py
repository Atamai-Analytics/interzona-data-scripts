#!/usr/bin/env python3
"""GEUS packages: for ElementalConcentration / OxideConcentration rows with the '<' operator, copy detectionLimit into concentration.

Loaded layout: concentration = null, detectionLimit = value, relativeOperatorId = 1 ('<').  Target: concentration = value too
(detectionLimit and operator are kept).  ND rows (operator null) are never touched.
PUT /api/geochem/<Elemental|Oxide>Concentration is a full replace of the DTO, so the complete current row is fetched and PUT
back with only 'concentration' changed.

Per aliquot (looked up in batches via aliquotName.in), ALL of these must hold or the aliquot is skipped and logged:
  1. the '<' rows (operator 1) restricted to data points of the package equal, as a multiset of (name, detection limit), the
     '<' rows of the load file (elem_/oxide_<package>.tsv) - so we are looking at exactly the rows we loaded
  2. no '<' row already holds a concentration different from its detection limit
After the PUTs the aliquot is re-read: row set unchanged, every '<' row has concentration == detectionLimit, every other
row identical to before.  Idempotent / resumable (finished aliquots are listed in the progress file).  Rows are backed up first.

--dry-run      read only, report what would change     --limit N  only the first N aliquots
--commit       write
"""
import argparse, collections, csv, json, os, sys, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import update_finland_sample_weight as base

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
BACKUP = HERE / "geus_lt_backups" / "geus_lt_before.csv"
PROGRESS = HERE / "geus_lt_backups" / "geus_lt_progress.txt"
LOG = HERE / "geus_lt_backups" / "geus_lt.log"
BATCH = 20
WORKERS = 6
PACKAGES = {205700763: ("rock", "elem_rock.tsv", "oxide_rock.tsv"),
            205700762: ("hmc", "elem_hmc.tsv", "oxide_hmc.tsv"),
            205700764: ("soil", "elem_soil.tsv", None)}
KINDS = {"elem": ("ElementalConcentration", "elementName", "element_symbol"),
         "oxide": ("OxideConcentration", "oxideName", "element_oxide")}
lock = threading.Lock()
stats = collections.Counter()


def log(msg):
    with lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def plan():
    """{aliquot: {'pkg': id, 'elem': Counter[(name, dl)], 'oxide': Counter[...]}} from the load files."""
    out = {}
    for pkg, (nm, ef, of) in PACKAGES.items():
        for kind, fn in (("elem", ef), ("oxide", of)):
            if not fn:
                continue
            for r in csv.DictReader(open(HERE / fn, encoding="utf-8"), delimiter="\t"):
                if r["qualifier_code"] != "<":
                    continue
                a = r["aliquotName"]
                assert "," not in a, a
                d = out.setdefault(a, {"pkg": pkg, "elem": collections.Counter(), "oxide": collections.Counter()})
                assert d["pkg"] == pkg, f"aliquot {a} in two packages"
                d[kind][(r[KINDS[kind][2]], round(float(r["Conc"]), 9))] += 1
    return out


def fetch(kind, names):
    ep = KINDS[kind][0]
    return base.api("GET", f"/api/geochem/{ep}?aliquotName.in=%s&size=20000" % urllib.parse.quote(",".join(names))) or []


def process_batch(names, info, dpsets, commit, wr):
    try:
        for kind in ("elem", "oxide"):
            ep, namef, _ = KINDS[kind]
            if not any(info[a][kind] for a in names):
                continue
            rows = fetch(kind, names)
            changed = []
            by = collections.defaultdict(list)
            for e in rows:
                by[e["aliquotName"]].append(e)
            for a in names:
                exp = info[a][kind]
                if not exp:
                    continue
                ours = [e for e in by.get(a, []) if e["gcdataPointId"] in dpsets[info[a]["pkg"]]]
                lt = [e for e in ours if e["relativeOperatorId"] == 1]
                got = collections.Counter((e[namef], round(float(e["detectionLimit"]), 9)) for e in lt if e["detectionLimit"] is not None)
                if got != exp or len(lt) != sum(exp.values()):
                    stats["skip_mismatch"] += 1
                    log(f"SKIP {kind} {a}: expected {sum(exp.values())} '<' rows, got {len(lt)} (multiset equal: {got == exp})")
                    info[a]["bad"] = True
                    continue
                if any(e["concentration"] is not None and abs(e["concentration"] - e["detectionLimit"]) > 1e-12 for e in lt):
                    stats["skip_conflict"] += 1
                    log(f"SKIP {kind} {a}: '<' row with a different concentration")
                    info[a]["bad"] = True
                    continue
                todo = [e for e in lt if e["concentration"] is None]
                stats[f"{kind}_already"] += len(lt) - len(todo)
                if not commit:
                    stats[f"{kind}_would_change"] += len(todo)
                    continue
                if todo:
                    with lock:
                        for e in todo:
                            wr.writerow([kind, e["id"], a, e[namef], e["concentration"], e["detectionLimit"], e["relativeOperatorId"], e["gcdataPointId"]])
                    for e in todo:
                        n = dict(e)
                        n["concentration"] = e["detectionLimit"]
                        base.api("PUT", f"/api/geochem/{ep}", n)
                        stats[f"{kind}_changed"] += 1
                    changed.append(a)
            if changed:                       # one batched re-read for all aliquots changed in this batch
                arows = collections.defaultdict(dict)
                for e in fetch(kind, changed):
                    arows[e["aliquotName"]][e["id"]] = e
                for a in changed:
                    before = {e["id"]: e for e in by[a]}
                    after = arows.get(a, {})
                    ok = set(after) == set(before)
                    for i, b0 in before.items():
                        want = dict(b0)
                        if b0["relativeOperatorId"] == 1 and b0["gcdataPointId"] in dpsets[info[a]["pkg"]]:
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
                    with lock, open(PROGRESS, "a", encoding="utf-8") as f:
                        f.write(a + "\n")
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
    BACKUP.parent.mkdir(exist_ok=True)
    info = plan()
    tot = collections.Counter()
    for v in info.values():
        tot["elem"] += sum(v["elem"].values())
        tot["oxide"] += sum(v["oxide"].values())
    print(f"plan: {len(info)} aliquots, '<' rows in load files: elemental {tot['elem']}, oxide {tot['oxide']}")
    dpsets = {p: set(json.load(open(HERE / f"datapoint_ids_{p}.json")).values()) for p in PACKAGES}
    done = set(PROGRESS.read_text(encoding="utf-8").splitlines()) if PROGRESS.exists() else set()
    todo = sorted(x for x in info if x not in done)
    if a.limit:
        todo = todo[:a.limit]
    print(f"aliquots already finished: {len(done)}; to process now: {len(todo)}")
    new_file = not BACKUP.exists()
    fh = open(BACKUP, "a", newline="", encoding="utf-8")
    wr = csv.writer(fh)
    if new_file:
        wr.writerow(["kind", "id", "aliquotName", "name", "concentration", "detectionLimit", "relativeOperatorId", "gcdataPointId"])
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    ctr = {"n": 0}

    def run(b):
        process_batch(b, info, dpsets, a.commit, wr)
        fh.flush()
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
