# Finland Rock: where the "490 missing samples" went

Checked 2026-10-04 against `FINRock.xlsx` (GTK Rock Geochemical Database of Finland, 6,544 samples), the
`criticialmineralsexp` database and LithoSurfer package 244688701 (6,054 samples).

**6,544 published − 6,054 in LithoSurfer = 490 = 375 + 128 − 13**

| Group | Samples | What happened |
|---|---|---|
| **A. Flagged `DUPLICATE$ = 'D'`** | 375 | **Never in the database.** The GTK manual defines `D` as "a field duplicate sample was taken at this site" — it marks a *normal* sample, not a duplicate row. Each is its own site (none share coordinates with another row; 373 are outcrop samples), has coordinates, and carries a full analysis (88 analyte columns, avg 87.9 values — identical to unflagged rows). 100% of the samples absent from the database carry the flag, so the earlier ingestion into `criticialmineralsexp` evidently dropped every `D` row, treating the flag as "this row is a duplicate". They exist only in the GTK source files (no staging table). |
| **B. Wrong sample-type filter** | 128 | **In the database with all 7 GTK rock methods** (175X, 511P, 511U, 521U, 707I, 811L, 816L — 128 samples each) and matching map-sheet names, but typed *Grab Rock Sample* (104) or *Float Rock Sample* (24) instead of *Outcrop Sample*. They are the source's `SAMTYPE$` = R (block field) and L (boulder) samples. The LithoSurfer extraction selected only sample type 31 (Outcrop), so they were left out. List: `finland_missing_128_other_sample_types.csv`. |
| **C. Extras that should not be there** | −13 | LithoSurfer holds 13 samples that are **not in the rock file**: location name *"Finland regional till samples"*, 5-digit sample numbers (04058 … 35212), only ICP-AES 511P results (286 rows), mis-typed as *Outcrop Sample* in the database, so the type-31 filter pulled them into the rock package. |

Checks done: every source sample number was matched to the database by `samplenumber` across *all* datasources
and sample types (6,041 → outcrop/Finland, 104 → grab, 24 → float, 375 → no match anywhere; no match by
`samplenumberalt` either). One sample number also collides with an NSW soil sample (harmless).

### Why group C is "regional till" data (verified 2026-10-04)
All 13 sample positions, converted to the Finnish YKJ grid, land **within 1 m** of a record in GTK's
`regional_till_geochemistry.xlsx` (sheet `almr_519u_north`) carrying the same `OBSERVATION_NO`. The numbers alone are
ambiguous (`OBSERVATION_NO` repeats across survey years and map sheets: 13 numbers hit 76 rows), but position pins
each one. The matched records are survey years 1982-1986, `SOIL_HORIZON` C, and `MATERIAL` = **weathered bedrock**
(not glacial till as such) - part of the regional till geochemistry survey. Other supporting signs: location name
"Finland regional till samples" (shared by 81,987 till samples), 5-digit observation-style numbers (rock LABNUMs have
8 digits), and only 511P (ICP-AES aqua regia) results. Unexplained: why the database typed these 13 as *Outcrop Sample*.

## Why C matters
Your lawyer's sheet puts GTK's regional till data under the **Basic Licence** (no commercial / AI use), while the rock
data is CC BY 4.0. The 13 till samples sit in a package described as CC BY rock data. They should come out.

## Proposed fixes (nothing has been changed yet)
1. **B (128):** load them into package 244688701 from the database as they are (≈1,000 datapoints, ≈12,000 values);
   map R → "Block field"/grab and L → "Boulder"/float sample kinds as LithoSurfer allows.
2. **A (375):** ingest the 375 rows from `FINRock.xlsx` into `criticialmineralsexp` the way the other 6,041 were
   (samples, locations with converted coordinates, analytical_results), then load them to LithoSurfer.
3. **C (13):** delete the 13 till samples (and their datapoints) from the package; separately fix their sample type in the DB.
4. Afterwards update the package description sentence ("6,544 published; 6,054 in this package") and the
   `lithodat_samples`-style extraction so it does not filter on sample type 31 alone.

Optional: the 375 `Z` laboratory-duplicate analyses described in the manual (Report 164, N/Z pairs) are *not* in
`FINRock.xlsx` as rows; `RGDB_1.1.xls` may hold them if you want the QC pairs.
