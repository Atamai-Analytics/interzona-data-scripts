# LithoSurfer deposit extract — SEGEMAR / SIGAM (Argentina)

**Built:** 2026-09-09 from the SIGAM staging layer in `criticialmineralsexp`
(`sigam_fichas`, `sigam_ficha_grades`, `sigam_ficha_ages` — the 2026-09-09 fact-sheet scrape)
plus the curated `deposits` / `deposit_commodities` / `deposit_mineralogy` / `sigam_deposit_type_mapping`
tables for context and the deposit-type crosswalk.

Build script: `scratchpad/build_extract.py` (+ `build_crosswalks.py`, `export_sources.sql`).
Reference-list IDs resolved live from `https://api.lithosurfer.io` swagger group 17 on build day.

## Files

| File | Rows | LithoSurfer entity (`POST /api/deposit/…`) |
|---|---:|---|
| `deposit.jsonl` | 3,523 | `Deposit` (`DepositDTO`) |
| `deposit_style.jsonl` | 3,165 | `DepositStyle` — deposit type |
| `deposit_endowment.jsonl` | 5,926 | `DepositEndowment` — 5,038 commodity-presence rows + 888 grade/tonnage rows |
| `deposit_age.jsonl` | 262 | `DepositAge` — radiometric ages |
| `deposit_op_status.jsonl` | 1,113 | `DepositOpStatus` — operating status |
| `endowment_raw.csv` | 1,399 | every staging grade/amount value + unit, for proper unit normalisation later |
| `crosswalk_deposit_type.csv` | 65 | DB Hofstra `deposit_type_id` → `LDepositType.id` (all matched: 49 exact, 16 manual) |
| `crosswalk_commodity.csv` | 82 | DB `commodity` → `LCommodity.id` (all matched) |
| `review_type_disagreements.csv` | 7 | deposits where the fact-sheet type ≠ the curated `deposits.deposit_type_id` |
| `review_needs_attention.csv` | 3 | deposits with no name / no coordinate in the fact sheet |
| `_coverage.json` | — | the counters below |

Every row carries **`sourceId = "SIGAM:<depno>"`** (ages: `"SIGAM:<depno>#<seq>"`). That is the join key
across all five files and back to `sigam_deposits.deposit_id` / `locations.external_id`.

## Linking model (how a loader uses this)

`DepositInfo` is a DataPoint, so each deposit must be created inside a **writable DataPackage**. There is
**no batch endpoint** in group 17 — it is one POST per row. Order:

1. `POST /api/deposit/Deposit` ← `deposit.jsonl` row → returns `Deposit.id`
2. `POST /api/deposit/DepositInfo` with `{ dataPointDTO:{ dataPackageId:<pkg>, name:"<name>\\<session>", locationId?:… }, extendingDataPointDTO:{ depositId:<Deposit.id> } }` → returns `DepositInfo.id`
3. build a `depno → DepositInfo.id` map from the returned rows (match on the deposit name / your session tag)
4. for each child file, `POST` each row with `depositInfoId` set from that map (match on `sourceId`)

`literatureId` is left null everywhere — references are free text in the `comment` / `description`.
`company` is null everywhere (`company_deposit_links` is empty in the source).

## Coverage

| | count | notes |
|---|---:|---|
| deposits | **3,523** | 3,344 already in `deposits`, 179 new (mostly `depno ≥ 26143`) |
| with coordinates | 3,521 | 2 new industrial deposits have a zero axis in the fact sheet — see `review_needs_attention.csv` |
| with deposit type (`DepositStyle`) | **3,165 (90%)** | the 358 unmapped are all industrial rock / dimension-stone SIGAM codes (10i slate-marble, 06f granite, 09k limestone, 11g volcanic rock, 01f ornamental) — Hofstra 2021 has no ore-model type for building-stone quarries |
| with ≥1 commodity | **3,409 (97%)** | curated `deposit_commodities` for existing; parsed `sigam_fichas.commodities` for new |
| grade / tonnage rows | 888 across 455 deposits | **763 have a numeric `grade`** (resource grades in %, g/t or ppm only). Production grades and every tonnage / contained-metal amount are left in `comment` and in `endowment_raw.csv` — units are **not** normalised |
| radiometric ages | 262 across ~210 deposits | 223 have an `ageMethodId` (K-Ar, Ar-Ar, Rb-Sr, U-Pb, Sm-Nd, Pb-Pb); 39 had no method in the source, 3 rows had no numeric age and were dropped |
| operating status | 1,113 (32%) | `PRODUCER`/`PAST_PRODUCER`/`FEASIBILITY`/`DEVELOPMENT` → `LOperatingStatus`; `OCCURRENCE`/`PROSPECT`/`EXPLORATION`/`UNKNOWN` (2,400) do not map to an operating status and are omitted |

## Decisions & limitations

- **Coordinates** come from `locations` (the 2026-09-08 WFS fix + 2026-09-09 round-2) for existing
  deposits, and from the fact sheet for the 179 new ones. `latLonPrecision` is a blanket **5000 m**
  (SIGAM points are ~1:250k, not survey-grade).
- **Deposit type is staging-layer-first:** the SIGAM fact-sheet type code → `sigam_deposit_type_mapping`
  → Hofstra `deposit_type_id` → `LDepositType`. The curated `deposits.deposit_type_id` is only a
  fallback where the fact-sheet code is missing/unmapped. Where the two disagree (7 deposits) the
  fact-sheet wins and the pair is listed in `review_type_disagreements.csv` for a human check
  (e.g. depno 1 Pumahuasi: fact sheet "14c Polimetálicos / Vein polymetallic" vs curated "Residual clay" — fact sheet is right).
- **`description`** is synthesised free text (province, tectonic setting, mineralisation style, form,
  alteration, metallogenic association, mineralogy summary, SIGAM type label, fact-sheet URL) — none of
  these has a structured home in `DepositDTO`. Existing deposits only; new deposits get the URL line.
- **No `DepositEndowment.tonnage`** is populated. The `amount` values in the source mix ore tonnage and
  contained-metal in many units (t, Mt, kg, troy oz, million lb); normalising them needs a per-row
  decision. They are preserved verbatim in `endowment_raw.csv` and in each endowment `comment`.
- **Mineralogy** (7,596 rows) has no LithoSurfer deposit entity — folded into `description` only.

## Not yet done

- Resolve the 7 type disagreements and the 3 attention rows.
- Normalise grade/tonnage units and populate `tonnage` (from `endowment_raw.csv`).
- `resourceClassificationId` on `DepositOpStatus` (JORC categories are parseable from
  `sigam_deposits.datos_del_recurso` for ~550 deposits — not done here).
- Attach `literatureId` (needs Literature entities created first).
- Pick the target DataPackage and run the load.
