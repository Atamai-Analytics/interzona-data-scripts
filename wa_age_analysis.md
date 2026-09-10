# WA‑DNR age tables — schema fit & LithoSurfer ingestion analysis

**DB:** `criticialmineralsexp`  ·  **Date:** 2026‑09‑10  ·  Sibling of `wa_deposit_extract/`

Scope: the seven `WA_*_age` staging tables vs. the native age model
(`age_measured`, `age_stratigraphic`, `age_type_reference`,
`stratigraphic_age_reference`, `minerals`, `dating_method_reference`,
`dating_instruments`), and what of it LithoSurfer can take.

---

## 0. The source tables

| Table | Rows | Age field(s) | Unit | Nature |
|---|---:|---|---|---|
| `WA_argon_age` | 1,598 | `age_ma` ± `error_ma` | Ma | Radiometric — K‑Ar (1,476), Ar‑Ar (110), isochron (7), Laser‑Ar (5) |
| `WA_uranium_age` | 922 | `age_ma` ± `error_ma` | Ma | Radiometric — U‑Pb family: 206/238 (276), 207/235 (235), 207/206 (232), 208/232 (78), U‑Pb (51), **Pb‑alpha (39)**, SIMS (6), LA‑ICPMS (3), U‑Th‑Pb (2) |
| `WA_fission_track_age` | 363 | `age_ma` ± `error_ma` | Ma | Radiometric — apatite/sphene/zircon FT, `grain_count`, `decay_constant` |
| `WA_other_analysis_age` | 149 | `age_ma` ± `error_ma` | Ma | **36Cl cosmogenic (77)**, Rb‑Sr (62), Sm‑Nd (10) |
| `WA_luminescence_age` | 370 | `age_ka` ± `error_ka` | **ka** | IRSL (238), TL (68), OSL (46), OSL‑blue (18) |
| `WA_carbon_age` | 1,829 | `conventional_age_bp` / `measured_age_bp` / `reported_age_bp` / `two_sigma_cal_age_data`, `d13c_12c_ratio_per_mille` | **14C yr BP** (text, `-9999` = null) | Radiocarbon |
| `WA_fossil_age` | 563 | `reported_age` (free text, e.g. *"Probably middle or late Jurassic"*) | — | **Biostratigraphy — qualitative, no number** |
| **Total** | **5,794** | | | |

Every row also carries: point `latitude`/`longitude`, PLSS
`township`/`range`/`section`/`section_part`, `county_name`, `geologic_unit_name`,
`material_dated`, `sample_id` (lab/field id, text), `lab_id` (lab *name*, text),
`db_source` + `db_source_record_id` (provenance), `symbology` (chronostrat bin —
Eocene, Quaternary, Paleozoic…), and several comment columns.

---

## 1. Can the native age tables manage this data?

**Partly.** The radiometric Ma‑scale ages fit `age_measured` with minor loss.
Radiocarbon, luminescence and fossil ages do not fit cleanly, and provenance has
nowhere to live on any of the age tables.

### 1a. `age_measured` (32,783 rows today; `age_ma` NUMERIC, `CHECK age_ma >= 0`)

Relevant columns it already has: `age_ma`, `age_error_ma`, `age_error_percent`,
`datingmethodid`→`dating_method_reference`, `instrument_id`→`dating_instruments`,
`age_type_id`→`age_type_reference`, `mineral`/`mineral_id`→`minerals`,
`material_dated`, `laboratory`, `lab_sample_id`, `mswd`, `probability`,
`n_analyses`, `age_interpretation`, `age_quality`, `dated_by`, `reference`, `doi`,
`comments`, plus the observation‑context machinery
(`SAMPLE` / `DRILLHOLE` / `POINT_LOCATION` / `DRILLHOLE_POINT` + FKs to
`samples`/`locations`/`drillhole_collar`).

