# LithoSurfer deposit extract — Washington State Geological Survey (DGER)

**Built 2026-09-10** from the `criticialmineralsexp` rows loaded in Step 3
(`staging/09_load.sql`, `createdby='claude_wa_20260910'`). Sibling of
`../ls_deposit_extract/` (SIGAM / Argentina), kept fully separate.

Pipeline: `staging/` (source union → dedup → load into `criticialmineralsexp`)
→ `build/export_sources.sql` (→ `build/wa_*.csv`) → `build/build_extract.py` (→ the
`*.jsonl` here). See `staging/STAGING_STATUS.md` for Steps 1–4.

## Files

| File | Rows | LithoSurfer entity (`POST /api/deposit/…`) |
|---|---:|---|
| `deposit.jsonl` | 5,418 | `Deposit` |
| `deposit_endowment.jsonl` | 9,316 | `DepositEndowment` — commodity-presence only |
| `deposit_style.jsonl` | 0 | — WA has no deposit-type / genetic classification |
| `deposit_age.jsonl` | 0 | — WA has no ages |
| `deposit_description_full.csv` | 5,418 | full free text (`Deposit.description` is capped at 255) |
| `crosswalk_lcommodity.csv` | 80 | DB `commodities.commodity_id` → `LCommodity.id` (all exact name matches — the DB list mirrors `LCommodity` 1:1) |
| `_coverage.json` | — | the counters below |

Every row carries **`sourceId = "WA:<canonical_id>"`** — the join key across files
and back to `locations.external_id` / `deposits`.

## Coverage

| | count | note |
|---|---:|---|
| deposits | 5,418 | all with coordinates (`latLonPrecision` 30–10,000 m from DGER `location_accuracy`) |
| ≥1 commodity | 5,393 (99.5%) | 25 without — iaml-only metal mines + the null-name coal composite |
| ≥1 PRIMARY commodity | 5,393 | every commodity-bearing deposit has one |
| endowment rows | 9,316 | commodity presence + role in `comment`; **no grade or tonnage** (DGER source is an occurrence inventory) |
| deposit type | 0 | none in source |
| ages | 0 | none in source |

## Loading (Step 6 — DONE 2026-09-10)

Loaded into package **250875260** "WA-DNR: USA, Washington State: Deposits &
Occurrences": **5,418 Deposit + 5,418 DepositInfo + 9,316 DepositEndowment**
(deposit ids 252248711–252317428), 102 min, 0 aborts, 0 name collisions.
Verified: `load_progress_250875260.jsonl` == `deposit.jsonl` (5,418, no gaps),
endowment count matches, 26 evenly-spaced samples confirmed against the API
(DepositInfo → dataPackageId 250875260, Deposit↔DepositInfo links, endowment links).
NB: `GET /api/deposit/DepositInfo?dataPackageId=` does **not** filter server-side —
verify by fetching records by id, not by listing the package.

```
node find_package.cjs "washington"                        # -> package id
node load_deposits.cjs --package 250875260 --dry --limit 5   # inspect
node load_deposits.cjs --package 250875260                   # real, resumable
node verify_loaded.cjs 250875260 3                           # check against API
node undo_load.cjs     --package 250875260                   # children-first delete
```

Rate ~1/sec (~90 min for 5,418). If it aborts on an API error, fix the extract and
re-run — resumable via `load_progress_250875260.jsonl` (already-loaded sourceIds are
skipped, so names are not re-spent).

`Deposit.name` is globally unique with no server uniquifier and API delete is
soft-only, so the loader names every deposit **`"<name> (WA <canonicalId>)"`** —
one scheme, spent once. Order per deposit: `Deposit` → `DepositInfo`
(inside the package) → `DepositEndowment` rows. Resumable via
`load_progress_<pkg>.jsonl`.

## Not carried into LithoSurfer

- **Deposit type / genetic model** — none in the DGER source.
- **Grade / tonnage** — the DGER source records only yes/no production & assay flags.
- **Ages, operating status, operator/company** — none in source.
- **Mineralogy** (5,131 `deposit_mineralogy` rows in `criticialmineralsexp`) — no
  LithoSurfer deposit entity; folded into `deposit_description_full.csv` instead.
- **`deposit_type_id` is NULL** on all 5,418 rows in `criticialmineralsexp`.
