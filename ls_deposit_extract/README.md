# LithoSurfer deposit extract — SEGEMAR / SIGAM (Argentina)

**Rebuilt:** 2026-09-10 (v2) from the **cleaned `criticialmineralsexp` master** after Phase 1
(`../phase1/`). v1 derived from the raw staging layer; v2 reads the curated tables directly:
`deposits` + `locations` + `deposit_commodities` + `deposit_endowment` + `age_measured` +
`deposit_mineralogy`, with `deposit_type_id` / `commodity_id` already resolved in the DB.

Build: `build/export_sources.sql` (→ `build/v2_*.csv`) then `build/build_extract.py`.
Reference-list IDs are the `build/ref_*.json` snapshots (LithoSurfer swagger group 17).

## Files

| File | Rows | LithoSurfer entity (`POST /api/deposit/…`) |
|---|---:|---|
| `deposit.jsonl` | 3,528 | `Deposit` |
| `deposit_style.jsonl` | 3,170 | `DepositStyle` — deposit type |
| `deposit_endowment.jsonl` | 5,942 | `DepositEndowment` — 5,054 commodity-presence + 888 grade/tonnage |
| `deposit_age.jsonl` | 262 | `DepositAge` |
| `deposit_op_status.jsonl` | 1,108 | `DepositOpStatus` |
| `endowment_raw.csv` | 1,399 | every `deposit_endowment` value + unit, for unit normalisation |
| `crosswalk_deposit_type.csv` | 65 | DB Hofstra id → `LDepositType.id` (49 exact, 16 manual) |
| `crosswalk_commodity.csv` | 82 | DB `commodity` → `LCommodity.id` |
| `review_needs_attention.csv` | 2 | deposits with a zero coordinate axis (depno 25722, 26259) |
| `_coverage.json` | — | the counters below |

Every row carries **`sourceId = "SIGAM:<depno>"`** (`deposit_age`: `"SIGAM:<depno>#<n>"`) — the join
key across files and back to `locations.external_id` / `deposits`.

## Linking model (Phase 3 loader)

`DepositInfo` is a DataPoint, so each deposit is created inside a **writable DataPackage**. No batch
endpoint in group 17 — one POST per row. Order:

1. `POST /api/deposit/Deposit` ← `deposit.jsonl` → `Deposit.id`
2. `POST /api/deposit/DepositInfo` `{ dataPointDTO:{ dataPackageId, name:"<name>\\<session>" }, extendingDataPointDTO:{ depositId } }` → `DepositInfo.id`
3. build `depno → DepositInfo.id`
4. child files: `POST` each row with `depositInfoId` set, matched on `sourceId`

`literatureId` and `company` are null everywhere (source has no structured literature or operator data;
references are free text in `comment` / `description`).

## Coverage

| | count | note |
|---|---:|---|
| deposits | **3,528** | includes the 179 added in Phase 1 |
| with coordinates | 3,526 | depno 25722, 26259 have one axis = 0 (`review_needs_attention.csv`) |
| deposit type (`DepositStyle`) | **3,170 (90%)** | 358 untyped — industrial-rock SIGAM codes with no Hofstra ore-model type |
| ≥1 commodity | **3,415 (97%)** | from curated `deposit_commodities` |
| grade / tonnage rows | 888 across 455 deposits | **763 numeric `grade`** (resource grades in %, g/t, ppm). Production grades + all tonnage/contained-metal stay in `comment` + `endowment_raw.csv` — units **not** normalised |
| radiometric ages | 262 across ~210 deposits | 223 with an `ageMethodId`; 39 unmapped (Thermoluminescence / C-14 / Unknown have no `LAgeMethod`) |
| operating status | 1,108 (31%) | PRODUCER/PAST_PRODUCER/CLOSED/FEASIBILITY/DEVELOPMENT → `LOperatingStatus`; OCCURRENCE/PROSPECT/EXPLORATION/UNKNOWN (~2,400) have no mapping |

## Decisions & limitations

- **Coordinates** from `locations` (2026-09-08 WFS fix + 2026-09-09 round-2). `latLonPrecision` = blanket 5000 m.
- **Deposit type**: `deposits.deposit_type_id` → `crosswalk_deposit_type.csv` → `LDepositType`. Phase 1
  backfilled 926 nulls from the SIGAM ficha codes and resolved the 7 ficha-vs-curated disagreements
  (SIGAM won), so this is now a straight DB lookup.
- **`description`** is synthesised free text (province, tectonic setting, mineralisation style, form,
  alteration, metallogenic association, mineralogy, SIGAM type label, fact-sheet URL) — none has a
  structured home in `DepositDTO`.
- **No `DepositEndowment.tonnage`.** `deposit_endowment.measure='AMOUNT'` rows mix ore tonnage and
  contained metal across many units; preserved verbatim in `endowment_raw.csv` and each `comment`.
- **Mineralogy** (8,050 rows in the master) has no LithoSurfer deposit entity — `description` only.

## Not yet done (Phase 3)

- Normalise grade/tonnage units and populate `tonnage` (from `endowment_raw.csv`).
- `resourceClassificationId` on `DepositOpStatus` (JORC categories parseable from
  `sigam_deposits.datos_del_recurso`).
- `literatureId` (needs Literature entities first).
- Pick the target DataPackage and run the load.
