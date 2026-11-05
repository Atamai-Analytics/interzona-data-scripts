"""Flatten the CDoGS per-quantity spreadsheets (qtyNNNNN.xlsx, one per analysed quantity across all surveys) into one CSV.

Hyperlink formulas ('=HYPERLINK("url", "text")') are reduced to their text. Every row is kept here (filtering happens in the loader), with the
quantity id added. Output: <dir>/cdogs_values.csv
Usage: python cdogs_flatten.py D:/CriticalMineralsDB/Canada/NRCan_CDoGS
"""
import csv, os, re, sys, glob, time
from multiprocessing import Pool
import openpyxl

COLS = ["qty_id", "lat", "lon", "sample_type", "prep", "decomposition", "technique", "method_id", "bundle", "project", "survey", "lab_sample_type",
        "value_text", "value_negdl", "site_key", "field_key", "lab_key", "lab_sample_id", "lab_sample_id_alt", "repeat_index"]
LINK = re.compile(r'^=HYPERLINK\(".*?",\s*"(.*)"\)$', re.S)


def txt(v):
    if isinstance(v, str):
        m = LINK.match(v)
        return m.group(1) if m else v
    return v


def one(path):
    qid = int(re.search(r"qty(\d+)", path).group(1))
    out = path.replace(".xlsx", ".csv.part")
    n = 0
    wb = openpyxl.load_workbook(path, read_only=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            h = next(it)
            ix = {k: i for i, k in enumerate(h)}
            for r in it:
                g = lambda k: txt(r[ix[k]]) if k in ix else None
                w.writerow([qid, g("Latitude_NAD83"), g("Longitude_NAD83"), g("SampleType"), g("PrepMethod"), g("Decomposition"), g("Technique"),
                            g("Method"), g("BundleKey"), g("ProjectKey"), g("SurveyKey"), g("Lab_Sample_Type_ID"), g("Analytical_Value_Text"),
                            g("Analytical_Value_NegativeDL"), g("Site_Key"), g("Field_Key"), g("Lab_Key"), g("Lab_Sample_Identifier"),
                            g("Lab_Sample_Identifier_Alt"), g("Repeat_Index")])
                n += 1
    wb.close()
    return qid, n


if __name__ == "__main__":
    root = sys.argv[1]
    files = sorted(glob.glob(os.path.join(root, "qty", "qty*.xlsx")), key=os.path.getsize, reverse=True)
    t0 = time.time()
    with Pool(6) as p:
        res = p.map(one, files, chunksize=1)
    with open(os.path.join(root, "cdogs_values.csv"), "w", newline="", encoding="utf-8") as fo:
        fo.write(",".join(COLS) + "\n")
        for f in files:
            part = f.replace(".xlsx", ".csv.part")
            with open(part, encoding="utf-8") as fi:
                for line in fi: fo.write(line)
            os.remove(part)
    print("files", len(res), "rows", sum(n for _, n in res), "in", round(time.time() - t0), "s")
