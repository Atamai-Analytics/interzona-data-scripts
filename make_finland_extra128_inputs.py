#!/usr/bin/env python3
"""Prepare the loader inputs for the 128 GTK grab/float rock samples (sample types 26 / 30).

1. Writes load_finland_extra_samples.py - a copy of load_finland_samples.py that
   * reads finland_samples_extra128.tsv and uses its own checkpoint (finland_extra128_sample_progress.txt)
   * sets locationKindId per sample from the source SAMTYPE$ (L = boulder -> 'Boulder' 287903;
     R = block field -> 'Other' 60551; LithoSurfer has no 'block field' location kind)
   * uses session id <date>-finland-extra128 in sample names
2. Writes gcdp_finland_rock_extra128.tsv = the exported datapoint rows with the documented nominal
   sampleweightgm and digestionnotes filled in (same values/notes as the 48,328 existing Finland datapoints).
"""
import csv
import re
from pathlib import Path

import update_finland_digestion_notes as notes
import update_finland_sample_weight as base

HERE = Path(__file__).resolve().parent
SCRATCH = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/7e27489a-eae3-4aec-bb30-ae7938a2e666/scratchpad")

# ---- 1. sample loader copy ------------------------------------------------------------------------
src = (HERE / "load_finland_samples.py").read_text(encoding="utf-8")
patches = [
    ('TSV_PATH = HERE / "finland_samples.tsv"', 'TSV_PATH = HERE / "finland_samples_extra128.tsv"'),
    ('checkpoint_path = HERE / "finland_sample_progress.txt"', 'checkpoint_path = HERE / "finland_extra128_sample_progress.txt"'),
    ('base_session_id = f"{date.today():%Y%m%d}-finland"', 'base_session_id = f"{date.today():%Y%m%d}-finland-extra128"'),
    ('LOCATION_KIND_ID = 60556', 'LOCATION_KIND_ID = 60556  # unused here: see LOCATION_KIND_BY_SAMTYPE\nLOCATION_KIND_BY_SAMTYPE = {"L": 287903, "R": 60551}  # L boulder -> Boulder; R block field -> Other'),
    ('"locationKindId": LOCATION_KIND_ID,', '"locationKindId": LOCATION_KIND_BY_SAMTYPE[row["src_samtype"]],'),
]
for old, new in patches:
    assert src.count(old) == 1, f"patch target not found exactly once: {old!r}"
    src = src.replace(old, new)
src = src.replace('"""Load Samples (+ nested Locations)', '"""[COPY for the 128 grab/float rock samples - see make_finland_extra128_inputs.py]\nLoad Samples (+ nested Locations)', 1)
(HERE / "load_finland_extra_samples.py").write_text(src, encoding="utf-8")
print("wrote load_finland_extra_samples.py")

# ---- 2. datapoint TSV with weights + notes ---------------------------------------------------------
rows = list(csv.DictReader(open(SCRATCH / "gcdp_extra128_raw.tsv", encoding="utf-8", newline=""), delimiter="\t"))
fields = list(rows[0].keys())
unknown = set()
for r in rows:
    code = r["sourcemethodcode"]
    if code not in base.WEIGHTS_G:
        unknown.add(code); continue
    assert not (r["sampleweightgm"] or "").strip() and not (r["digestionnotes"] or "").strip(), "unexpected existing weight/notes"
    r["sampleweightgm"] = f"{base.WEIGHTS_G[code]:g}"
    r["digestionnotes"] = notes.NOTES[code]
assert not unknown, f"methods without a documented charge: {unknown}"
with open(HERE / "gcdp_finland_rock_extra128.tsv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
    w.writeheader(); w.writerows(rows)
names = [r["datapointName"] for r in rows]
print(f"wrote gcdp_finland_rock_extra128.tsv: {len(rows)} datapoint rows, {len(set(names))} distinct names, "
      f"{len({r['sampleName'] for r in rows})} samples, methods: {sorted({r['sourcemethodcode'] for r in rows})}")
