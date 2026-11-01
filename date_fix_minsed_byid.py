import openpyxl, pandas as pd, datetime as dt
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
db = pd.read_csv(SP + "/fi_minsed_samples.csv")
db["sampledate"] = pd.to_datetime(db.sampledate, errors="coerce")
db["src_id"] = db.locationcode.str.split("_").str[1]                  # minSed_<ID>_<ID_NUMBER>
print("DB minSed:", len(db), "| dated:", int(db.sampledate.notna().sum()), "| unique src_id:", db.src_id.nunique(), "| sample rows sharing a src_id:", int(db.src_id.duplicated(keep=False).sum()))
base = r"D:/CriticalMineralsDB/Finland/regional_stream_sediment_etrs_tm35fin_xlsx/"
rows = []
for fname, col in (("mineral_samples_a61.xlsx", "DATE_A61"), ("mineral_samples_p62.xlsx", "DATE_P62")):
    ws = openpyxl.load_workbook(base + fname, read_only=True, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True); hdr = list(next(it))
    ci, ii = hdr.index(col), hdr.index("ID")
    for r in it:
        v = r[ci]
        if v in (None, ""): continue
        s = (str(int(v)) if not isinstance(v, str) else v.strip()).zfill(8)
        try: rows.append((str(r[ii]).strip(), dt.datetime(int(s[4:8]), int(s[2:4]), int(s[0:2])), fname))
        except Exception: pass
src = pd.DataFrame(rows, columns=["src_id", "src_date", "file"])
conflict = set(src.groupby("src_id").src_date.nunique().loc[lambda s: s > 1].index)
print("source ids:", src.src_id.nunique(), "| ids with conflicting dates:", len(conflict))
src = src[~src.src_id.isin(conflict)].drop_duplicates("src_id")
m = db.merge(src, on="src_id")                                        # every DB sample is verified on its own; m = m[m.sampledate.notna()].copy()
m["diff"] = (m.sampledate - m.src_date).dt.days
print("matched on ID:", len(m), "| diff distribution:", m["diff"].value_counts().head(6).to_dict())
fix = m[m["diff"] == -1]
print("exactly -1 day (will shift +1):", len(fix), "| other (left alone):", len(m) - len(fix))
dated_left = db[db.sampledate.notna() & ~db.sampleid.isin(fix.sampleid)]
print("dated DB minSed samples NOT verified/shifted:", len(dated_left), "(shared ids / conflicting or missing source dates)")
fix[["sampleid", "samplenumber", "sampledate", "src_date"]].assign(new_date=lambda d: d.src_date.dt.date).to_csv(SP + "/date_fix_minsed.csv", index=False)
