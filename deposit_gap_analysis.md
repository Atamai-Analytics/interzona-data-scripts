# Deposit data readiness: `criticalmineralsexp` → LithoSurfer

**Date:** 2026-09-08
**Scope:** Can the deposit tables in `criticalmineralsexp` populate LithoSurfer's deposit model, and where are the gaps?

---

## 1. What you have (source: `criticalmineralsexp`)

| Table | Rows | Notes |
|---|---|---|
| `deposits` | 3,349 | 1 row per deposit; geometry via `locationid` → `locations` |
| `locations` (deposit rows) | 3,349 | name, lat/lon, all **EPSG:4326 (WGS84)** |
| `deposit_commodities` | 4,821 | 3,236 deposits (97%); `commodity_role` = PRIMARY / SECONDARY |
| `deposit_mineralogy` | 7,596 | 1,732 deposits; mineral + textural role |
| `deposit_types` | 191 | **This is the Hofstra et al. (2021) classification** — same scheme LithoSurfer uses |
| `sigam_deposit_type_mapping` | — | SIGAM code → `deposit_type_id`, with DIRECT / APPROXIMATE confidence |
| `sigam_deposits` | 3,351 | raw SEGEMAR source rows (Spanish), semi-structured text for ages / resources / grades |
| `company_deposit_links` | **0** | empty — no operator/owner data |

**Provenance:** every deposit is from the *Argentine Geological and Mining Service (SEGEMAR)*. All 3,349 have valid coordinates (13 have a `0` in one axis — needs cleanup; 1 has no name).

The dataset has clearly already been modelled toward LithoSurfer: deposit types = Hofstra 2021, commodity names = LithoSurfer `LCommodity` vocabulary.

---

## 2. LithoSurfer's deposit model (`/api/deposit/`, Swagger group 17)

```
DataPackage
  └── DepositInfo         (a DataPoint specialisation; carries dataPackageId, optional sampleId/locationId)
        └── Deposit        (the physical object: name, lat, lon, depth, description)
        ├── DepositStyle       0..n   deposit type (Hofstra 2021) + literature + date
        ├── DepositAge         0..n   numeric age + method + type + uncertainty + literature
        ├── DepositEndowment   0..n   commodity + grade + tonnage + cutoff + economic viability + company
        └── DepositOpStatus    0..n   operating status + resource classification (JORC) + company
```

Reference lists (all publicly readable): `LDepositType` (224), `LCommodity` (310), `LOperatingStatus` (14), `LResourceClassification`, `LEconomicViability`, `LAgeMethod`, `LAgeRelationship`, `LDepositAgeType`.

**`Deposit` core DTO fields: `name`, `lat`, `lon`, `latLonPrecision`, `depth`, `depthPrecision`, `description`, `sourceId` — that is the entire structured schema.** There are no fields for province, tectonic setting, alteration, form, mineralisation style, host rock, etc.

---

## 3. Field-by-field mapping

### 3a. Core `Deposit` — READY

| LithoSurfer | Source | Coverage | Notes |
|---|---|---|---|
| `name` | `locations.locationname` | 3,348 / 3,349 | 1 missing; 3,009 distinct names (some shared across nearby workings) |
| `lat` / `lon` | `locations.latitude/longitude` | 3,349 / 3,349 | WGS84 already; fix 13 zero-axis rows |
| `latLonPrecision` | — | 0 | optional; SEGEMAR points are nominal — leave null or set a blanket estimate |
| `depth` / `depthPrecision` | — | 0 | optional; not in source |
| `description` | synthesise | — | see gap #1 |
| `sourceId` | `deposits.depositid` or SIGAM `numero_de_deposito` | 3,349 | use as backlink |

### 3b. `DepositStyle` (deposit type) — MOSTLY READY

- `deposit_types` **is** the Hofstra 2021 scheme. All **49 types actually in use** map to LithoSurfer `LDepositType` by name (39 exact, 10 trivially near — e.g. DB `Low-sulfidation epithermal gold-silver` vs LS `Low-sulfidation (LS) epithermal goldsilver`).
- **Crosswalk needed:** DB `deposit_type_id` (small ints, 1–191) ≠ LithoSurfer `LDepositType.id` (e.g. 30232310). Build a name-based lookup once (~50 rows).
- **Gap:** **1,234 deposits (37%) have `deposit_type_id = NULL`.** `deposit_type_local` (raw SIGAM label) is populated for all 3,349, so those could go in as a `comment` on the style, or left unclassified.
- `literatureId` / `date` — not structured; `deposits.references` is free text (2,037 deposits).

