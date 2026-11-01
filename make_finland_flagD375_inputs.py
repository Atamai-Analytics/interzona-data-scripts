#!/usr/bin/env python3
"""Prepare the loader inputs for the 375 GTK rock samples flagged DUPLICATE$='D' (ingested into
criticialmineralsexp on 2026-10-04, tag claude_finland_flagD_20261004).

Same approach as make_finland_extra128_inputs.py:
1. Writes load_finland_flagD375_samples.py - copy of load_finland_samples.py reading finland_samples_flagD375.tsv,
   own checkpoint (finland_flagD375_sample_progress.txt), session id <date>-finland-flagD375 and
   locationKindId by source SAMTYPE$ (P outcrop 60556, R block field -> Other 60551, L boulder 287903).
2. Writes gcdp_finland_rock_flagD375.tsv = exported datapoint rows + nominal sampleweightgm / digestionnotes.
"""
import csv
from pathlib import Path

import update_finland_digestion_notes as notes
import update_finland_sample_weight as base

HERE = Path(__file__).resolve().parent
SCRATCH = Path(r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/7e27489a-eae3-4aec-bb30-ae7938a2e666/scratchpad")

src = (HERE / "load_finland_samples.py").read_text(encoding="utf-8")
patches = [
    ('TSV_PATH = HERE / "finland_samples.tsv"', 'TSV_PATH = HERE / "finland_samples_flagD375.tsv"'),
    ('checkpoint_path = HERE / "finland_sample_progress.txt"', 'checkpoint_path = HERE / "finland_flagD375_sample_progress.txt"'),
    ('base_session_id = f"{date.today():%Y%m%d}-finland"', 'base_session_id = f"{date.today():%Y%m%d}-finland-flagD375"'),
    ('LOCATION_KIND_ID = 60556', 'LOCATION_KIND_ID = 60556  # unused here: see LOCATION_KIND_BY_SAMTYPE\nLOCATION_KIND_BY_SAMTYPE = {"P": 60556, "L": 287903, "R": 60551}  # P outcrop; L boulder -> Boulder; R block field -> Other'),
    ('"locationKindId": LOCATION_KIND_ID,', '"locationKindId": LOCATION_KIND_BY_SAMTYPE[row["src_samtype"]],'),
]
for old, new in patches:
    assert src.count(old) == 1, f"patch target not found exactly once: {old!r}"
    src = src.replace(old, new)
src = src.replace('"""Load Samples (+ nested Locations)', '"""[COPY for the 375 DUPLICATE$=D rock samples - see make_finland_flagD375_inputs.py]\nLoad Samples (+ nested Locations)', 1)
(HERE / "load_finland_flagD375_samples.py").write_text(src, encoding="utf-8")
print("wrote load_finland_flagD375_samples.py")

rows = list(csv.DictReader(open(SCRATCH / "gcdp_flagD375_raw.tsv", encoding="utf-8", newline=""), delimiter="\t"))
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
with open(HERE / "gcdp_finland_rock_flagD375.tsv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
    w.writeheader(); w.writerows(rows)
names = [r["datapointName"] for r in rows]
print(f"wrote gcdp_finland_rock_flagD375.tsv: {len(rows)} datapoint rows, {len(set(names))} distinct names, "
      f"{len({r['sampleName'] for r in rows})} samples, methods: {sorted({r['sourcemethodcode'] for r in rows})}")