| WA field | Fits `age_measured`? | Gap |
|---|---|---|
| `age_ma`, `error_ma` (argon, uranium, FT, other) | ✅ direct | — |
| `age_ka`, `error_ka` (luminescence) | ⚠️ only after ÷1000 | No unit column; `age_ma` is hard‑coded Ma. 273 ka → 0.000273 Ma; sig‑fig / readability loss for young ages. |
| `age_modifier` `>` `<` `~` `≥` (75 rows across 5 tables) | ❌ | No qualifier/limit column. Partly expressible via `age_type_id` = *Minimum/Maximum crystallisation age* but that overloads a different concept. |
| `material_dated` ("whole rock, muscovite, and amphibole") | ✅ as free text | `mineral_id` FK can't hold multi‑mineral / whole‑rock. |
| `grain_count` (FT) | ⚠️ → `n_analyses` | Semantic drift (grains ≠ analyses). |
| `decay_constant` (argon, uranium, FT — e.g. "1976 IUGS constants", explicit λ) | ❌ | No column → comments only. |
| `analytical_data` (argon, uranium, other — free‑text analytical detail) | ❌ | No column / no JSONB → comments only. |
| `geologic_unit_name` (every row) | ❌ | `age_measured` has no dated‑unit column; would go to `age_interpretation`/`comments`, or be modelled via `age_stratigraphic`. |
| `db_source` + `db_source_record_id` (provenance) | ❌ | Only free‑text `reference`/`doi`. No provenance/citation FK. `geochron_references` exists but is **empty and unreferenced**. |
| `lab_id` (lab name) | ✅ → `laboratory` | — |
| `latitude`/`longitude` + PLSS | ⚠️ | Needs a `locations` row per age (~5,200). `locations` has no PLSS columns (township/range/section) → comments. |
| radiocarbon `*_age_bp`, `d13c`, `two_sigma_cal_age_data` | ❌ | See 1c. |

**Method vocab gap** — `dating_method_reference` has 19 rows and is missing:
`40Ar/36Ar–40K/36Ar isochron`, `Laser‑Ar`, `Pb‑alpha`, `36Cl` (cosmogenic),
`OSL`, `IRSL`, `Sm‑Nd`, `U‑Th‑Pb`, `LA‑ICP‑MS`. (`Ar‑Ar`, `K‑Ar`, `Fission
Track`, `Rb‑Sr`, `C‑14`, `Thermoluminescence`, `Fossil Assemblage` are present.)

### 1b. Fossil ages → `age_stratigraphic` + `stratigraphic_age_reference`

`WA_fossil_age` (563) carries **no number** — it is qualitative biostratigraphy.
It does not belong in `age_measured` at all. Correct home:
`age_stratigraphic` (289,174 rows) linking to `stratigraphic_age_reference`
(318 rows — `Eocene`, `Permian`, `Jurassic`, `Mesozoic` … all present, with
`age_start_ma`/`age_end_ma`).

Gaps:
- `reported_age` free text ("Probably middle or late Jurassic") must be **parsed**
  to one `stratigraphic_age_id` + `confidence_level='UNCERTAIN'`; keep the
  original string in `age_local`.
- `fossil_type` ("Marine fossils (radiolaria)") → `determination_method` or
  `comments`.
- `age_stratigraphic` has **no** `age_type_id` and **no** citation FK — same
  provenance gap as `age_measured`.
- The `symbology` column on the *radiometric* tables (Eocene, Quaternary…) is a
  free bonus: it can populate an `age_stratigraphic` row alongside each
  `age_measured` row for map‑unit context.

### 1c. Radiocarbon — genuine model mismatch

`age_measured` holds exactly one number in Ma from a 0‑datum. `WA_carbon_age`
needs: BP datum (not Ma), the **conventional (1,166) / measured (796) / reported
(169)** distinction, δ¹³C (674), 2σ calibrated ranges (172), and lab code. Loading
`conventional_age_bp / 1e6` into `age_ma` technically passes the CHECK but throws
away everything that makes a radiocarbon date interpretable. **Recommend a
dedicated table** (or accept that radiocarbon is out of scope for this DB).

### 1d. Luminescence — usable with a unit column

