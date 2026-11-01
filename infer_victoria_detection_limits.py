#!/usr/bin/env python3
"""Infer below-detection-limit values for Resources Victoria Soil element
results that have qualifier_code='<' but no numeric value anywhere in the
source (confirmed: both analytical_results.value and
analytical_results.lower_detection_limit are NULL for all 94,737 such
rows - this is a genuine source-data gap, not an import artifact).

Source: D:\\CriticalMineralsDB\\Victoria\\...\\gsiteassay.txt (pipe-delimited,
~56MB), confirmed via spot-check to be keyed by:
  gcSampleId  == samples.samplenumber
  quantType   == element full name (Gold, Arsenic, ...) -> mapped to symbol
  unitCd      == unit code (ppb, ppm, %, ...)
  bdlFlag='Y' + blank quantVal == our qualifier_code='<' + null value rows
  batchSampleId + batchSeqId   == the analytical batch grouping

Standard geochemistry convention (confirmed with user): within one
analytical batch, the instrument/method detection limit for a given
element+unit is constant, so it can be inferred as the minimum
*quantified* (non-BDL) value reported for that same
(batchSampleId, batchSeqId, element, unit) group.

Output: victoria_inferred_dl.tsv - one row per (samplenumber, element,
unit) BDL record that got a group with at least one real value, with the
inferred detection limit. Rows whose entire batch/element/unit group has
no quantified value anywhere (all-BDL group) are reported separately as
unresolvable - no inference possible there, no way around that gap.

Usage: python infer_victoria_detection_limits.py
"""

import csv
import sys

sys.stdout.reconfigure(line_buffering=True)

SRC_PATH = r"D:\CriticalMineralsDB\Victoria\G171397_2010_GSV_Databases\G171397_2010_GSV_Databases\Databases\Geochemistry\ASCII Database Tables\gsiteassay.txt"

# Standard element full-name -> symbol. Includes the two odd source labels
# seen ("Zirconium assay", "Titanium assay", "Phosphur" - a source typo for
# Phosphorus) alongside the plain names.
NAME_TO_SYMBOL = {
    "Gold": "Au", "Arsenic": "As", "Copper": "Cu", "Zinc": "Zn", "Lead": "Pb",
    "Nickel": "Ni", "Silver": "Ag", "Cobalt": "Co", "Antimony": "Sb",
    "Molybdenum": "Mo", "Manganese": "Mn", "Iron": "Fe", "Chromium": "Cr",
    "Bismuth": "Bi", "Tungsten": "W", "Vanadium": "V", "Cadmium": "Cd",
    "Tin": "Sn", "Palladium": "Pd", "Barium": "Ba", "Phosphur": "P",
    "Phosphorus": "P", "Uranium": "U", "Mercury": "Hg", "Platinum": "Pt",
    "Tellurium": "Te", "Strontium": "Sr", "Zirconium assay": "Zr",
    "Zirconium": "Zr", "Magnesium": "Mg", "Rubidium": "Rb", "Sulphur": "S",
    "Sulfur": "S", "Titanium assay": "Ti", "Titanium": "Ti", "Thorium": "Th",
    "Calcium": "Ca", "Carbon": "C", "Lithium": "Li", "Potassium": "K",
    "Sodium": "Na", "Niobium": "Nb", "Lanthanum": "La", "Selenium": "Se",
    "Gallium": "Ga", "Cerium": "Ce", "Fluorine": "F", "Praseodymium": "Pr",
    "Samarium": "Sm", "Neodymium": "Nd", "Europium": "Eu", "Beryllium": "Be",
    "Yttrium": "Y", "Gadolinium": "Gd", "Thallium": "Tl", "Ruthenium": "Ru",
    "Holmium": "Ho", "Hafnium": "Hf", "Scandium": "Sc", "Germanium": "Ge",
    "Bromine": "Br", "Erbium": "Er", "Dysprosium": "Dy", "Tantalum": "Ta",
    "Cesium": "Cs", "Caesium": "Cs", "Rhenium": "Re", "Lutetium": "Lu",
    "Terbium": "Tb", "Thulium": "Tm", "Ytterbium": "Yb", "Chlorine": "Cl",
    "Indium": "In", "Iodine": "I", "Iridium": "Ir", "Rhodium": "Rh",
    "Osmium": "Os", "Hydrogen": "Hydrogen",  # pH rows - excluded downstream anyway
    "Aluminium": "Al", "Aluminum": "Al", "Boron": "B", "Neodynium": "Nd",
}


