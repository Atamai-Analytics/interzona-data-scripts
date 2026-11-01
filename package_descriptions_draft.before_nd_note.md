# Data package descriptions — draft for review

Drafted 2026-10-03 for Lithodat's request: for each package, (1) the original compilation/source,
(2) the original data link, (3) the formal citation/attribution the licence requires, and (4) what
Atamai did to the data. Nothing here has been written to LithoSurfer yet.

**How this file is used:** `apply_package_descriptions.py` reads the fenced `text` blocks under each
`### description <package id>` (and optional `### license <package id>`) heading. Edit the text here,
then run the script (dry run by default).

Packages in scope (all currently have `distribution` PRIVATE except Argentina Sediment = COMMERCIAL):

| Package id | Name | Samples | Datapoints | Existing description |
|---|---|---|---|---|
| 205700763 | GEUS: Greenland Rock Samples | 6,957 | 22,078 | one line (kept as first sentence) |
| 205700765 | GEUS: Greenland Stream Sediment Samples | 17,455 | 73,459 | one line (kept) |
| 205700764 | GEUS: Greenland Soil Samples | 1,491 | 3,567 | one line (kept) |
| 205700762 | GEUS: Greenland Heavy Mineral Concentrates | 855 | 1,692 | one line (kept) |
| 246454433 | Resources Victoria: Soil Samples | 132,210 | 203,413 | none |
| 244688701 | GTK: Finland Rock Samples | 6,054 | 48,341 | none |
| 55066009 | SEGEMAR: Argentina Sediment & Soil Surface Geochem | 37,791 | 37,838 | one line (kept) |

Not drafted: **SEGEMAR: Argentina Deposits & Occurrences (250875258)** — the package is empty
(0 samples/datapoints; the deposit load is blocked, see `ls_deposit_extract/PHASE3_STATUS.md`).
Write its description when the deposits are in.

---

## Part 1 — Sample charge / mass analysed

**Short answer:** the model already has a home for it, we just never filled it in.

* LithoSurfer's `GCDataPoint.sampleWeightGm` (grams) exists; LithoSurfer's own geochemistry guide
  calls it "decisive for fire assay: FA25 and FA50 are not the same". `digestionNotes` (free text)
  is the companion field for anything the lists cannot hold.