Numerically fine after ka→Ma, but IRSL/OSL/TL, equivalent dose and dose rate are
method essentials that have nowhere to go. A `unit`/`age_unit` column on
`age_measured` (default `Ma`) plus method rows would make this honest.

### Summary — fit by table

| Table | Rows | Native home | Verdict |
|---|---:|---|---|
| `WA_argon_age` | 1,598 | `age_measured` | ✅ good (add 2 method rows, decay‑constant note → comments) |
| `WA_uranium_age` | 922 | `age_measured` | ✅ good (add Pb‑alpha / U‑Th‑Pb / LA‑ICPMS methods) |
| `WA_fission_track_age` | 363 | `age_measured` | ✅ good (`grain_count`→`n_analyses`) |
| `WA_other_analysis_age` | 149 | `age_measured` | ⚠️ Rb‑Sr/Sm‑Nd fine; 36Cl needs a method row + is arguably out of scope |
| `WA_luminescence_age` | 370 | `age_measured` | ⚠️ needs unit column + OSL/IRSL methods |
| `WA_carbon_age` | 1,829 | — | ❌ needs dedicated table |
| `WA_fossil_age` | 563 | `age_stratigraphic` | ⚠️ needs free‑text→`stratigraphic_age_id` parse |

---

## 2. Schema‑change suggestions

Ordered by value / effort. None are destructive; all are additive.

> **Status — S1–S4 applied to `criticialmineralsexp` on 2026‑09‑10.**
> - `age_reference` table created (`serial` PK, `UNIQUE (source_name, source_record_id)`, `isactive`/`createdby` style).
> - `age_measured` + `age_reference_id`, `age_qualifier`, `age_unit` (`NOT NULL DEFAULT 'Ma'`), `n_grains`, `decay_constant`, `dated_unit_name`, `analytical_notes jsonb`; CHECKs `chk_age_meas_qualifier` / `chk_age_meas_unit` / `chk_age_meas_n_grains`.
> - `age_stratigraphic` + `age_reference_id`, `age_type_id` (→`age_type_reference`), `fossil_taxa`, `reported_age_raw`.
> - `dating_method_reference` +8 rows (`created_by='claude_wa_age_20260910'`): `40Ar/36Ar-40K/36Ar isochron`, `Laser Ar-Ar`, `Pb-alpha`, `36Cl cosmogenic`, `OSL`, `IRSL`, `U-Th-Pb`, `U-Pb LA-ICP-MS`. (`Sm-Nd` already existed as id 17 — not re-added.)
> - **S5 (`age_radiocarbon`) and S6 (PLSS on `locations`) not applied** — 14C declared out of scope by the user.
>
> **Load — radiometric subset applied 2026‑09‑10** (`lithosurfer-work/wa_age_extract/`):
> `2,953` rows → `age_measured` (argon 1,598 · uranium 920 · fission track 363 · Rb‑Sr/Sm‑Nd 72),
> each with a new `SURFACE` `locations` row + 2 `age_reference` rows.
> Tag `createdby='claude_wa_age_20260910'`; `rollback.sql` reverses it.
> 2 uranium rows dropped (negative / `-9999` age). Carbon, luminescence, fossil, 36Cl **not** loaded.

### S1 — Provenance / citation table + FKs  *(highest value — affects every row)*
`geochron_references` already exists (empty). Either populate and use it, or add:

```sql
CREATE TABLE age_reference (
  age_reference_id   serial PRIMARY KEY,
  source_name        varchar(200) NOT NULL,   -- WA_*.db_source
  source_record_id   varchar(60),             -- WA_*.db_source_record_id
  citation           text,
  doi                varchar(120),
  url                text,
  isactive           boolean NOT NULL DEFAULT true,
  createdby          varchar(60) NOT NULL,
  createddate        timestamp NOT NULL DEFAULT now(),
  UNIQUE (source_name, source_record_id)
);

ALTER TABLE age_measured      ADD COLUMN age_reference_id integer REFERENCES age_reference;
ALTER TABLE age_stratigraphic ADD COLUMN age_reference_id integer REFERENCES age_reference;
```
Back‑fill `age_measured.reference`/`doi` into it opportunistically.