### 3c. `DepositEndowment` (commodity / grade / tonnage) — PARTIAL

| Field | Source | Coverage |
|---|---|---|
| `commodityId` | `deposit_commodities` → `commodities.commodity_name` | 3,236 deposits; **all 82 distinct names match `LCommodity` exactly** |
| `comment` / commodity role | `deposit_commodities.commodity_role` | PRIMARY (3,234) / SECONDARY (1,587) — no direct LithoSurfer field; put in `comment` |
| `grade` (numeric) | `deposits.grade_info` / `sigam_deposits.informacion_de_las_leyes...` | **~540 deposits (16%)**, free text e.g. `Cu: 0.57 %\nAu: 0.2 g/t` |
| `tonnage` (numeric) | `deposits.resource_data` / `sigam_deposits.datos_del_recurso` | **~550 deposits (16%)**, free text e.g. `773 millones de toneladas métricas mena` |
| `economicCutoffGrade` | `sigam_deposits.ley_cutoff_del_commodity` | sparse |
| `economicViabilityId` | — | none |
| `company` / `date` | `company_deposit_links` (empty) / SIGAM `Fecha estimada` | company: **none**; date: parseable from resource text |

**This is the biggest gap.** For ~84% of deposits you can record *which commodities are present* but have **no quantitative grade or tonnage**. For the ~16% that do, the numbers are Spanish free text that must be parsed into `{commodity, grade, grade_unit, tonnage, tonnage_unit, date, classification}`. It is structured enough to parse (consistent `Commodity: value unit` lines) but it is a real task.

### 3d. `DepositOpStatus` — PARTIAL / needs a mapping decision

`deposits.deposit_status`:

| Value | Count | Nearest LithoSurfer concept |
|---|---|---|
| UNKNOWN | 1,436 | leave null |
| PAST_PRODUCER | 806 | `LOperatingStatus` = Not Operating / Historic |
| OCCURRENCE | 660 | *not an operating status* — deposit maturity, no clean target |
| PRODUCER | 210 | Operating |
| EXPLORATION | 113 | *maturity, not op status* |
| PROSPECT | 90 | *maturity, not op status* |
| FEASIBILITY | 18 | Under Development / Feasibility |
| DEVELOPMENT | 16 | Under Development |

`LOperatingStatus` only has Operating / Not Operating / Under Development / No Development branches. OCCURRENCE / PROSPECT / EXPLORATION (863 deposits, 26%) don't map — decide whether to drop the status or record it in a comment.

- `resourceClassificationId` (JORC): derivable from `sigam_deposits.datos_del_recurso` "Categoría del recurso" (`reserva probada`, `recurso medido, indicado e inferido`, …) for the ~550 deposits with resource text — needs a Spanish→`LResourceClassification` mapping.
- `company` — none (`company_deposit_links` empty).

### 3e. `DepositAge` — LARGELY MISSING

- No structured age anywhere in `criticalmineralsexp`.
- `sigam_deposits.edades_radimetricas`: **207 deposits (6%)** with semi-structured text — `Objeto datado: … Edad - Ma: 6.97; +0.4; -0.4; Método de datación: K-Ar; … Referencia: …`, often several ages per deposit. Parseable into `{age, ageUncertainty, ageMethodId, description, literature}`; `Método de datación` values (K-Ar, Ar-Ar, U-Pb, Rb-Sr) map to `LAgeMethod`.
- `edades_geologicas`: 2,261 deposits, but only chronostratigraphic names ("Mioceno superior", "roca de caja") — no numeric age. Fits `description` / an age-type note, not `age`.
- Verdict: low priority; a parser could recover ~200 deposits' worth of radiometric ages if wanted.

---

## 4. Data with no home in LithoSurfer's deposit model

These are populated in `criticalmineralsexp` but **`DepositDTO` has no field for them** — they can only go into the free-text `description`, or be dropped:

- `deposit_mineralogy` — **7,596 rows / 1,732 deposits.** No mineralogy child entity on a LithoSurfer deposit at all.
- `deposits`: `geological_province` (2,284), `geological_subprovince`, `geological_district`, `tectonic_setting` (1,490), `regional_structure`, `metallogenic_association`, `deposit_form` (1,360), `mineralization_style` (1,978), `associated_igneous`, `alteration` (682), `workings_type`, `deposit_group_local`.
  2,374 deposits (71%) carry at least one of these.
