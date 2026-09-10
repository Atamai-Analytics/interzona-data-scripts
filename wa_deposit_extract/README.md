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
| `deposit.jsonl` | 5,417 | `Deposit` |
| `deposit_endowment.jsonl` | 9,320 | `DepositEndowment` — commodity-presence only |
| `deposit_style.jsonl` | 0 | — WA has no deposit-type / genetic classification |
| `deposit_age.jsonl` | 0 | — WA has no ages |
| `deposit_description_full.csv` | 5,417 | full free text (`Deposit.description` is capped at 255) |
| `crosswalk_lcommodity.csv` | 80 | DB `commodities.commodity_id` → `LCommodity.id` (all exact name matches — the DB list mirrors `LCommodity` 1:1) |
| `_coverage.json` | — | the counters below |

Every row carries **`sourceId = "WA:<canonical_id>"`** — the join key across files
and back to `locations.external_id` / `deposits`.

## Coverage

| | count | note |
|---|---:|---|
| deposits | 5,417 | all with coordinates (`latLonPrecision` 30–10,000 m from DGER `location_accuracy`) |
| ≥1 commodity | 5,391 (99.5%) | 26 without — iaml-only metal mines + the null-name coal composite |
| ≥1 PRIMARY commodity | 5,391 | every commodity-bearing deposit has one |
| endowment rows | 9,320 | commodity presence + role in `comment`; **no grade or tonnage** (DGER source is an occurrence inventory) |
| deposit type | 0 | none in source |
| ages | 0 | none in source |

## Loading (Step 6 — DO NOT RUN YET)

Blocked behind SIGAM Phase 3 (waiting on Lithodat to purge test rows from package
250875258 — see `../ls_deposit_extract/PHASE3_STATUS.md`). Also needs a **Washington
data package** to exist.

```
node load_deposits.cjs --package <id> --dry --limit 5     # inspect first
node load_deposits.cjs --package <id>                     # real, resumable
node undo_load.cjs     --package <id>                     # children-first delete
```

`Deposit.name` is globally unique with no server uniquifier and API delete is
soft-only, so the loader names every deposit **`"<name> (WA <canonicalId>)"`** —
one scheme, spent once. Order per deposit: `Deposit` → `DepositInfo`
(inside the package) → `DepositEndowment` rows. Resumable via
`load_progress_<pkg>.jsonl`.

## Not carried into LithoSurfer

- **Deposit type / genetic model** — none in the DGER source.
- **Grade / tonnage** — the DGER source records only yes/no production & assay flags.
- **Ages, operating status, operator/company** — none in source.
- **Mineralogy** (5,237 `deposit_mineralogy` rows in `criticialmineralsexp`) — no
  LithoSurfer deposit entity; folded into `deposit_description_full.csv` instead.
- **`deposit_type_id` is NULL** on all 5,417 rows in `criticialmineralsexp`.