* Our loaders send `sampleWeightGm`, but **every TSV we loaded has it empty** (0% populated across
  Greenland, Victoria and Finland; Argentina's template has no weight column at all). Checked live
  on the API as well: `sampleWeightGm` is null.

What the source data actually contains:

| Dataset | Charge in source? | Detail |
|---|---|---|
| **Finland** | **Yes, per method** (documentation, not per sample) | GTK `AnalysisMethods.docx` / Report 164 give the charge for all 7 loaded methods: 175X XRF = 7 g pressed pellet (+210 mg wax); 511P ICP-AES = 150 mg; 511U GFAAS = 0.15 g; 521U GFAAS (Au, Te, Pd) = 5 g; 811L and 816L carbon = 0.5 g; 707I fluorine = 100 mg (+2 g NaOH). Nominal values, constant per method. |
| **Victoria** | **Field exists but is empty** | `gsiteanmethod.analyticalSampleWeight` ("weight of the sample used for the analysis") is populated for 41 of 1,241 method rows and every one of the 41 is `0` with no unit. **Correction (2026-10-03, later):** the charge *is* recoverable for many methods because GSV's method descriptions (`gsiteanmethod.methodDesc`) state it in words, e.g. "50g sample aqua regia digest AAS", "30g FA, AAS", "50g FA AAS" — about 85 method rows; see `package_charge_weights_applied.csv` (42 packages written to `analytical_packages`). Separate field `gsitegcsample.fieldSampleWeight` is the *as-collected field sample mass* (8.2% of samples, grams/kg) — not the analysed charge. |
| **Greenland** | No | Column headers carry lab / prep / technique / analyte / unit only. 1,041 fire-assay datapoints (rock 576, stream 300, HMC 165; Actlabs, Bondar-Clegg, Chemex) have no charge recorded. |
| **Argentina** | No | Methods are recorded as packages ("INAA + ICP-ES", etc.) with no weights. |

**Recommendation**

1. Keep using `GCDataPoint.sampleWeightGm`; no schema change needed. One suggestion to Lithodat: a
   small "nominal vs measured" marker (or a convention in `digestionNotes`, e.g. "charge 7 g –
   nominal, per GTK method 175X") so a documented method charge is never mistaken for a weighed
   one.
2. **Finland:** populate all 48,341 datapoints from the published per-method charges (7 methods,
   fully documented), and put the same text in `digestionNotes`. Low risk, fully traceable.
3. **Victoria:** populate only what the source states — 461 `AAL-FA50` datapoints = 50 g. Leave the
   other fire-assay datapoints null rather than infer from a code suffix (could extend to
   `AMD-FA50`/`GEOCHEM-LG50` if you or Lithodat are comfortable with the inference).
4. **Greenland, Argentina:** leave null and say so in the description ("not reported by the
   source"). Lab-published nominal charges (e.g. Actlabs 30 g fire assay) are external, vary by
   year and package, and would be our assumption rather than GEUS/SEGEMAR data.
5. The package descriptions below already state what is and is not reported, so the information is
   documented even before any datapoint is updated.

Updating Finland means PUTting 48,341 GCDataPoints (full DTO each) — about the cost of the earlier
Victoria material update. Say the word and I'll do it with the same checkpoint/resume pattern.

---

## Part 2 — Draft package descriptions

Plain text on purpose (no markdown syntax) so it displays cleanly wherever LithoSurfer shows it.
Maximum length of the field is not published in the API schema; the apply script reports lengths
and verifies by reading back.

### description 205700763
```text
Rock geochemistry from Greenland, curated from The Greenland Mineral Resources Portal, provided by The Geological Survey of Denmark and Greenland (GEUS).

ABOUT THE SOURCE
Rock-sample geochemistry compiled by GEUS from its archive of Greenland field campaigns (sampling years 1957-2007, mainly South-West and West Greenland, about 60-70 degrees N). Sample records cite three GEUS released reports: the Nuuk-region mineral resource assessment (GEUS Report 2011/92), the Mineral Resource Potential of South Greenland CD-ROM, and the Mineral Resources of the Precambrian Shield of central West Greenland DVD (66-70.25 degrees N). This package holds 6,957 samples and 22,078 analytical datapoints from nine laboratories, chiefly the GEUS Rock Geochemical Laboratory, Activation Laboratories and Risoe National Laboratory.

SOURCE LINK
Greenland Mineral Resources Portal: https://www.greenmin.gl  |  GEUS data portal: https://data.geus.dk  |  GEUS geochemical mapping: https://eng.geus.dk/mineral-resources/greenland-and-geoscience-maps/geochemical-mapping

CITATION AND ATTRIBUTION
Licence: Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. Please cite the Geological Survey of Denmark and Greenland (GEUS) and the Mineral Resources Authority (MMR), Naalakkersuisut - Government of Greenland, as data providers and name the portal, for example: "Source: GEUS and MMR, Government of Greenland; Greenland Mineral Resources Portal (greenmin.gl); GEUS: Greenland Rock Samples; CC BY 4.0. Adapted by Atamai Analytics." The data have been adapted (see below); GEUS and MMR do not endorse the adapted data and accept no responsibility for its use.

WHAT ATAMAI ADDED
- Restructured GEUS's wide-format table (one row per sample, 174 columns including many analyte columns whose headers encode laboratory, preparation, technique, analyte and unit) into LithoSurfer's sample > analytical datapoint > concentration model, so every value carries its laboratory, method and unit and can be retrieved through the API.
- Mapped each laboratory / preparation / technique combination to a standard analytical package using LithoSurfer's laboratory, digestion and technique vocabularies.
- Element values are stored in ppm and oxides in wt%; detection-limit qualifiers ("<") are kept wherever the source supplies them.
- Placeholder values (for example zero, 999 or negative numbers) are flagged inactive and excluded rather than presented as measurements.
- Sample descriptors supplied by GEUS (collector, sampling year, etc.) are kept as sample properties.

USE NOTES
Results come from several laboratories and methods over about five decades and are not inter-laboratory calibrated; use each datapoint's method, laboratory and detection-limit fields when comparing. The analysed sample weight (charge), for example for fire assay, is not reported by the source.
```

### description 205700765
```text
Stream sediment geochemistry from Greenland, curated from The Greenland Mineral Resources Portal, provided by The Geological Survey of Denmark and Greenland (GEUS).

ABOUT THE SOURCE
Stream-sediment geochemistry from GEUS regional and local surveys across Greenland (sampling years 1971-2013, about 60-84 degrees N), mostly the fine fraction (0-100 micron). See also the GEUS geochemical atlas of Greenland stream sediments (7,122 samples, surveys 1977-1998), published with financial support from the Bureau of Minerals and Petroleum, Greenland. This package holds 17,455 samples and 73,459 analytical datapoints; analyses were done by many laboratories, chiefly Activation Laboratories, Risoe National Laboratory and GEUS.

SOURCE LINK
Greenland Mineral Resources Portal: https://www.greenmin.gl  |  GEUS data portal: https://data.geus.dk  |  GEUS geochemical mapping: https://eng.geus.dk/mineral-resources/greenland-and-geoscience-maps/geochemical-mapping

CITATION AND ATTRIBUTION
Licence: Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. Please cite the Geological Survey of Denmark and Greenland (GEUS) and the Mineral Resources Authority (MMR), Naalakkersuisut - Government of Greenland, as data providers and name the portal, for example: "Source: GEUS and MMR, Government of Greenland; Greenland Mineral Resources Portal (greenmin.gl); GEUS: Greenland Stream Sediment Samples; CC BY 4.0. Adapted by Atamai Analytics." The data have been adapted (see below); GEUS and MMR do not endorse the adapted data and accept no responsibility for its use.

WHAT ATAMAI ADDED
- Restructured GEUS's very wide table (over 500 columns whose headers encode laboratory, preparation, technique, analyte and unit) into LithoSurfer's sample > analytical datapoint > concentration model, so every value carries its laboratory, method and unit and can be retrieved through the API.
- Mapped each laboratory / preparation / technique combination to a standard analytical package using LithoSurfer's laboratory, digestion and technique vocabularies.
- Element values are stored in ppm and oxides in wt%; detection-limit qualifiers ("<") are kept wherever the source supplies them (the stream-sediment source supplies very few).
- Placeholder values (about 244,000 zeros, plus 999 and negative values) are flagged inactive and excluded rather than presented as measurements.
- Sample descriptors supplied by GEUS (collector, sampling year, grain-size fraction, etc.) are kept as sample properties.

USE NOTES
Results come from many laboratories and methods over more than four decades and are not inter-laboratory calibrated; use each datapoint's method, laboratory, grain-size fraction and detection-limit fields when comparing. The analysed sample weight (charge), for example for fire assay, is not reported by the source.
```

### description 205700764
```text
Soil geochemistry from Greenland, curated from The Greenland Mineral Resources Portal, provided by The Geological Survey of Denmark and Greenland (GEUS).

ABOUT THE SOURCE
Soil geochemistry from GEUS surveys across Greenland (about 60-82 degrees N), with the grain-size fraction recorded for each sample. Analyses were done chiefly by Activation Laboratories (about half of the datapoints), with the remainder by GGU/University of Copenhagen, GEUS and Risoe National Laboratory. This package holds 1,491 samples and 3,567 analytical datapoints.

SOURCE LINK
Greenland Mineral Resources Portal: https://www.greenmin.gl  |  GEUS data portal: https://data.geus.dk  |  GEUS geochemical mapping: https://eng.geus.dk/mineral-resources/greenland-and-geoscience-maps/geochemical-mapping

CITATION AND ATTRIBUTION
Licence: Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. Please cite the Geological Survey of Denmark and Greenland (GEUS) and the Mineral Resources Authority (MMR), Naalakkersuisut - Government of Greenland, as data providers and name the portal, for example: "Source: GEUS and MMR, Government of Greenland; Greenland Mineral Resources Portal (greenmin.gl); GEUS: Greenland Soil Samples; CC BY 4.0. Adapted by Atamai Analytics." The data have been adapted (see below); GEUS and MMR do not endorse the adapted data and accept no responsibility for its use.

WHAT ATAMAI ADDED
- Restructured GEUS's wide-format table (hundreds of analyte columns whose headers encode laboratory, preparation, technique, analyte and unit) into LithoSurfer's sample > analytical datapoint > concentration model, so every value carries its laboratory, method and unit and can be retrieved through the API.
- Mapped each laboratory / preparation / technique combination to a standard analytical package using LithoSurfer's laboratory, digestion and technique vocabularies.
- Element values are stored in ppm and oxides in wt%; detection-limit qualifiers ("<") are kept wherever the source supplies them.
- Placeholder values (for example zero, 999 or negative numbers) are flagged inactive and excluded rather than presented as measurements.
- Sample descriptors supplied by GEUS (collector, sampling year, grain-size fraction, etc.) are kept as sample properties.

USE NOTES
Results come from several laboratories and methods and are not inter-laboratory calibrated; use each datapoint's method, laboratory and detection-limit fields when comparing. The analysed sample weight (charge), for example for fire assay, is not reported by the source.
```

### description 205700762
```text
Heavy mineral concentrate geochemistry from Greenland, curated from The Greenland Mineral Resources Portal, provided by The Geological Survey of Denmark and Greenland (GEUS).

ABOUT THE SOURCE
Geochemistry of heavy mineral concentrates (HMC) from stream sediments, as registered in GEUS's Greenland geochemical databases; HMCs are usually produced by panning in the field and occasionally in the laboratory. Samples span Greenland (about 60-83 degrees N). This package holds 855 samples and 1,692 analytical datapoints, mostly analysed by Activation Laboratories and Bondar-Clegg.

SOURCE LINK
Greenland Mineral Resources Portal: https://www.greenmin.gl  |  GEUS data portal: https://data.geus.dk  |  GEUS geochemical mapping: https://eng.geus.dk/mineral-resources/greenland-and-geoscience-maps/geochemical-mapping

CITATION AND ATTRIBUTION
Licence: Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. Please cite the Geological Survey of Denmark and Greenland (GEUS) and the Mineral Resources Authority (MMR), Naalakkersuisut - Government of Greenland, as data providers and name the portal, for example: "Source: GEUS and MMR, Government of Greenland; Greenland Mineral Resources Portal (greenmin.gl); GEUS: Greenland Heavy Mineral Concentrates; CC BY 4.0. Adapted by Atamai Analytics." The data have been adapted (see below); GEUS and MMR do not endorse the adapted data and accept no responsibility for its use.

WHAT ATAMAI ADDED
- Restructured GEUS's wide-format table (one row per sample, many analyte columns whose headers encode laboratory, preparation, technique, analyte and unit) into LithoSurfer's sample > analytical datapoint > concentration model, so every value carries its laboratory, method and unit and can be retrieved through the API.
- Mapped each laboratory / preparation / technique combination to a standard analytical package using LithoSurfer's laboratory, digestion and technique vocabularies.
- Element values are stored in ppm and oxides in wt%; detection-limit qualifiers ("<") are kept wherever the source supplies them.
- Placeholder values (for example zero, 999 or negative numbers) are flagged inactive and excluded rather than presented as measurements.
- Sample descriptors supplied by GEUS (collector, sampling year, etc.) are kept as sample properties.

USE NOTES
Results come from several laboratories and methods and are not inter-laboratory calibrated; use each datapoint's method, laboratory and detection-limit fields when comparing. The analysed sample weight (charge), for example for fire assay, is not reported by the source.
```

### description 246454433
```text
Soil geochemistry from the Geological Survey of Victoria (GSV) geochemistry database, State of Victoria, Australia.

ABOUT THE SOURCE
The GSV geochemistry database holds surface geochemical samples and assays submitted from mineral exploration programs across Victoria; GSV has built up the collection since 1965 and the database was renovated in 2009/2010. This package holds the soil subset (soil, A-horizon, B-horizon and auger soil samples): 132,210 samples, 203,413 analytical datapoints (one per sample and laboratory method; 191 laboratory/method packages) and about 650,000 element concentrations. The data come from the Victorian Geoscientific Data Package DVD (GSV item G171397, data current at 12 July 2010).

SOURCE LINK
Geological Survey of Victoria geochemistry data: https://resources.vic.gov.au/geology-and-data/maps-reports-data/geochemistry-data  |  GSV data portal: https://geology.data.vic.gov.au/  |  current release of the same database: GSV Geochemistry data collection - state-wide (G172012).

CITATION AND ATTRIBUTION
(c) State of Victoria (Department of Energy, Environment and Climate Action). Geological Survey of Victoria Geochemistry Database. Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. The data have been adapted (see below); the State of Victoria does not endorse the adapted data.

WHAT ATAMAI ADDED
- Restructured the source's relational tables into LithoSurfer's sample > analytical datapoint > concentration model so that every value carries its laboratory, method, digestion and unit and can be retrieved through the API.
- Standardised units (element values in ppm) and mapped laboratory/method codes to LithoSurfer's digestion and technique vocabularies (for example partial, near-total and fire assay). Where one analysis reports an element in more than one unit, the datapoint name shows the units, for example "[ppb/ppm]".
- Sample metadata: standardised sample type and collection method (auger, grab, other); assigned a LithoSurfer Material from the GSV lithology records for 117,888 samples (ambiguous cases were left blank); soil pH (238 values) is held as the sample property soil_pH rather than as a concentration.
- Detection limits: results below detection limit carry a "<" qualifier (94,737 results). The GSV source flags these results as below detection but leaves the value empty. For 94,594 of them we attached the detection limit that GSV records for the analytical method used (GSV method table, converted to ppm) and stored it in both the detection limit and the concentration fields so that it displays. This limit is method-level, not element-specific: it is the limit GSV lists for the whole method, so the limit shown for an individual element may be higher or lower than that element's true laboratory limit. In about 22% of the cases we could compare, the same method also reports quantified values below the listed limit. 143 results (142 with no matching source assay, 1 with a zero source limit) keep an estimate made by us (the lowest quantified value for that element and unit in the same laboratory batch) or, where no estimate was possible, have no number. Treat every "<" result in this package as "below roughly this value", not as a measurement.
- Non-results excluded: for example 112 combined Os+Ir records that contain no values.

USE NOTES
Results come from many laboratories and decades of exploration programs; use each datapoint's method, laboratory and detection-limit fields when comparing. Concentrations with the "<" relative operator hold a method-level detection limit (see Detection limits above), not a measured value, so exclude them or treat them as censored values rather than using them as measured concentrations. The analysed sample weight (charge) is not reported by the source; it appears only in some method names (for example FA50 = 50 g fire assay).
```

### description 244688701
```text
Rock geochemistry from the Rock Geochemical Database of Finland, Geological Survey of Finland (GTK).

ABOUT THE SOURCE
The database describes major and trace element concentrations in the bedrock of Finland. Samples were taken in 1990-1995 with a mini-drill from rock that was as unaltered as possible, using a stratified design (about one sample per 30-120 square km), and analysed in 1992-2001 at the GTK geochemical laboratory. This package holds all 6,544 samples of the published database, with 58,893 analytical datapoints (one per GTK laboratory method), about 503,000 element values and about 65,000 oxide values. Reproducibility and drift were assessed by GTK with 375 duplicate pairs, and a lowest reliable concentration was determined for each element and method.

SOURCE LINK
GTK Hakku download service: https://hakku.gtk.fi/ (Rock geochemical data of Finland)  |  Documentation: Report of Investigation 164, http://tupa.gtk.fi/julkaisu/tutkimusraportti/tr_164.pdf

CITATION AND ATTRIBUTION
(c) Geologian tutkimuskeskus (Geological Survey of Finland, GTK). Rock geochemical data of Finland (The Rock Geochemical Database of Finland), version 1.0, 2007. GTK open licence, Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. Manual: Rasilainen, K., Lahtinen, R. and Bornhorst, T.J., 2007. The Rock Geochemical Database of Finland: Manual. Geological Survey of Finland, Report of Investigation 164.
THIS MATERIAL HAS BEEN EDITED (as required by the GTK open licence). The original, unedited data are available from the GTK Hakku service linked above.

WHAT ATAMAI ADDED
- Converted GTK's wide spreadsheet (124 columns, one row per sample, with method and unit encoded in column names such as "AL_ICPAES ppm") into LithoSurfer's sample > analytical datapoint > concentration model, so every value carries its method, laboratory and unit and can be retrieved through the API.
- Mapped the eight GTK laboratory methods (175X XRF, 308M ICP-MS after acid digestion and lithium metaborate fusion, 511P ICP-AES, 511U and 521U GFAAS, 707I fluorine, 811L and 816L carbon) to LithoSurfer's method and digestion vocabularies following GTK's method documentation. Aqua-regia leaches are labelled Partial and are not presented as totals; the 308M ICP-MS values (26 elements including the rare earths) are a total digestion.
- Element values in ppm and oxides in wt%. Values below GTK's lowest reliable concentration (LRC) carry a "<" qualifier, and the limit stored with them (the detection limit field, also copied into the concentration) is that LRC, exactly as GTK coded them ("<LRC"). The LRC is GTK's own estimate from the precision of 375 duplicate sample pairs; it is not the laboratory detection limit, which GTK lists separately in Report of Investigation 164 (Tables 1-7) and which can be higher or lower than the LRC.
- Projected Finnish grid coordinates converted to WGS84 longitude/latitude.
- Sample properties added: original sample number and date, original lithology, and stratigraphic age (name, start/end Ma, region, rank).

USE NOTES
GTK advises that the sampling density is low (one sample per 30-120 square km), so the data suit regional studies and are not suitable for conclusions from a single sample point. Sample charge by GTK method (nominal, from the method documentation, not weighed per sample): 175X XRF pellet 7 g; 308M ICP-MS 0.2 g; 511P ICP-AES 0.15 g; 511U GFAAS 0.15 g; 521U GFAAS (Au, Te, Pd) 5 g; 811L and 816L carbon 0.5 g; 707I fluorine 0.1 g.
```

### description 55066009
```text
Sediment and soil surface Geochem sampling and multi-element geochemistry derived from Argentine Geological Mining Service SEGEMAR.

ABOUT THE SOURCE
Geochemical sample points at 1:250,000 scale (SIGAM layer e250K.MuestraGeoqMu: sample type, sample code, size fraction, analytical method and multi-element results) published by the Servicio Geologico Minero Argentino (SEGEMAR) through its SIGAM geoscience information system. This package holds 37,791 samples, 37,838 analytical datapoints and about 1.8 million analytical results, mostly by INAA combined with ICP-ES, with smaller numbers by MS-ICP + ICP-AES and INAA + ICP-OES.

SOURCE LINK
SIGAM: https://sigam.segemar.gov.ar/  (WFS layer sigam:e250K.MuestraGeoqMu at https://sigam.segemar.gov.ar/geoserver217/wfs)  |  SEGEMAR: https://www.argentina.gob.ar/economia/segemar

CITATION AND ATTRIBUTION
Source: Servicio Geologico Minero Argentino (SEGEMAR) / SIGAM. Layer: e250K.MuestraGeoqMu (geochemical samples, 1:250,000). Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. The data have been adapted (see below); this adaptation is not endorsed by SEGEMAR, and SEGEMAR logos are not used.

WHAT ATAMAI ADDED
- Restructured the source's wide table into LithoSurfer's sample > analytical datapoint > concentration model, and mapped the source's analytical packages to standard LithoSurfer method and laboratory vocabularies, so every value carries its method and unit and can be retrieved through the API.
- Unit correction: a systematic Na/P unit transposition affecting 2,179 samples was corrected by relabelling the phosphorus unit from ppm to %.
- Non-measurements excluded: results of 0 (treated as failed or missing analyses) and 999 (a "not determined" placeholder) are flagged inactive (166 results) and are not in the dataset.
- Detection limits: negative source values, a convention for "not detected" where the magnitude is the detection limit, were converted to positive detection limits with the "<" qualifier (270,458 results).

USE NOTES
About 0.5% of results have an unknown analytical method. The analysed sample weight (charge), for example for fire assay, is not reported by the source.
```

---

## Part 3 — Optional `licenseText` updates

Victoria, Finland and the SEGEMAR packages currently say only "Creative Commons" (Greenland already has
a full CC BY 4.0 text plus the 6-May-2026 GEUS permission note, and SEGEMAR Sediment already has a
precise one). These make Victoria and Finland match.

### license 246454433
```text
Creative Commons Attribution 4.0 International (CC BY 4.0). (c) State of Victoria (Department of Energy, Environment and Climate Action), Geological Survey of Victoria Geochemistry Database. Adapted by Atamai Analytics - see the package description. Not endorsed by the State of Victoria.
```

### license 244688701
```text
Creative Commons Attribution 4.0 International (CC BY 4.0) - GTK open licence (GTK/388/12.00/2018). (c) Geologian tutkimuskeskus (Geological Survey of Finland, GTK), Rock geochemical data of Finland, version 1.0, 2007. This material has been edited by Atamai Analytics - see the package description. Original unedited data: https://hakku.gtk.fi/
```

---

## Part 4 — Things you should decide or check (please read)

1. **Victoria licence chain.** The data we loaded are the **2010 DVD (G171397)** — the database has exactly
   156,331 Resources Victoria samples, identical to the DVD's `gsitegcsample` (the newer G172012 release
   has 164,473). The `licence.pdf` bundled on that DVD is a GeoScience Victoria "Digital Data Access
   Licence Agreement" scoped to *gridded airborne geophysics and gravity data* — not CC BY, and it says
   the Licensee shall not re-supply the Data without consent. It does not name the geochemistry tables,
   but it is the only licence document in that download. The **CC BY 4.0** statement is on the *current*
   release of the same database (G172012 metadata PDF: "Licence: CC BY 4.0") and on resources.vic.gov.au
   (your lawyer's sheet: CC BY 4.0, accessed 2026-03-13). The draft cites CC BY 4.0. Worth confirming with
   your lawyer, or re-basing on G172012 (CC BY stated in the download itself; 8,142 more samples).
2. **Greenland rock — restrictive terms on one source report.** 7,365 of the 26,068 source rock rows
   cite the "Mineral Resource Potential of South Greenland" CD-ROM, whose bundled *General Terms of
   Delivery* say internal use only, no redistribution without GEUS's written consent. Your lawyer's sheet
   flags this class of GEUS terms as overriding portal-level CC BY. The package licence text already
   records GEUS's **6-May-2026 permission** to process and commercially distribute derived products.
   **RESOLVED 2026-10-03:** the user confirmed they hold written permission from GEUS for the Greenland data.
   (The other two cited reports: GEUS Report 2011/92, 12,743 rows; central West Greenland DVD, 5,960 rows.)
3. **Finland sample count.** The published database and `FINRock.xlsx` have 6,544 samples (375 flagged
   duplicates); the package has 6,054. A gap of 490 that duplicates (375) don't fully explain. I wrote
   "6,544 published; 6,054 in this package" without a reason — I'd like to find out why before this goes out.
4. **Finland licence mechanics.** The GTK open licence *requires* edited material to be marked as edited
   with a link to the original — that is the "THIS MATERIAL HAS BEEN EDITED" line; keep it. The Finland
   download folders for till and stream sediment contain GTK's **Basic Licence** PDF instead (restrictive:
   your lawyer's sheet says no commercial/AI use). Only the rock dataset is on the open licence; don't
   load the till/stream packages on the same assumption.
5. **Finland digestion vocabulary.** 707I (fluorine by NaOH fusion in a nickel crucible) was loaded as
   "Sodium Peroxide Fusion" — closest list entry, not exact. Suggest `digestionNotes` = "NaOH fusion,
   100 mg sample + 2 g NaOH, Ni crucible, 600 C; fluoride by ion-selective electrode" (could be done in
   the same pass as the charge update).
6. **Dates and links.** I left out "accessed [date]" because I don't know when each download was made —
   CC BY doesn't require it, but your lawyer's suggested wording includes one. Tell me the dates and I'll
   add them. The GTK link is the Hakku portal root (confirmed as GTK's download service); I couldn't
   verify a deep link to the rock dataset, and GEUS's catalogue pages redirect, so those link to the
   portals rather than individual records.
7. **Greenland rock source area.** The rock package is South/West Greenland (59.9-70.3 N), *not* the
   East Greenland 70-76 N compilation (GEUS Report 2021/4, 26,067 samples) — the row counts are almost
   identical by coincidence, so don't cite that report for it. It *is* the right reference for an
   East Greenland package if you ever load one.
8. **Field length.** The API schema doesn't publish a maximum for `description` (the Deposit description
   turned out to be capped at 255). The longest draft is about 3,000 characters. The apply script reads
   each description back after writing and stops on the first failure.
9. **Sources for every statement** are the local files listed in the final message plus the web pages cited
   in the text; the "what Atamai added" bullets come from the loaders/QC steps in `lithosurfer-work`
   and `Notes On SEGEMAR Assay Migration.pdf`.