- `deposits.production_data` (184) — LithoSurfer models endowment/resource, not historical production, except loosely via `DepositEndowment` comment.

---

## 5. Practical blockers for the write itself

1. **`DepositInfo` is a DataPoint** → every deposit must be created inside a **DataPackage** (and the API wants auth as a LithoSurfer user with write access to it). Decide the target package first.
2. **ID crosswalks to build** (name-based, one-off): `deposit_types` → `LDepositType`, `commodities` → `LCommodity` (near-trivial), Spanish resource categories → `LResourceClassification`, `deposit_status` → `LOperatingStatus`, dating methods → `LAgeMethod`.
3. **Text parsers to write** for grade, tonnage, radiometric age, resource classification, reporting date (all out of `sigam_deposits`).

---

## 6. Verdict

| LithoSurfer entity | Can you populate it now? |
|---|---|
| `Deposit` (name + coords) | **Yes — 3,349 ready** (fix 13 coords, 1 name) |
| `DepositStyle` (type) | **Yes for 2,115 (63%)** after a ~50-row name crosswalk; 1,234 unclassified |
| `DepositEndowment` — commodity list | **Yes — 3,236 deposits**, vocab already aligned |
| `DepositEndowment` — grade / tonnage | **Only ~540 / ~550 (16%)**, and only after writing a parser |
| `DepositOpStatus` | **~1,050 deposits (31%)** map cleanly; needs a status-mapping decision for OCCURRENCE/PROSPECT/EXPLORATION; no company data |
| `DepositAge` | **~200 deposits (6%)** recoverable via a parser; otherwise absent |

**Bottom line:** you have enough to load **all 3,349 deposits with name, coordinates, deposit type, and commodity association** — that's a solid, complete first pass. What you *don't* have in structured form is quantitative endowment (grade/tonnage) for ~84%, operating/owner company data for 100%, and numeric ages for ~94%. And LithoSurfer's deposit schema will **not** hold your mineralogy or geological-context fields except as free text — that's a modelling limitation on their side, not a data gap on yours.

---

## 7. Coordinate quality — the DB coords were unreliable; **fixed 2026-09-08**

> **Status: RESOLVED.** On 2026-09-08 the deposit coordinates in `locations` and `sigam_deposits`
> were replaced from the SEGEMAR WFS (`sigam:e250K.DepositMetalif` + `sigam:e250K.DepositMinIndust`,
> joined on `depno`). **3,321 of 3,349** `locations` rows changed; 28 unchanged. Pre-fix values are
> preserved in `locations_deposit_coords_bak_20260909`; per-row rollback in `rollback_deposit_coords.sql`.
> 8 depnos were left untouched and flagged (not in WFS, or name mismatch): `3103, 3104, 3412, 3413,
> 3414, 25613, 11098, 24777`. A later cross-check against the fact-sheet scrape (§8) found **5 more
> rows** with a whole-number longitude the WFS fix missed — see `sigam_fichas/DIFF_SUMMARY.md`.
> The analysis that follows is the original pre-fix assessment, kept for context.

Cross-checked `criticalmineralsexp` deposit coordinates against SEGEMAR's own published **1:250,000 metalliferous-deposits shapefile** (`lithosurfer-work/e250K_DepositMetalif/`, 1,966 points, EPSG:4326, join key `depno` = `locations.external_id`, names confirmed matching).

Of the **1,921 deposits present in both**:

| DB vs shapefile distance | count | share |
|---|---|---|
| ≤ 1 km (agree) | 344 | 18% |
| 1–10 km | 107 | 6% |
| 10–50 km | 258 | 13% |
| **≥ 50 km (gross disagreement)** | **1,212** | **63%** |

