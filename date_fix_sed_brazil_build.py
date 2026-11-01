import openpyxl, pandas as pd, datetime as dt
SP = r"C:/Users/dean/AppData/Local/Temp/claude/C--Users-dean-claude-lithosurfer/129b4d4e-cfc2-4303-8a93-af4691c973fe/scratchpad"
# ---------- Finland stream sediment (minSed) ----------
db = pd.read_csv(SP + "/fi_minsed_samples.csv")
db["sampledate"] = pd.to_datetime(db.sampledate, errors="coerce")
print("minSed samples in DB:", len(db), "| dated:", int(db.sampledate.notna().sum()), "| unique samplenumbers:", db.samplenumber.nunique())
base = r"D:/CriticalMineralsDB/Finland/regional_stream_sediment_etrs_tm35fin_xlsx/"
rows = []
for fname, col in (("mineral_samples_a61.xlsx", "DATE_A61"), ("mineral_samples_p62.xlsx", "DATE_P62")):
    ws = openpyxl.load_workbook(base + fname, read_only=True, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True); hdr = list(next(it))
    ci, ii = hdr.index(col), hdr.index("ID_NUMBER")
    for r in it:
        v = r[ci]
        if v in (None, ""): continue
        s = (str(int(v)) if not isinstance(v, str) else v.strip()).zfill(8)
        try: rows.append((str(r[ii]).strip(), dt.datetime(int(s[4:8]), int(s[2:4]), int(s[0:2])), fname))
        except Exception: pass
src = pd.DataFrame(rows, columns=["samplenumber", "src_date", "file"])
print("source rows with a date:", len(src), "| ids with >1 different date:", int((src.groupby("samplenumber").src_date.nunique() > 1).sum()))
amb = set(src.groupby("samplenumber").src_date.nunique().loc[lambda s: s > 1].index)
src = src[~src.samplenumber.isin(amb)].drop_duplicates("samplenumber")
dbu = db[~db.samplenumber.duplicated(keep=False)]               # unique sample numbers only (unambiguous join)
m = dbu.merge(src, on="samplenumber")
m = m[m.sampledate.notna()].copy()
m["diff"] = (m.sampledate - m.src_date).dt.days
print("matched:", len(m), "| diff distribution:", m["diff"].value_counts().head(5).to_dict())
fix = m[m["diff"] == -1]
print("exactly -1 day (will shift +1):", len(fix), "| other mismatches left alone:", len(m) - len(fix))
fix[["sampleid", "samplenumber", "sampledate", "src_date"]].assign(new_date=lambda d: d.src_date.dt.date).to_csv(SP + "/date_fix_minsed.csv", index=False)
# ---------- Brazil ----------
b = pd.read_csv(SP + "/br_samples.csv"); b["sampledate"] = pd.to_datetime(b.sampledate, errors="coerce")
print("\nBrazil DB samples:", len(b), "| dated:", int(b.sampledate.notna().sum()), "| example:", b.head(2)[["samplenumber", "locationcode", "locationname"]].to_dict("records"))
s = pd.read_csv(r"D:/CriticalMineralsDB/Brazil/Noroeste_de_Rondonia.csv", encoding="latin1", low_memory=False, usecols=["Num_Lab", "Num_Campo", "DtVisita"])
s["DtVisita"] = pd.to_datetime(s.DtVisita, errors="coerce")
for key in ("Num_Lab", "Num_Campo"):
    j = b.assign(k=b.samplenumber.astype(str).str.strip()).merge(s.assign(k=s[key].astype(str).str.strip()).drop_duplicates("k"), on="k")
    print(f"  join DB.samplenumber = {key}: {len(j)} matches")
    if len(j) > 1000:
        j["diff"] = (j.sampledate - j.DtVisita).dt.days
        print("   diff distribution:", j["diff"].value_counts().head(5).to_dict())
        fixb = j[j["diff"] == -1]
        print("   exactly -1 day:", len(fixb))
        fixb[["sampleid", "samplenumber", "sampledate", "DtVisita"]].assign(new_date=lambda d: d.DtVisita.dt.date).to_csv(SP + "/date_fix_brazil.csv", index=False)
        break
