#!/usr/bin/env python3
"""Classify the stored GTK 511P results of every Finland rock sample as ICP-AES (stay in 511P) or ICP-MS (-> 308M).

The original ingestion put the 26 *_ICPMS ppm source columns of FINRock.xlsx under package 511P (ICP-AES aqua regia) although
GTK documents them as laboratory method 308M (HF-HClO4 + LiBO2 fusion, ICP-MS, total). Rows are told apart by re-deriving
the expected (analyte, qualifier, value) of every ICPAES / ICPMS column from the source (same rules + rounding as
finland_ingest_rules.py) and matching the stored 511P rows:
  * (analyte, qual, value) expected only from ICPMS  -> MOVE the stored row to 308M
  * expected only from ICPAES                         -> stays
  * expected from BOTH (identical numbers; the original ingestion collapsed identical rows into ONE) -> stored row stays in
    511P and a copy is INSERTED into 308M (so both methods hold their value)
Anything that does not reconcile is reported (and must be zero before applying).

Writes (scratchpad): icpms_move.csv, icpms_dup.csv, icpms_analysis_summary.json
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finland_ingest_rules as R

SP = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/7e27489a-eae3-4aec-bb30-ae7938a2e666/scratchpad")


def method_of(col):
    unit = col.split()[-1]
    stem = col[: -len(unit)].strip()
    el, _, m = stem.partition("_")
    return el, m, unit


def main():
    rows, acols = R.read_source()
    src = {str(int(r["LABNUM"])): r for r in rows}
    cols_ms = [c for c in acols if method_of(c)[1] == "ICPMS"]
    cols_aes = [c for c in acols if method_of(c)[1] == "ICPAES"]
    print(f"source rows {len(src)}; ICPMS cols {len(cols_ms)}, ICPAES cols {len(cols_aes)}")

    db = defaultdict(list)       # samplenumber -> list of dict rows (511P, ppm)
    codes = {}
    for r in csv.DictReader(open(SP / "res511_all.csv", encoding="utf-8")):
        db[r["samplenumber"]].append(r)
        codes[r["analyte_code"].upper()] = r["analyte_code"]
    print(f"db samples with 511P rows {len(db)}; analyte codes known {len(codes)}")

    move, dup = [], []
    stats = Counter(); problems = []
    per_analyte_ms = Counter()
    for sn, rws in db.items():
        s = src.get(sn)
        if s is None:
            stats["sample_not_in_source"] += 1; problems.append(("sample_not_in_source", sn)); continue
        exp = defaultdict(set)    # key -> {'AES','MS'}
        for tag, cols in (("AES", cols_aes), ("MS", cols_ms)):
            for c in cols:
                el, m, unit = method_of(c)
                code = codes.get(el.upper())
                pv = R.parse_value(s[c])
                if pv[0] == "skip":
                    continue
                if code is None:
                    problems.append(("no_code", sn, c)); continue
                exp[(code, unit, pv[1], pv[2])].add(tag)
        stored = Counter()
        by_key = {}
        for r in rws:
            q = int(r["qualifier_id"]) if r["qualifier_id"] else None
            k = (r["analyte_code"], r["unitcode"], q, float(r["value"]))
            stored[k] += 1
            by_key[k] = r
        if set(stored) != set(exp) or any(v != 1 for v in stored.values()):
            stats["sample_mismatch"] += 1
            if len(problems) < 25:
                problems.append(("mismatch", sn, [k for k in exp if k not in stored][:3], [k for k in stored if k not in exp][:3], [k for k, v in stored.items() if v != 1][:3]))
            continue
        stats["sample_ok"] += 1
        for k, tags in exp.items():
            r = by_key[k]
            if tags == {"MS"}:
                move.append(r); per_analyte_ms[k[0]] += 1
            elif tags == {"AES", "MS"}:
                dup.append(r); per_analyte_ms[k[0]] += 1
    out = ["result_id", "sampleid", "samplenumber", "locationid", "analyte_code", "unitcode", "qualifier_id", "value", "isactive", "package_id"]
    for name, lst in (("icpms_move.csv", move), ("icpms_dup.csv", dup)):
        with open(SP / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=out); w.writeheader(); w.writerows(lst)
    summ = {"samples_ok": stats["sample_ok"], "samples_mismatch": stats["sample_mismatch"], "other": {k: v for k, v in stats.items() if k not in ("sample_ok", "sample_mismatch")},
            "rows_to_move": len(move), "rows_to_duplicate": len(dup), "moves_inactive": sum(1 for r in move if r["isactive"] != "t"),
            "dups_inactive": sum(1 for r in dup if r["isactive"] != "t"), "samples_with_ms": len({r["sampleid"] for r in move + dup}),
            "per_analyte_ms": dict(per_analyte_ms), "problems_first": problems[:10]}
    (SP / "icpms_analysis_summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