Median offset **88 km**. Verified failure cases (external references + SIGAM's own `ubicacion_politica` town/province text all favour the shapefile):

- `depno 2218` "Wanda" — DB puts it in Neuquén (-39.06, -69.68); it's in **Misiones** (-25.95, -54.55, per shapefile and the duplicate SIGAM record 11002). ~2,000 km error.
- `depno 11118` "Santa Catalina" — DB/SIGAM lat = lon = -23.38861 (copy error). Shapefile (-21.96, -66.06) matches the town in Jujuy.
- `depno 26064` "Veta 25 de mayo" — DB/SIGAM longitude = 0. Shapefile (-23.42, -65.50) matches Huacalera, Jujuy.
- `depno 92` "El Queva", `depno 3321` "Agua del Sauce", `depno 465` "General San Martín" — 90–250 km off; shapefile agrees with the named nearest town, SIGAM does not.

Root cause: `sigam_deposits.lat/lon` (the source the DB loaded from) is itself corrupt — zeros, transposed values, and gross positional errors — and `locations` carried it through faithfully. Only 13 rows are *obviously* broken (zero/equal), so the errors are mostly silent.

**Implications for the deposit load:**
1. **Do not trust `deposits`/`locations` coordinates.** For the ~1,921 metalliferous deposits, replace them with the `e250K_DepositMetalif` shapefile coordinates (joined on `depno`).
2. The remaining ~1,430 deposits (non-metalliferous / industrial minerals / the rest of `sigam_deposits`) are **not** covered by this shapefile — their coordinates are unverified and, given the same source, likely have the same error rate. Need SEGEMAR's other map layers (industrial minerals, etc.) or manual QC.
3. Even the shapefile is only ~1:250k cartographic precision (points often at area/district centroids) — fine for a deposit database, not survey-grade. Set `latLonPrecision` accordingly rather than leaving it null.
4. A CSV of the shapefile (geometry + all 22 attributes) is at `lithosurfer-work/e250K_DepositMetalif.csv`.

---

## 8. Fact-sheet scrape → staging tables (added 2026-09-09)

Scraped all 3,523 SIGAM deposit fact sheets (`scrape_sigam_fichas.py`) and loaded three **additive**
staging tables — nothing existing was modified:

| Table | Rows | Deposits | Purpose |
|---|---|---|---|
| `sigam_fichas` | 3,524 | 3,523 | scalar QC + diff against `sigam_deposits` |
| `sigam_ficha_grades` | 1,399 | 455 | structured grade / tonnage → `DepositEndowment` |
| `sigam_ficha_ages` | 265 | 212 | radiometric ages (262 numeric, 8 methods) → `DepositAge` |

**Diff result** (join `sigam_deposits.deposit_id = sigam_fichas.depno` — `numero_de_deposito` is
unusable, every row = "País"):

- 3,346 fact sheets match an existing deposit
- **177 new deposits** not in the DB (124 in the fresh `depno ≥ 26143` block; rest are U / Au-Ag /
  industrial). List: `sigam_fichas/new_deposits_177.csv`
- 5 DB deposits have no fact sheet — the same retired records flagged in §7

This is the layer to build the LithoSurfer extract from. Grade/tonnage and age tables are now
structured (previously free text in `sigam_deposits`). Full detail: `sigam_fichas/DIFF_SUMMARY.md`.

---

## 9. LithoSurfer deposit extract (added 2026-09-09)

Built in `lithosurfer-work/ls_deposit_extract/` — API-ready DTO rows for all five group-17 entities,
keyed by `sourceId = "SIGAM:<depno>"`. There is **no batch endpoint** in group 17: one POST per row,
parents (`Deposit` → `DepositInfo`) before children.

| File | Rows | Coverage |
|---|---:|---|
| `deposit.jsonl` | 3,523 | name + coords (3,521) + synthesised description |
| `deposit_style.jsonl` | 3,165 | **90%** typed; 358 industrial-rock SIGAM codes have no Hofstra ore-model type |
| `deposit_endowment.jsonl` | 5,926 | 5,038 commodity-presence + 888 grade/tonnage (763 numeric resource grades) |
| `deposit_age.jsonl` | 262 | radiometric ages, 223 with `ageMethodId` |
| `deposit_op_status.jsonl` | 1,113 | 32% — OCCURRENCE/PROSPECT/EXPLORATION/UNKNOWN don't map |

Crosswalks (all matched, in the extract dir): 65 deposit types → `LDepositType`, 82 commodities →
`LCommodity`. Deposit type is **staging-first** (fact-sheet code → `sigam_deposit_type_mapping` →
Hofstra → `LDepositType`), curated `deposits.deposit_type_id` only as fallback. 7 fact-sheet-vs-curated
type disagreements and 3 no-name/no-coord rows are flagged in `review_*.csv`.

**Left to do:** normalise grade/tonnage units (raw values in `endowment_raw.csv`); `resourceClassificationId`;
`literatureId` (needs Literature entities); resolve the 7+3 review rows; pick the target DataPackage and load.
Regenerate with `ls_deposit_extract/build/` (`export_sources.sql` → `build_crosswalks.py` → `build_extract.py`).
