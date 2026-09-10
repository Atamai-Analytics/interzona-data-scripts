# WA (Washington / DGER) deposit extract — staging, dedup, load

**2026-09-10.** Sibling of the SIGAM/Argentina deposit work, kept fully separate:
own staging tables (`wa_*`), own tag (`createdby='claude_wa_20260910'`), own dir
(`wa_deposit_extract/`). **Steps 1–5 complete** — 5,418 DGER deposits loaded into
`criticialmineralsexp` and a LithoSurfer extract built (`../README.md`). Step 6
(API load) in progress into package 250875260. Run order: `01`→`14`, then `build/`.

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

## Step 2 — dedup

`staging/02_edges.sql` → `03_cluster.py` (union-find) → `04_canonical.sql`.
Tables built: `wa_cluster_assignment`, `wa_dedup_canonical` (5,418 rows).

### Auto-merge rule (high precision, applied in the candidate set)

**E1 — exact normalized name AND great-circle distance ≤ 500 m.**

Coordinate proximity **alone never merges**: ~240 distinct-name pairs sit within
30 m because DGER digitised many sites to a section/township centroid
("Black Bear", "Mitchell", "Florence" all at one point = distinct claims).
Exact name at > 500 m is almost always a generic name reused across districts —
"Last Chance" (205 far pairs, 10 counties), "Eureka" (91), "Copper King" (28) —
or a shared geographic name (creek/lake/valley) on unrelated occurrences.

### Result (after 2026-09-10 review decisions — `staging/06_apply_decisions.sql`)

Decisions applied: **accept 11 name-variant merges** (Old Dominion later reverted, see 14), **drop the 5 iaml
mills/smelters**, **keep the coal composites**.

| | count |
|---|--:|
| staging rows | 6,035 |
| excluded (iaml mills/smelter) | 5 |
| active staging rows | 6,030 |
| auto-merge edges (E1 + 12 accepted) | 656 |
| **canonical deposits** | **5,418** |
| rows collapsed | 613 |
| 2-member clusters | 527 |
| 3-member clusters | 40 |
| 4-member clusters | 2 |

Multi-source merges are coherent: hazard re-cuts fold back into metallic/gold_silver,
asbestos folds into nonmetallic, iaml folds into metallic/gold_silver. After the
Old Dominion split (below) the widest merged-cluster spread is 660 m
("Silver Hill", metallic + 2× nonmetallic on one hill).

### Review queue — resolved

`staging/review_pairs.csv` (150 pairs) was triaged; `staging/review_pairs_open.csv`
(136 pairs) is what remains after the 11 accepted merges + 3 pairs they transitively
resolved. **All 136 open pairs are rejected** (kept distinct): DGER's deliberate
`(A)/(B)/(C)`, `No. 1/No. 2`, `Sec. N` enumerations, and shared place-names
("Sultan River" ×2 @ 2.8 km, "Marble", "Guye Peak", "Holden" nonmetallic vs
metallic @ 909 m). No further merges pending.

### Accepted name-variant merges (10; Old Dominion reverted)

`Deer Trail Monitor` · `McMyrl-Wilson`↔`McMyri-Wilson` (×3, incl. asbestos) ·
`Metaline Mining & Leasing Co.` · `Flagstaff Mountain` · `Sultan River Placer(s)` ·
`Frisco Standard` · `Northwest Haydite Co, Inc` · `Cedar Mountain` ·
`Johnson Coal Co.` — full staging_id pairs in `02_edges.sql` (`accepted_merges`).

**`14_split_old_dominion.sql`** (spot-check follow-up) — the accepted
`Old Dominion` / `Old Dominion mine` merge was **reverted**: `staging 4465` is a
dolomite prospect ("two beds of dolomite … crosscut in main adit") 830 m from the
Ag-Pb-Zn Old Dominion mine. Split into its own canonical **5418**
(`WA:5418`, Limestone). `WA:3231` is now gold_silver + iaml only, Ag/Pb/Zn,
spread 111 m. Patched `wa_cluster_assignment` directly (canonical ids are the
frozen load key — `03_cluster.py` renumbers, so a full rebuild is no longer safe;
`cluster_assignment.csv` is the source of truth).

**Cross-county merge review** (spot-check) — 5 merged clusters span >1 county.
`Silver Star` (163) and `Valley` (682) merge two DGER rows at identical coords
where one row's `county` was simply wrong — the dedup **fixes** these.
`Crown Point` (2378) straddles the Pierce/Yakima line in the Summit district.
`Snowshoe` (1004) has one member's county likely wrong (kept — 314 m, same name).
`Rocky Point` (270): the gold_silver member's `county`/`district` (Kittitas /
"Cle Elum") contradict its own clean coordinate (Lewis County) — merge kept
(identical coord + name), the bad `Cle Elum` district **cleared** from
`WA:270` / staging / canonical.

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
| `canonical_all.csv` | **5,418 canonical deposits** — merged fields, member keys |
| `canonical_merged_only.csv` | just the 569 merged clusters, widest-spread first |
| `review_pairs.csv` / `review_pairs_open.csv` | 150 triaged / 136 still-open (all rejected) |

## Step 4 — commodity crosswalk (done)

`07_commodities.sql` tokenizes commodities per canonical deposit →
`wa_canonical_commodity_tok` (canonical_id, token, role, mentions). `08_crosswalk.py`
maps the **114 distinct tokens** → `commodities`:

