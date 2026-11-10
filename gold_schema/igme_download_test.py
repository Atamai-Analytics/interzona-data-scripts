"""IGME (Spain) geochemistry - ONE-ELEMENT download test (no database writes), 2026-11-08.

API (see memory igme-spain-geochem): POST resultCampSubs/{limit}/{camp}?codSubs={sub} body "" or a JSON-string WKT polygon -> {"<total>": rows};
GET fichaDetalle/{id} -> all elements of one sample with technique, type, detection limit and 'restringido' (restricted) flag.
Method: for every campaign that has the element, fetch the whole campaign if total <= LIMIT, else split the bounding box into quadrants
recursively (quadtree) until each piece fits. Then fetch fichaDetalle for N random samples per campaign to learn the element's technique /
detection limit / restricted flag and to check which technique the table value comes from. Polite pace: PAUSE s between requests.
Usage: python igme_download_test.py [element symbol, default Li]
Output: D:/CriticalMineralsDB/Spain/download_20261108/igme_test_<el>_rows.jsonl, ..._detail.jsonl, ..._report.json
"""
import json, os, random, sys, time, urllib.request, collections

EL = sys.argv[1] if len(sys.argv) > 1 else "Li"
B = "https://info.igme.es/APIs/Geoquimica/Geoquimica/"
OUT = "D:/CriticalMineralsDB/Spain/download_20261108"
LIMIT, PAUSE, NDETAIL = 2000, 0.5, 25
BBOX = (-18.5, 27.0, 4.5, 44.0)          # Iberia + Balearics + Canaries
os.makedirs(OUT, exist_ok=True)
stats = collections.Counter(); t0 = time.time()


def call(path, body=None, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(B + path, data=body, headers={"Content-Type": "application/json"} if body is not None else {},
                                         method="POST" if body is not None else "GET")
            r = urllib.request.urlopen(req, timeout=300).read(); stats["requests"] += 1; stats["bytes"] += len(r)
            time.sleep(PAUSE)
            return json.loads(r.decode("utf-8"))
        except Exception as e:
            stats["errors"] += 1; print("  retry", k, path[:80], e, flush=True); time.sleep(5 * (k + 1))
    raise RuntimeError("failed " + path)


def wkt(b):
    x0, y0, x1, y1 = b
    return json.dumps(f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))").encode()


MAX_REQUESTS, MIN_BOX = 2500, 0.002      # caps: stop splitting at ~200 m (co-located sample pairs can never be separated; copper lost 2 of 8,686 that way)
unresolved = []


def fetch(camp, sub, box=None, depth=0):
    if stats["requests"] >= MAX_REQUESTS: raise RuntimeError("request cap reached")
    j = call(f"resultCampSubs/{LIMIT}/{camp}?codSubs={sub}", wkt(box) if box else b'""')
    total = int(list(j)[0]); rows = j[list(j)[0]]
    if total <= len(rows): return rows
    if box is None: box = BBOX
    x0, y0, x1, y1 = box
    # Split ONLY when the page is full. IGME's API counts some samples it never returns (total 2 / returned 1, total 1 / returned 0, at any
    # box size - the tungsten run spent ~10 requests per such sample before this rule); a short page means those, not a full page.
    page_full = len(rows) >= LIMIT - 10
    if not page_full or x1 - x0 < MIN_BOX or y1 - y0 < MIN_BOX:  # keep what we got, log the shortfall
        unresolved.append({"camp": camp, "box": box, "total": total, "returned": len(rows)}); print("  UNRESOLVED", unresolved[-1], flush=True)
        return rows
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    out = []
    for q in ((x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)):
        out += fetch(camp, sub, q, depth + 1)
    return out


subs_all = {s["text"]: s["cod"] for s in call("getAllSubs")}
camps = call("getAllCamp")
report, allrows = {}, []
for c in camps:
    subs = {s["text"]: s["cod"] for s in call(f"subsCamp/{c['cod']}")}
    if EL not in subs: continue
    t = time.time(); r0 = stats["requests"]
    rows = fetch(c["cod"], subs[EL])
    uniq = {r["id"]: r for r in rows}                     # quadrant edges can repeat a point
    allrows += uniq.values()
    v = [r["concentracion"] for r in uniq.values() if r["concentracion"] is not None]
    report[c["text"]] = {"camp": c["cod"], "rows": len(rows), "samples": len(uniq), "requests": stats["requests"] - r0, "secs": round(time.time() - t, 1),
                         "units": dict(collections.Counter(r["unidad"] for r in uniq.values())), "types": dict(collections.Counter(r["tipoMuestra"] for r in uniq.values())),
                         "min": min(v) if v else None, "max": max(v) if v else None, "nulls": len(uniq) - len(v), "negatives": sum(1 for x in v if x < 0)}
    print(c["text"], report[c["text"]], f"| total requests {stats['requests']}, {round(time.time() - t0)} s", flush=True)
    with open(f"{OUT}/igme_test_{EL}_rows.jsonl", "a" if len(report) > 1 else "w", encoding="utf-8") as f:
        for r in uniq.values():
            r = {k: v for k, v in r.items() if k != "sustancias"}; f.write(json.dumps(r, ensure_ascii=False) + "\n")

# detail check
random.seed(1); det = []
for name, rep in report.items():
    ids = [r["id"] for r in allrows if r["codCampana"] == rep["camp"]]
    for i in random.sample(ids, min(NDETAIL, len(ids))):
        d = call(f"fichaDetalle/{i}")[0]
        tab = next(r for r in allrows if r["id"] == i)
        els = [e for e in d["sp_reportGeoquimicaDetalleResult"] if e["sustancia"] == EL]
        det.append({"campaign": name, "id": i, "table_value": tab["concentracion"], "table_unit": tab["unidad"], "detail": els,
                    "n_elements": len(d["sp_reportGeoquimicaDetalleResult"]),
                    "n_restricted": sum(1 for e in d["sp_reportGeoquimicaDetalleResult"] if e["restringido"])})
with open(f"{OUT}/igme_test_{EL}_detail.jsonl", "w", encoding="utf-8") as f:
    for d in det: f.write(json.dumps(d, ensure_ascii=False) + "\n")
summary = collections.defaultdict(lambda: collections.Counter())
for d in det:
    s = summary[d["campaign"]]
    s["checked"] += 1; s[f"techniques={'+'.join(sorted(e['tecnica'] for e in d['detail']))}"] += 1
    s[f"dl={','.join(str(e['limiteDeteccion']) for e in d['detail'])}"] += 1
    s["restricted_el"] += any(e["restringido"] for e in d["detail"])
    s["table_matches_a_detail_value"] += any(abs((e["concentracion"] or -1) - (d["table_value"] or -2)) < 1e-9 for e in d["detail"])
    s["table_below_dl"] += any(d["table_value"] is not None and e["limiteDeteccion"] and d["table_value"] < e["limiteDeteccion"] for e in d["detail"])
    s["samples_with_any_restricted_element"] += d["n_restricted"] > 0
json.dump({"element": EL, "elapsed_s": round(time.time() - t0), "requests": stats["requests"], "MB": round(stats["bytes"] / 1e6, 1), "errors": stats["errors"], "unresolved": unresolved,
           "campaigns": report, "detail_check": {k: dict(v) for k, v in summary.items()}},
          open(f"{OUT}/igme_test_{EL}_report.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("DONE", EL, "samples", len(allrows), "requests", stats["requests"], "MB", round(stats["bytes"] / 1e6, 1), "errors", stats["errors"], "secs", round(time.time() - t0))
for k, v in summary.items(): print(" ", k, dict(v))