### S2 — `age_measured`: qualifier, unit, and method‑metadata columns
```sql
ALTER TABLE age_measured
  ADD COLUMN age_qualifier   varchar(4)
      CHECK (age_qualifier IN ('>','>=','<','<=','~','c.')),   -- WA age_modifier
  ADD COLUMN age_unit        varchar(4) NOT NULL DEFAULT 'Ma'
      CHECK (age_unit IN ('Ma','ka','a','BP')),                -- luminescence = 'ka'
  ADD COLUMN n_grains        integer,                          -- FT grain_count (keep n_analyses clean)
  ADD COLUMN decay_constant  text,                             -- argon/U/FT
  ADD COLUMN dated_unit_name varchar(255),                     -- WA geologic_unit_name
  ADD COLUMN analytical_notes jsonb;                           -- WA analytical_data blob
```
(If you prefer to keep `age_ma` strictly Ma, store luminescence as
`age_ma = age_ka/1000` **and** set `age_unit='ka'` + keep the ka value in
`analytical_notes`.)

### S3 — Extend `dating_method_reference`
Insert: `40Ar/36Ar–40K/36Ar isochron`, `Laser Ar-Ar`, `Pb-alpha`,
`36Cl (cosmogenic)`, `OSL`, `IRSL`, `Sm-Nd`, `U-Th-Pb`, `U-Pb LA-ICP-MS`
(method_type `RADIOMETRIC` / `COSMOGENIC` / `LUMINESCENCE`). ~9 rows.

### S4 — `age_stratigraphic`: interpretation + biostratigraphy fields
```sql
ALTER TABLE age_stratigraphic
  ADD COLUMN age_type_id      integer REFERENCES age_type_reference,
  ADD COLUMN fossil_taxa      text,        -- WA fossil_type
  ADD COLUMN reported_age_raw text;        -- verbatim "Probably middle or late Jurassic"
```

### S5 — Dedicated radiocarbon table  *(only if 14C is in scope)*
```sql
CREATE TABLE age_radiocarbon (
  age_radiocarbon_id   serial PRIMARY KEY,
  locationid           integer REFERENCES locations,
  sampleid             integer REFERENCES samples,
  observation_context  varchar(20) NOT NULL,
  material_dated       varchar(120),
  lab_code             varchar(40),                 -- WA lab_id + sample_id
  conventional_age_bp  numeric,
  conventional_error   numeric,
  measured_age_bp      numeric,
  measured_error       numeric,
  reported_age_bp      numeric,
  reported_error       numeric,
  d13c_permille        numeric,
  cal_range_2sigma     text,                        -- or (cal_from_bp, cal_to_bp, curve)
  calibration_curve    varchar(30),
  age_reference_id     integer REFERENCES age_reference,
  comments             text,
  isactive             boolean NOT NULL DEFAULT true,
  createdby            varchar(60) NOT NULL,
  createddate          timestamp NOT NULL DEFAULT now()
);
```

### S6 — PLSS on `locations` (optional, low priority)
```sql
ALTER TABLE locations
  ADD COLUMN plss_township varchar(10),
  ADD COLUMN plss_range    varchar(10),
  ADD COLUMN plss_section  integer,
  ADD COLUMN plss_section_part varchar(40);
```
Otherwise concatenate into `locations.comments`.

### Load path once schema is in place
1. `age_reference` ← distinct (`db_source`,`db_source_record_id`) + join `WA_citations`.
2. `locations` ← one row per WA age row (`locationtype='OUTCROP'`, `datasource='WA DGER'`, `external_id = 'WA-AGE:<table>:<age_analysis_id>'`).
3. `age_measured` ← argon, uranium, FT, other (Rb‑Sr/Sm‑Nd), luminescence (with `age_unit`), `observation_context='POINT_LOCATION'`.
4. `age_stratigraphic` ← fossil ages (parsed) + one context row per radiometric age from `symbology`.
5. `age_radiocarbon` ← carbon (if in scope).
Tag everything `createdby='claude_wa_age_<date>'` for reversibility, matching the deposit‑extract convention.