| method | tokens | note |
|---|--:|---|
| ELEMENT | ~45 | element word → `commodity_symbol` (Au, Cu, Sb, …) |
| CURATED | ~61 | industrial minerals/rocks → `commodity_name` (Limestone, Pumice, Clay, Baryte, Talc, Serpentine, …) |
| SPLIT | 15 phrases | "copper gold" → Cu + Au, etc. |
| DROP | 4 | `plutonium` (14 — uranium-hazard-table artifact), `flour`, `unknown`, `pyrite` |
| UNMAPPED | 0 | every commodity-bearing deposit resolves |

Output `crosswalk_commodity_wa.csv`. Judgement calls: `dolomite`/`marl`/`travertine`
→ Limestone; `beryl` → Be; `gem and ornamental stones` → Miscellaneous Dimension
Stones; `mineral pigments` → Ochre; `sodium sulfate` → Thenardite.

**`13_commodity_tweaks.sql`** (spot-check follow-up) — `wa_tok` now drops
source-flagged uncertain commodities (`"Copper?"`, `"cobalt?"`, `"reportedly
nickel"` — the definite `primary_commodity` still carries the real one); added
`special clays - expanding clays and shales` → Clay (was over the length cap).
`deposit_commodities` re-synced: 9,320 → **9,316** (5,479 PRIMARY / 3,837
SECONDARY), commodity-less deposits 26 → **25**.

## Step 3 — load (DONE 2026-09-10, `09_load.sql`)

Snapshots `deposits` / `deposit_commodities` / `deposit_mineralogy` →
`*_bak_wa_20260910`, then one transaction. Everything `createdby='claude_wa_20260910'`,
`deposit_type_id` NULL, rollback block at the bottom of `09_load.sql`.

| table | rows added | notes |
|---|--:|---|
| `locations` | 5,418 | locationtype='DEPOSIT', datasource='Washington State Geological Survey (DGER)', external_id='WA:<canonical_id>', countryid=246, divisionid=48, geom via trigger (0 null). Provenance + aliases + location notes in `comments`. |
| `deposits` | 5,418 | `deposits` 3,528 → **8,946**. `geological_district` ← mining_district; comments carry DGER comments/value/ore-minerals; `production_data` flag where recorded. |
| `deposit_commodities` | 9,316 | 5,479 PRIMARY / 3,837 SECONDARY (after `13`/`14`). 25 deposits have no commodity (iaml-only metal mines + null-name coal composite). |
| `deposit_mineralogy` | 5,131 | from `ore_minerals` (cleaned by `15`); 4,264 (83%) matched a `minerals.mineral_id`. |

Verified: 0 null geom, 0 unmapped ids, 0 orphan commodities. Van Epps (WA:2)
spot-checked — Sb primary + Ag/Au/Ni/Pb/Zn secondary, 7 ore minerals all resolved.

### Post-load fixes

- **`10_flatten_comments.sql`** — the load first joined `comments` sections with
  newlines, which break flat/CSV exports. Every `locations.comments` /
  `deposits.comments` is now a single line, sections separated by ` | `; doubled /
  dangling separators collapsed. `09_load.sql` emits the flat form directly.
- **`11_flatten_staging.sql` / `01_staging.sql`** — a few DGER source values carry
  a trailing `\r` (`"Manganese\r"`, `alternate_names "… | Casteel\r"`). Stripped
  from all staging text columns; `tn()` now does it at ingest. All 4 loaded tables
  + every extract file swept: **0 control chars**.
- **`12_fix_iaml_material.sql`** — `01_staging.sql` had routed the iaml `material`
  field (abandoned-mine-land site debris: "ore car", "scrap steel", "none",
  "see feature 1003-14") into `ore_minerals`. Moved the meaningful values to
  `comments` as `Site remains (IAML): …`, cleared `ore_minerals` for iaml
  (51 rows), rebuilt canonical + `deposit_mineralogy` + `deposits.comments`.
  `deposit_commodities` unaffected (iaml has no commodity field).
- **`15_clean_ore_minerals.sql`** — DGER `ore_minerals` is free text with
  quantifiers/commentary ("some chalcopyrite", "minor amounts of sphalerite",
  "reportedly stibnite", "cinnabar was found in nw 1/4 sec. 25"). `04_canonical.sql`
  now runs each token through `wa_min()` (strip leading quantifier + trailing
  "reported"/"?" , drop residual prose). `deposit_mineralogy` 5,237 → **5,131**
  (~100 phrase rows removed), `minerals.mineral_id` match rate 81% → **83%**.
- **`build/export_sources.sql`** — switched to `\copy … WITH (ENCODING 'UTF8')`;
  psql `\o` on Windows was writing Latin-1 for non-ASCII (`¼` in section refs).

## Next

- **Step 5:** build the LithoSurfer extract in `wa_deposit_extract/` (copy
  `ls_deposit_extract/build/` approach; `Deposit` + `DepositEndowment` commodity-presence,
  no ages/styles; sourceId `"WA:<canonical_id>"`).
- **Step 6 DONE 2026-09-10:** 5,418 Deposit + 9,316 DepositEndowment loaded into package 250875260 "WA-DNR: USA, Washington State: Deposits & Occurrences" (0 aborts, 0 collisions, verified)
  (blocked on Lithodat purge of package 250875258).
