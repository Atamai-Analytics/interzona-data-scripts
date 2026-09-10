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

### Result (after 2026-09-10 review decisions — `staging/06_apply_decisions.sql`)

Decisions applied: **accept all 11 name-variant merges**, **drop the 5 iaml
mills/smelters**, **keep the coal composites**.

| | count |
|---|--:|
| staging rows | 6,035 |
| excluded (iaml mills/smelter) | 5 |
| active staging rows | 6,030 |
| auto-merge edges (E1 + 12 accepted) | 656 |
| **canonical deposits** | **5,417** |
| rows collapsed | 613 |
| 2-member clusters | 527 |
| 3-member clusters | 40 |
| 4-member clusters | 2 |

Multi-source merges are coherent: hazard re-cuts fold back into metallic/gold_silver,
asbestos folds into nonmetallic, iaml folds into metallic/gold_silver. Widest
member spread in any merged cluster is 830 m ("Old Dominion", one of the accepted
variant merges — gold_silver + iaml + nonmetallic).

### Review queue — resolved

`staging/review_pairs.csv` (150 pairs) was triaged; `staging/review_pairs_open.csv`
(136 pairs) is what remains after the 11 accepted merges + 3 pairs they transitively
resolved. **All 136 open pairs are rejected** (kept distinct): DGER's deliberate
`(A)/(B)/(C)`, `No. 1/No. 2`, `Sec. N` enumerations, and shared place-names
("Sultan River" ×2 @ 2.8 km, "Marble", "Guye Peak", "Holden" nonmetallic vs
metallic @ 909 m). No further merges pending.

### Accepted name-variant merges (11)

`Deer Trail Monitor` · `McMyrl-Wilson`↔`McMyri-Wilson` (×3, incl. asbestos) ·
`Metaline Mining & Leasing Co.` · `Flagstaff Mountain` · `Sultan River Placer(s)` ·
`Frisco Standard` · `Old Dominion` · `Northwest Haydite Co, Inc` · `Cedar Mountain` ·
`Johnson Coal Co.` — full staging_id pairs in `02_edges.sql` (`accepted_merges`).

### Excluded (5 iaml processing facilities — `excluded=true` in staging)

`Talisman Mill` (5009) · `Republic Mill` (5024) · `Bonanza Mill` (5052) ·
`Red Shirt Mill` (5095) · `Northport Smelter` (5501). `Dutch Miller` (1101) kept —
it is a real prospect, not a mill.

### Kept by decision

- **23 coal "area/coalfield/composite" entries** (`Centralia Coalfield`,
  `Roslyn Coalfield`, `Stratigraphy of Coal Seams Along Coal Creek`, …) + 1 null-name
  coal row (`mine_id=KT5`) — loaded as centroid-level deposits.
- 2 staging rows carry `\r` inside a commodity string (cosmetic; clean in Step 4).

## Files

| file | what |
|---|---|
| `01_staging.sql` … `06_apply_decisions.sql` | the pipeline, re-runnable in order (06 records the review decisions; 02 carries the accepted merges) |
| `03_cluster.py` | union-find clustering (stdlib only); also emits `review_pairs_open.csv` |
| `nodes.csv` / `edges.csv` | clustering inputs |
| `cluster_assignment.csv` | staging_id → cluster_id |
| `cluster_report.txt` | size distribution + source-mix summary |
| `canonical_all.csv` | **5,417 canonical deposits** — merged fields, member keys |
| `canonical_merged_only.csv` | just the 569 merged clusters, widest-spread first |
| `review_pairs.csv` / `review_pairs_open.csv` | 150 triaged / 136 still-open (all rejected) |

## Next (Step 3)

Review decisions are applied; `wa_dedup_canonical` (5,417 rows) is frozen as the load set.

1. Snapshot `deposits` / `deposit_commodities` / `deposit_mineralogy` →
   `*_bak_wa_20260910`, document rollback (pattern: `../../phase1/README.md`).
2. Load canonical → `locations` (locationtype='DEPOSIT',
   datasource='Washington State Geological Survey (DGER)', external_id='WA:<canonical_id>',
   countryid=246, divisionid=48) + `deposits` + `deposit_commodities` + `deposit_mineralogy`,
   all tagged `createdby='claude_wa_20260910'`, `deposit_type_id` NULL.
3. WA→`commodities`→`LCommodity` crosswalk (~40 clean tokens; prose tail needs manual
   mapping/drop — see `05_review_export.sql` token dump).
