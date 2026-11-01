#!/usr/bin/env python3
"""Remove the 13 regional-till-survey samples that were wrongly loaded into LithoSurfer package
244688701 ("GTK: Finland Rock Samples"). They are GTK regional till geochemistry observations
(positions match GTK's regional_till_geochemistry.xlsx to within 1 m) that had been mis-typed
'Outcrop Sample' in criticialmineralsexp; the licence for that survey (Basic Licence) differs from
the CC BY rock data.

ONLY these 13 samples are touched (never deleteByCriteria). For each sample, in this order:
  ElementalConcentration rows (found by aliquotName) -> GCAliquot -> GCDataPoint -> SampleProperty rows -> Sample
Every record is checked to belong to this package / this sample before it is deleted. Each deleted id
is appended to finland_till_removal_log.txt (audit trail).

--dry-run  (default) lists what would be deleted, writes nothing
--only LOCATIONID  restrict to one sample (use for a first test)
--commit   delete
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dump_packages as d

sys.stdout.reconfigure(line_buffering=True)
HERE = Path(__file__).resolve().parent
PACKAGE_ID = 244688701
LOCATION_IDS = [8498221, 8597179, 8234067, 8322531, 8279833, 8169049, 8567644, 8255688, 8635340, 8223324, 8269662, 8294254, 8388645]
LOG = HERE / "finland_till_removal_log.txt"
DUMP = Path(os.environ.get("FINLAND_LS_DUMP", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--only", type=int)
    ap.add_argument("--dump", required=True, help="finland_ls_samples.json from finland_gap_fetch.py")
    a = ap.parse_args()
    d.load_dotenv()
    host = os.environ.get("LITHOSURFER_HOST", "https://api.lithosurfer.io")
    tok = d.request("POST", f"{host}/api/authenticate", body={"username": os.environ["LITHOSURFER_USER"], "password": os.environ["LITHOSURFER_PASSWORD"], "rememberMe": False})["id_token"]
    api = lambda m, p, b=None: d.request(m, host + p, body=b, token=tok)

    samples = json.loads(Path(a.dump).read_text(encoding="utf-8"))
    dp_cache = json.loads((HERE / f"datapoint_ids_{PACKAGE_ID}.json").read_text(encoding="utf-8"))
    dp_cache.pop("__complete__", None)
    targets = [l for l in LOCATION_IDS if (not a.only or l == a.only)]
    totals = {"concentrations": 0, "aliquots": 0, "datapoints": 0, "properties": 0, "samples": 0}

    def delete(kind, path, rid):
        if a.commit:
            api("DELETE", path)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"deleted {kind} {rid}\n")
        totals[kind if kind.endswith("s") else kind + "s"] += 0

    for loc in targets:
        label = f"{loc}//AA 511P [ppm]"
        match = [s for s in samples if str(s["name"]).startswith(f"{loc}//AA")]
        if len(match) != 1:
            raise SystemExit(f"location {loc}: expected exactly 1 sample in the dump, found {len(match)} - stopping")
        sid = match[0]["id"]
        gid = dp_cache.get(label)
        if gid is None:
            raise SystemExit(f"location {loc}: no datapoint id cached for {label!r} - stopping")
        # verify ownership before touching anything
        dp = api("GET", f"/api/geochem/GCDataPoint/{gid}")
        if dp["dataPointDTO"]["sampleId"] != sid or dp["dataPointDTO"]["dataPackageId"] != PACKAGE_ID:
            raise SystemExit(f"location {loc}: datapoint {gid} does not belong to sample {sid} in package {PACKAGE_ID} - stopping")
        q = urllib.parse.quote(label, safe="")
        conc = [c for c in api("GET", f"/api/geochem/ElementalConcentration?aliquotName.contains={q}&size=200") if c.get("aliquotName") == label]
        aliq = [x for x in api("GET", f"/api/geochem/GCAliquot?aliquotName.contains={q}&size=50") if x.get("aliquotName") == label]
        props = api("POST", "/api/core/SampleProperty/post?page=0&size=2000", {"sampleId": {"in": [sid]}}) or []
        print(f"{loc}: sample {sid} | datapoint {gid} (EC count {dp.get('countElementalConcentrations')}) | "
              f"{len(conc)} concentrations, {len(aliq)} aliquots, {len(props)} properties", flush=True)
        if len(conc) != (dp.get("countElementalConcentrations") or 0):
            raise SystemExit(f"location {loc}: found {len(conc)} concentrations but the datapoint reports {dp.get('countElementalConcentrations')} - stopping")
        if not a.commit:
            for k, n in (("concentrations", len(conc)), ("aliquots", len(aliq)), ("datapoints", 1), ("properties", len(props)), ("samples", 1)):
                totals[k] += n
            continue
        for c in conc:
            api("DELETE", f"/api/geochem/ElementalConcentration/{c['id']}"); LOG.open("a").write(f"deleted ElementalConcentration {c['id']}\n"); totals["concentrations"] += 1
        for x in aliq:
            api("DELETE", f"/api/geochem/GCAliquot/{x['id']}"); LOG.open("a").write(f"deleted GCAliquot {x['id']}\n"); totals["aliquots"] += 1
        api("DELETE", f"/api/geochem/GCDataPoint/{gid}"); LOG.open("a").write(f"deleted GCDataPoint {gid}\n"); totals["datapoints"] += 1
        for p in props:
            api("DELETE", f"/api/core/SampleProperty/{p['id']}"); LOG.open("a").write(f"deleted SampleProperty {p['id']}\n"); totals["properties"] += 1
        api("DELETE", f"/api/core/sample-with-locations/{sid}"); LOG.open("a").write(f"deleted Sample {sid}\n"); totals["samples"] += 1
        print(f"   -> removed sample {sid} and its children", flush=True)
    print(("COMMIT" if a.commit else "DRY RUN (nothing deleted)") + " totals:", totals)


if __name__ == "__main__":
    main()