def to_float(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main():
    print("Pass 1: scanning gsiteassay.txt for real (non-BDL) values per batch/element/unit group...")
    group_min = {}  # (batchSampleId, batchSeqId, symbol, unitCd) -> min real value
    n_rows = 0
    n_real = 0
    n_bdl_blank = 0
    unmapped_names = set()

    with open(SRC_PATH, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader)
        idx = {name: i for i, name in enumerate(header) if name}
        for row in reader:
            n_rows += 1
            if n_rows % 2_000_000 == 0:
                print(f"  ...{n_rows:,} rows scanned", flush=True)
            if len(row) <= max(idx.values()):
                continue
            quant_type = row[idx["quantType"]]
            symbol = NAME_TO_SYMBOL.get(quant_type)
            if symbol is None or symbol == "Hydrogen":
                if symbol is None:
                    unmapped_names.add(quant_type)
                continue
            unit_cd = row[idx["unitCd"]]
            bdl_flag = row[idx["bdlFlag"]]
            quant_val = to_float(row[idx["quantVal"]])
            batch_key = (row[idx["batchSampleId"]], row[idx["batchSeqId"]], symbol, unit_cd)

            if bdl_flag == "Y" and quant_val is None:
                n_bdl_blank += 1
                continue
            if quant_val is not None:
                n_real += 1
                cur = group_min.get(batch_key)
                if cur is None or quant_val < cur:
                    group_min[batch_key] = quant_val

    print(f"\nTotal rows: {n_rows:,}, real values: {n_real:,}, blank-BDL rows: {n_bdl_blank:,}")
    print(f"Unmapped quantType names: {sorted(unmapped_names)}")
    print(f"Distinct batch/element/unit groups with at least one real value: {len(group_min):,}")

    print("\nPass 2: resolving each BDL/blank row's inferred detection limit and writing output...")
    out_rows = []
    n_resolved = 0
    n_unresolved = 0
    unresolved_groups = set()

    with open(SRC_PATH, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader)
        idx = {name: i for i, name in enumerate(header) if name}
        for row in reader:
            if len(row) <= max(idx.values()):
                continue
            quant_type = row[idx["quantType"]]
            symbol = NAME_TO_SYMBOL.get(quant_type)
            if symbol is None or symbol == "Hydrogen":
                continue
            bdl_flag = row[idx["bdlFlag"]]
            quant_val = to_float(row[idx["quantVal"]])
            if not (bdl_flag == "Y" and quant_val is None):
                continue
            unit_cd = row[idx["unitCd"]]
            batch_key = (row[idx["batchSampleId"]], row[idx["batchSeqId"]], symbol, unit_cd)
            inferred = group_min.get(batch_key)
            gc_sample_id = row[idx["gcSampleId"]]
            if inferred is None:
                n_unresolved += 1
                unresolved_groups.add(batch_key)
                continue
            n_resolved += 1
            batch_sample_id, batch_seq_id = batch_key[0], batch_key[1]
            out_rows.append((gc_sample_id, symbol, unit_cd, inferred, batch_sample_id, batch_seq_id))

    print(f"\nResolved: {n_resolved:,} rows (via {len(group_min):,} groups)")
    print(f"Unresolved (whole batch/element/unit group is 100% BDL, no real value anywhere): {n_unresolved:,} rows across {len(unresolved_groups):,} groups")

    with open("victoria_inferred_dl.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["samplenumber", "element_symbol", "unitCd", "inferred_detection_limit", "batchSampleId", "batchSeqId"])
        for r in out_rows:
            w.writerow(r)

    print("Wrote victoria_inferred_dl.tsv")


if __name__ == "__main__":
    main()
