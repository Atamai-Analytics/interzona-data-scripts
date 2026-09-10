# SIGAM fact-sheet scrape → staging load & diff

**Date:** 2026-09-09
**Source:** `scrape_sigam_fichas.py` over `https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp<N>.html`
**Raw data:** `sigam_fichas/sigam_fichas.jsonl` (3,524 lines = 3,523 deposits + 1 deliberate 404 test)

## What was loaded

Three additive staging tables in `criticialmineralsexp` (nothing existing was touched):

| Table | Rows | Deposits | Feeds |
|---|---|---|---|
| `sigam_fichas` | 3,524 | 3,523 ok | scalar QC + diff |
| `sigam_ficha_grades` | 1,399 | 455 | `DepositEndowment` (grade / tonnage) |
| `sigam_ficha_ages` | 265 | 212 | `DepositAge` |

`sigam_ficha_grades` breakdown (`kind` = produccion/recurso, `slot` = grade/amount):
- 1,070 grade values, 329 tonnage/amount values, 34 distinct commodities.

`sigam_ficha_ages`: 262 of 265 rows carry a numeric age (Ma). Methods present: K-Ar, Ar-Ar, Rb-Sr, U-Pb, U-Pb SHRIMP, Sm-Nd, Pb-Pb, Termoluminiscencia.

## Diff vs `sigam_deposits` (join key `sigam_deposits.deposit_id = sigam_fichas.depno`)

> Note: `sigam_deposits.numero_de_deposito` is unusable — every row contains the literal string "País" (a header leaked into the column during the original load). `deposit_id` **is** the SIGAM `depno`.

| | count |
|---|---|
| fact sheets OK | 3,523 |
| match an existing `sigam_deposits` row | 3,346 |
| **new — in fact sheets, not in DB** | **177** → `new_deposits_177.csv` |
| in DB, no fact sheet | 5 → `deposits_no_ficha_5.csv` |

### The 177 new deposits
| depno bucket | count | w/ grades | w/ ages | character |
|---|---|---|---|---|
| < 2000 | 11 | 1 | 0 | Sierras de Córdoba/San Luis Pb-Ag-Zn vein clusters |
| 2000–10 999 | 8 | 3 | 3 | Mn + W-Bi occurrences |
| 11 000–23 999 | 3 | 1 | 0 | industrial (bentonite, limestone) |
| 24 000–25 999 | 31 | 0 | 0 | U, Au-Ag (Calcatreu), serpentinite/asbestos, kaolin, sand |
| **26 143+** | **124** | 0 | 0 | brand-new SIGAM records — mostly Jujuy placer-Au (Río *) and Córdoba aggregates |

Full attributes (name, lat/lon, commodities, type, status, grade/age counts, URL) in `new_deposits_177.csv`.

### The 5 with no fact sheet
`3103 Bichito`, `3104 Bandi`, `3412 Arroyo Rojo`, `3413 Sargent`, `3414 Beatriz` — these are exactly the depnos that were also **absent from the SEGEMAR WFS** during the coordinate fix (left untouched, flagged in `deposit_gap_analysis.md` §7). They appear to be retired SIGAM records: keep the DB row, do not expect enrichment.

## Coordinate cross-check (bonus)

The fact-sheet coordinates are an independent second source. After the 2026-09-08 `locations` fix:

- **11 matched deposits** where ficha vs DB differ > 0.05° → `coord_disagreements_23.csv`. Of these, **5 are real DB errors** the WFS fix did not catch (longitude left as a whole number): `3045` Quebrada Sunchal (-66.033 vs -66), `3248` Atalaya (-70.283 vs -70), `3395` Río Hielo (-71.717 vs -71), `5080` San Martín (-65.9 vs -65), `5202` El Chacho (-67.667 vs -67). The other ~12 truncated-lon rows are SIGAM's own coarse rounding (ficha agrees with DB at whole-degree lon).
- **15 fact sheets have a 0 in one axis** (`lat=0` for the Buenos Aires arena/sand pits 25593–25605, `lon=0` for 26129 / 26259) — parser missed one coordinate; re-scrape these individually if they matter (all low-value industrial).
- `11098` El Peñón and `24777` Colorados/La Vasca appear here too — the two name-mismatch cases already flagged in §7.

## Next step for the LithoSurfer load

1. `sigam_ficha_grades` + `sigam_ficha_ages` are structured and ready to map to `DepositEndowment` / `DepositAge`.
2. Decide on the 177 new deposits: the 124 in the 26143+ block are the cleanest add (fresh records, coords present); the 31 in 24000–25999 need a commodity-vocabulary check.
3. Apply the 5 coordinate corrections above to `locations` + `sigam_deposits`.
4. Extend `sigam_deposit_type_mapping` for any SIGAM types among the new deposits not already covered.