---

## 3. LithoSurfer ingestion

LithoSurfer's model is `DataPackage → Sample (+Location) → DataPoint → method
specialization`. Age data is *sample‑anchored analytical data*, **not** deposit
data — LithoSurfer's "deposit ages" (group 17) are for ages attached to a mineral
deposit, and the WA deposit extract already established WA has none. So this goes
in as **sample geochronology**, needing Sample + Location + a **Washington
DataPackage** (which still does not exist — same blocker as
`wa_deposit_extract` Step 6 / SIGAM Phase 3).

### Method → endpoint

| WA data | Rows | LithoSurfer target | Fit |
|---|---:|---|---|
| K‑Ar (1,476), Laser‑Ar (5) | 1,481 | **08 Age Data** `/api/age/` generic AgeDataPoint | ✅ age ± error + method + material. K‑Ar has no dedicated group. |
| Ar‑Ar (110), isochron (7) | 117 | **16 ArAr** `/api/arar/ArArDataPoint` (header only) or generic Age | ⚠️ no step‑heating / aliquot / flux‑monitor data in source |
| U‑Pb family (922) | 922 | **06 UPb** `/api/upb/UPbDataPoint` (+ `UPbAgeGroup`) | ⚠️ ages only — no isotopic ratios, no concordia, no spot data. Pb‑alpha (39) doesn't really belong. 6 SIMS rows → **13 SHRIMP**. |
| Fission track (363) | 363 | **09 Fission Track** `/api/fissiontrack/FTDataPoint` (header) | ⚠️ pooled age + grain count only — no track lengths, no single‑grain data |
| Rb‑Sr (62), Sm‑Nd (10) | 72 | **15 Isotopes** `/api/iso/IsoDataPoint` or generic Age | ✅ as age datapoints |
| **Radiocarbon (1,829)** | 1,829 | **— none —** | ❌ no radiocarbon endpoint anywhere in the API |
| **Luminescence OSL/IRSL/TL (370)** | 370 | **— none —** | ❌ no luminescence endpoint |
| **36Cl cosmogenic (77)** | 77 | **— none —** (closest is 10 Helium, wrong nuclide) | ❌ |
| **Fossil / biostratigraphy (563)** | 563 | **— none —** | ❌ no biostratigraphy endpoint; only expressible as sample stratigraphic metadata |

### Bottom line

| | Rows | % |
|---|---:|---:|
| **Ingestible** as method datapoints (argon + uranium + FT + Rb‑Sr/Sm‑Nd) | **≈ 2,955** | **51%** |
| **Not ingestible** — no matching LithoSurfer method (14C + luminescence + 36Cl + fossils) | **≈ 2,839** | **49%** |

Prerequisites for the ingestible half:
1. A **Washington DataPackage** (blocked — see `wa_deposit_extract/README.md`).
2. **Sample + Location** rows created first (`/api/core/sample-with-locations`),
   one per age — LithoSurfer has no "bare age at a point"; it must hang off a sample.
3. **Literature** entities under `/api/core/` for `db_source` / `WA_citations`.
4. Per‑method lookups resolved live (`/api/core/l-analytical-method`,
   `/api/upb/LUPbCommonPbCorrection`, `/api/fissiontrack/LDosimeter`, …) — never
   hardcode ids.
5. Accept that the U‑Pb and FT loads are **header‑only** (age + error + material +
   method); the isotopic / track‑length detail is not in the WA source to begin with.

Recommended sequence: get the WA package created → load the ~2,955 radiometric
ages via generic **`/api/age/`** (simplest, covers K‑Ar + Rb‑Sr + Sm‑Nd + can
carry U‑Pb/FT ages too) → only promote U‑Pb/FT/Ar‑Ar to their dedicated method
endpoints if richer analytical data is sourced later. Keep radiocarbon,
luminescence, 36Cl and fossil ages in `criticialmineralsexp` only.
