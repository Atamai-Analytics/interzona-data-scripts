# WA (Washington / DGER) deposit extract — staging + dedup candidates

**2026-09-10.** Sibling of the SIGAM/Argentina deposit work, kept fully separate:
own staging tables (`wa_*`), own tag (`createdby='claude_wa_20260910'`), own dir
(`wa_deposit_extract/`). **Nothing here has touched `locations` / `deposits` /
`deposit_commodities` / `deposit_mineralogy`.** Waiting on review before Step 3.

## Step 1 — `wa_deposits_staging` (done)

`staging/01_staging.sql` — pure non-destructive UNION of the 9 deposit-relevant
`WA_*` tables, keyed `(wa_source, src_id)`, full source row kept in `raw` jsonb.

| wa_source | rows | notes |
|---|--:|---|
| metallic | 1,847 | site_name, commodities, ore_minerals, gangue, district, comments |
| gold_silver | 1,467 | same schema; **disjoint site_ids** from metallic, shared names are coincidental (see below) |
| nonmetallic | 1,902 | industrial minerals; `mineral` + `category` (Building Materials / Industrial Use / Ornamental) |
| arsenic | 230 | re-cut of metallic by hazardous commodity — **but 95 are sites not in metallic** |
| mercury | 62 | re-cut; 9 not in metallic |
| radon | 99 | re-cut (mostly uranium); 1 not in metallic |
| asbestos | 102 | ≈ subset of nonmetallic (100 fold in) |
| coal_mine | 229 | names/operators joined from `WA_coal_mine_map_inventory` on `mine_id` (228/229 matched) |
| iaml | 97 | richest — production narrative, years, ownership, mill; overlaps metallic/gold_silver |
| **total** | **6,035** | |

Coordinates: 0 nulls, all inside WA. Hazard re-cut coords are rounded to ~4 dp;
full-precision coords come from metallic/gold_silver/nonmetallic.

## Step 2 — dedup (candidates only, NOT applied)

`staging/02_edges.sql` → `03_cluster.py` (union-find) → `04_canonical.sql`.
Tables built: `wa_cluster_assignment`, `wa_dedup_canonical` (5,432 rows).

### Auto-merge rule (high precision, applied in the candidate set)

**E1 — exact normalized name AND great-circle distance ≤ 500 m.**

Coordinate proximity **alone never merges**: ~240 distinct-name pairs sit within
30 m because DGER digitised many sites to a section/township centroid
("Black Bear", "Mitchell", "Florence" all at one point = distinct claims).
Exact name at > 500 m is almost always a generic name reused across districts —
"Last Chance" (205 far pairs, 10 counties), "Eureka" (91), "Copper King" (28) —
or a shared geographic name (creek/lake/valley) on unrelated occurrences.

### Result

| | count |
|---|--:|
| staging rows | 6,035 |
| auto-merge edges (E1) | 644 |
| **canonical deposits** | **5,432** |
| rows collapsed | 603 |
| 2-member clusters | 525 |
| 3-member clusters | 36 |
| 4-member clusters | 2 |

Multi-source merges are coherent: hazard re-cuts fold back into metallic/gold_silver,
asbestos folds into nonmetallic, iaml folds into metallic/gold_silver. Widest
member spread in any merged cluster is 660 m ("Silver Hill", metallic+nonmetallic).

> This is **more conservative** than the prompt's ~4,500–5,000 estimate. The
> remaining ~400 plausible merges are in the review queue below rather than
> silently applied.

### Review queue — `staging/review_pairs.csv` (150 pairs, decide before Step 3)

| rule | n | what it is | recommendation |
|---|--:|---|---|
| `R_NAME_FAR` | 44 | exact name, same county, non-generic, 500 m–3 km | **mostly reject** — shared place-names on distinct sites ("Sultan River" ×2 @ 2.8 km, "Marble", "Guye Peak"). A few real: `Gold Axe` (551 m), `Nooksack` (714 m), `Holden` (909 m). |
| `R_TRGM` | 106 | trigram sim ≥ 0.72, same county, ≤ 1 km, different name | **mostly reject** — DGER's deliberate `(A)/(B)/(C)`, `No. 1/No. 2`, `Sec. N` enumerations of separate localities. |

**~11 genuine name-variants to merge** (surface as `X` vs `X Mine` / OCR typo):
`Deer Trail Monitor` · `McMyrl-Wilson`↔`McMyri-Wilson` · `Metaline Mining & Leasing Co.`
· `Flagstaff Mountain` · `Sultan River Placer(s)` · `Frisco Standard` · `Old Dominion`
· `Northwest Haydite Co, Inc` · `Cedar Mountain` · `Johnson Coal Co.` · `Frisco Standard mine`.

### Pre-load exclusion candidates (not deposits — flag before Step 3)

- **6 iaml mills/smelters:** `Bonanza Mill`, `Northport Smelter`, `Red Shirt Mill`,
  `Republic Mill`, `Talisman Mill` (+ `Dutch Miller` is a real prospect, keep).
- **~23 coal "area/coalfield/composite" entries** in `coal_mine` — e.g.
  `Centralia Coalfield`, `Roslyn Coalfield`, `King County regional composite maps`,
  `Stratigraphy of Coal Seams Along Coal Creek`, `Projection of Coal Seams East of Coal Creek`,
  and 1 null-name row (`mine_id=KT5`). Judgement call: a coalfield polygon centroid
  is arguably still a "deposit" for an occurrence inventory.
- 2 staging rows carry `\r` inside a commodity string (cosmetic; clean in Step 4).

## Files

| file | what |
|---|---|
| `01_staging.sql` … `05_review_export.sql` | the pipeline, re-runnable in order |
| `03_cluster.py` | union-find clustering (stdlib only) |
| `nodes.csv` / `edges.csv` | clustering inputs |
| `cluster_assignment.csv` | staging_id → cluster_id |
| `cluster_report.txt` | size distribution + source-mix summary |
| `canonical_all.csv` | **5,432 canonical deposits** — merged fields, member keys |
| `canonical_merged_only.csv` | just the 563 merged clusters, widest-spread first |
| `review_pairs.csv` | the 150 borderline pairs |

## Next (Step 3, blocked on review)

1. Confirm/adjust the review queue; fold accepted merges into `wa_dedup_canonical`.
2. Decide iaml-mill / coal-composite exclusions.
3. Snapshot `deposits` / `deposit_commodities` / `deposit_mineralogy` →
   `*_bak_wa_20260910`, document rollback (pattern: `../../phase1/README.md`).
4. Load canonical → `locations` (locationtype='DEPOSIT',
   datasource='Washington State Geological Survey (DGER)', external_id='WA:<canonical_id>',
   countryid=246, divisionid=48) + `deposits` + `deposit_commodities` + `deposit_mineralogy`,
   all tagged `createdby='claude_wa_20260910'`, `deposit_type_id` NULL.
5. WA→`commodities`→`LCommodity` crosswalk (~40 clean tokens; prose tail needs manual
   mapping/drop — see `05_review_export.sql` token dump).
