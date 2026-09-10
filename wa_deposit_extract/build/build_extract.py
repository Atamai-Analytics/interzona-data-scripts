"""WA deposit extract — Step 5b: build the LithoSurfer extract from the loaded WA rows.

Inputs  (this dir):  wa_base.csv, wa_commodities.csv, wa_mineralogy.csv, ref_LCommodity.json
Outputs (../):       deposit.jsonl, deposit_endowment.jsonl, deposit_style.jsonl (empty),
                     deposit_description_full.csv, crosswalk_lcommodity.csv, _coverage.json

WA rows carry no deposit-type / genetic classification and no ages, so DepositStyle
and DepositAge are empty. DepositEndowment is commodity-presence only (no grade/tonnage
in the DGER source). sourceId = "WA:<canonical_id>" everywhere.
"""
import csv, json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))
csv.field_size_limit(10_000_000)

def rows(n):
    with open(os.path.join(HERE, n), encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ---- LCommodity crosswalk: DB commodities.commodity_name == LCommodity.name (1:1) ----
lcomm = json.load(open(os.path.join(HERE, "ref_LCommodity.json"), encoding="utf-8"))
lc_by_name = {r["name"].strip().lower(): r["id"] for r in lcomm}

base = rows("wa_base.csv")
minerals = {r["canonical_id"]: r["minerals"] for r in rows("wa_mineralogy.csv")}
comm = collections.defaultdict(list)
for r in rows("wa_commodities.csv"):
    comm[r["canonical_id"]].append(r)

# emit the id crosswalk actually used
xw_seen, xw_rows, xw_missing = {}, [], set()
for cid, cname, _sym, _cat in {(r["commodity_id"], r["commodity_name"], "", "") for rs in comm.values() for r in rs}:
    lid = lc_by_name.get(cname.strip().lower())
    xw_seen[cid] = lid
    xw_rows.append((cid, cname, lid or ""))
    if lid is None:
        xw_missing.add(cname)
with open(os.path.join(OUT, "crosswalk_lcommodity.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["db_commodity_id", "db_commodity_name", "ls_commodity_id"])
    for row in sorted(xw_rows, key=lambda x: int(x[0])): w.writerow(row)

cov = collections.Counter()
dep_out, endow_out = [], []
desc_full = {}

for r in base:
    cid = r["canonical_id"]
    sid = f"WA:{cid}"
    cov["deposits"] += 1
    lat = float(r["latitude"]); lon = float(r["longitude"])
    prec = int(r["lat_lon_precision_m"]) if r["lat_lon_precision_m"] else 2000
    name = (r["name"] or "").strip() or f"Unnamed DGER site {cid}"

    district = (r["mining_district"] or "").strip()
    county = (r["county"] or "").strip()
    srcs = (r["sources"] or "").replace("+", ", ")

    # Deposit.description — compact, <=255, identity first (name is separately unique-suffixed by loader)
    short = " | ".join(x for x in [
        (county + " County, WA") if county else "Washington, USA",
        (district + " mining district") if district else None,
        "DGER sources: " + srcs,
    ] if x)
    dep_out.append({
        "name": name, "lat": lat, "lon": lon, "latLonPrecision": prec,
        "description": short[:255], "sourceId": sid,
    })

    # full description sidecar — the curated free text already assembled (flat) in the
    # DB (locations.comments = provenance/aliases/location notes; deposits.comments =
    # DGER comments / value / ore minerals). Drop the internal sourceId marker.
    import re as _re
    def flat(s):
        s = " ".join((s or "").split())
        return _re.sub(r"\s*\|\s*LithoSurfer sourceId: \S+\s*$", "", s).strip()
    lc, dcm = flat(r["location_comments"]), flat(r["deposit_comments"])
    desc_full[cid] = " | ".join(x for x in (lc, dcm) if x)

    # DepositEndowment — commodity presence
    seen = set()
    prim = False
    for c in comm.get(cid, []):
        lid = xw_seen.get(c["commodity_id"])
        if lid is None or lid in seen:
            if lid is None: cov["commodity_not_in_lcommodity"] += 1
            continue
        seen.add(lid)
        role = c["commodity_role"]
        if role == "PRIMARY": prim = True
        endow_out.append({
            "commodityId": lid,
            "commodityName": c["commodity_name"],
            "comment": f"Commodity present (DGER: {srcs}); role {role}",
            "sourceId": sid,
        })
    if seen:
        cov["deposits_with_commodity"] += 1
        cov["endowment_rows"] += len(seen)
    else:
        cov["deposits_without_commodity"] += 1
    if prim: cov["deposits_with_primary_commodity"] += 1

def dump(name, arr):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for o in arr:
            f.write(json.dumps({k: v for k, v in o.items() if v is not None}, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(arr)}")

dump("deposit.jsonl", dep_out)
dump("deposit_endowment.jsonl", endow_out)
dump("deposit_style.jsonl", [])   # empty — WA has no deposit-type classification
dump("deposit_age.jsonl", [])     # empty — WA has no ages

with open(os.path.join(OUT, "deposit_description_full.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["canonical_id", "description_full"])
    for k in sorted(desc_full, key=int): w.writerow([k, desc_full[k]])

json.dump(dict(cov), open(os.path.join(OUT, "_coverage.json"), "w"), indent=2)
print("\ncoverage:")
for k, v in sorted(cov.items()): print(f"  {k}: {v}")
if xw_missing:
    print("\nWARNING commodities with no LCommodity match:", sorted(xw_missing))
