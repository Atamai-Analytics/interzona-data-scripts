# WA_*_age → native age model

**Run 2026-09-10** against `criticialmineralsexp`. Loads the **radiometric** WA‑DNR
geochronology (`WA_argon_age`, `WA_uranium_age`, `WA_fission_track_age`,
`WA_other_analysis_age` minus 36Cl) into `age_measured` + `locations` +
`age_reference`. Sibling of `../wa_deposit_extract/`.

Depends on schema changes **S1–S4** from `../wa_age_analysis.md` (applied 2026‑09‑10).

## Files

| File | Purpose |
|---|---|
| `staging/01_load.sql` | the load — STEP 1 `age_reference`, STEP 2 `locations`, STEP 3 `age_measured`. Idempotent (guards on the `claude_wa_age_20260910` tag / `external_id` / `[WA-AGE:…]` comment token). |
| `staging/02_verify.sql` | reconciliation queries (source vs loaded, integrity checks). |
| `rollback.sql` | children‑first delete keyed on `createdby='claude_wa_age_20260910'`. |

## What was loaded

| Source table | In scope | Loaded | Dropped |
|---|---:|---:|---|
| `WA_argon_age` | 1,598 | **1,598** | 0 |
| `WA_uranium_age` | 922 | **920** | 2 — `age_analysis_id` 20213 (`age_ma=-9999`), 20305 (`age_ma=-26.6`, impossible) |
| `WA_fission_track_age` | 363 | **363** | 0 |
| `WA_other_analysis_age` | 149 | **72** | 77 `36 Cl` rows (no method / out of scope) |
| **Total** | | **2,953** | |

- `2,953` new `age_measured` rows, all `observation_context='POINT_LOCATION'`.
- `2,953` new `locations` rows: `locationtype='SURFACE'`, SRID 4326, `countryid=246` (United States), `divisionid=48` (Washington / US‑WA), `adminlevel2` = WA `county_name`, `external_id='WA-AGE:<tbl>:<age_analysis_id>'`, `legacy_id` = `db_source_record_id`, PLSS + description + location quality in `comments`. One location per age (no dedup of co‑located analyses — mirrors the source's per‑analysis point).
- `2` new `age_reference` rows: *National Geochronological Database*, *WA DGER 1:100k surface geology*. `db_source IS NULL` on ~1/3 of source rows → `age_reference_id` left NULL there (1,205 rows carry a ref).

### Method crosswalk (`analysis_type` → `dating_method_reference`)

| WA `analysis_type` | → id | method |
|---|---:|---|
| `K-Ar` | 2 | K‑Ar |
| `Ar-Ar` | 3 | Ar‑Ar |
| `40Ar/36Ar-40K/36Ar isochron` | 20 | (new, S3) |
| `Laser-Ar` | 21 | Laser Ar‑Ar (new, S3) |
| `206 Pb/238 U` | 11 | 206Pb/238U |
| `207 Pb/235 U` | 12 | 207Pb/235U |
| `207 Pb/206 Pb` | 13 | 207Pb/206Pb |
| `208 Pb/232 Th` | 14 | 208Pb/232Th |
| `U-Pb` | 15 | U‑Pb |
| `Pb-Alpha` | 22 | Pb‑alpha (new, S3) |
| `206 Pb/238 U: SIMS` | 16 | U‑Pb SHRIMP (ion probe ≈ SIMS) |
| `U-Pb: LA-ICP-MS` | 27 | U‑Pb LA‑ICP‑MS (new, S3) |
| `U-Th-Pb` | 26 | U‑Th‑Pb (new, S3) |
| `Rb-Sr` | 5 | Rb‑Sr |
| `Sm-Nd` | 17 | Sm‑Nd |
| (fission track — no `analysis_type` col) | 10 | Fission Track |

### Field mapping

| `age_measured` column | Source |
|---|---|
| `age_ma`, `age_error_ma` | `age_ma`, `error_ma` (`-9999` and negatives → NULL error) |
| `age_qualifier` | `age_modifier` (`>`→`>`, `>/=`→`>=`, `<`→`<`, `~`→`~`) — 29 rows |
| `age_unit` | `'Ma'` (constant — all in‑scope tables are Ma) |
| `n_grains` | leading integer of `grain_count` (FT; 207 rows) |
| `decay_constant` | `decay_constant` verbatim |
| `dated_unit_name` | `geologic_unit_name` |
| `analytical_notes` (jsonb) | `{wa_analytical_data, wa_grain_count}` where present |
| `material_dated` | `material_dated` (`left(…,100)`) |
| `laboratory`, `lab_sample_id` | `lab_id`, `sample_id` |
| `age_reference_id` | FK via `db_source` |
| `comments` | `[WA-AGE:<tbl>:<age_analysis_id>]` + `age_comments` + `original_comments` |
| `age_type_id`, `mineral_id` | **NULL** — not parsed from source (interpretation hints live in `age_comments`) |

## Not loaded (deliberate)

- **`WA_carbon_age`** (1,829) — radiocarbon; needs S5 `age_radiocarbon` table (declined). Stays in `WA_carbon_age`.
- **`WA_luminescence_age`** (370) — OSL/IRSL/TL in ka; deferred.
- **`WA_fossil_age`** (563) — qualitative biostratigraphy → `age_stratigraphic`; deferred (needs free‑text → `stratigraphic_age_id` parsing).
- **`36 Cl`** rows (77) — cosmogenic; no clean method / out of scope.

## Re-run / undo

```sql
\i rollback.sql          -- remove everything tagged claude_wa_age_20260910
\i staging/01_load.sql   -- reload (idempotent; safe to run over a partial load)
```

The 8 `dating_method_reference` rows (ids 20–27) are schema (S3), not load data —
`rollback.sql` leaves them.

## Next (blocked)

LithoSurfer push of the ingestible subset (see `../wa_age_analysis.md` §3) is
blocked on the **Washington DataPackage** — same blocker as
`../wa_deposit_extract/` Step 6.
