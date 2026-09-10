# Phase 1 — bring `criticialmineralsexp` up to full coverage

**Run:** 2026-09-10. All inserts/updates tagged `createdby='claude_sigam_20260910'`
(updates also `modifiedby=`). Everything is reversible — see Rollback.

Generator: `gen_phase1.py` (reads `../sigam_fichas/sigam_fichas.jsonl`, the crosswalks in
`../ls_deposit_extract/`, `../../<scratchpad>/src_grades.csv` + `src_ages.csv`, and the DB maps
exported to `phase1/*.csv`). Re-run it to regenerate the numbered SQL.

| Step | File | What it did | Result |
|---|---|---|---|
| 1 | `01_ddl_backup.sql` | new table `deposit_endowment`; snapshots `deposits_bak_20260910`, `deposit_commodities_bak_20260910`, `deposit_mineralogy_bak_20260910` | — |
| 2 | `02_new_deposits.sql` | insert the 179 deposits missing from `deposits` (177 new + 5233, 11261) → `locations` + `deposits` + `deposit_commodities` (233) + `deposit_mineralogy` (454) | 179 deposits, 129 with a Hofstra type |
| 3 | `03_endowment.sql` | `deposit_endowment` ← `sigam_ficha_grades` (all deposits), commodity + depositid resolved, units **not** normalised | 1,399 rows / 455 deposits, 0 unresolved commodities |
| 4 | `04_ages.sql` | `age_measured` (`observation_context='POINT_LOCATION'`) ← `sigam_ficha_ages` | 262 rows; 226 with a real dating method, 36 Unknown |
| 5 | `05_backfill_types.sql` | set `deposits.deposit_type_id` from the SIGAM ficha code where it was NULL | 926 backfilled |
| 6 | `06_fixes.sql` | 7 ficha-vs-curated type disagreements (ficha wins) + rename depno 24574 `Diabillos`→`Diablillos` (`locations` + `sigam_deposits`) | 8 rows |

### After Phase 1

| table | before | after |
|---|--:|--:|
| `deposits` | 3,349 | **3,528** |
| `deposits` with `deposit_type_id` | 2,115 | **3,170** (358 still null — all industrial-rock SIGAM codes with no Hofstra ore-model type) |
| `deposit_commodities` | 4,821 | 5,054 |
| `deposit_mineralogy` | 7,596 | 8,050 |
| `deposit_endowment` | — (new) | 1,399 |
| `age_measured` (SIGAM rows) | 0 | 262 |

## Rollback

```sql
BEGIN;
DELETE FROM deposit_endowment  WHERE createdby='claude_sigam_20260910';
DELETE FROM age_measured       WHERE createdby='claude_sigam_20260910';
DELETE FROM deposit_mineralogy WHERE createdby='claude_sigam_20260910';
DELETE FROM deposit_commodities WHERE createdby='claude_sigam_20260910';
DELETE FROM deposits  WHERE createdby='claude_sigam_20260910';
DELETE FROM locations WHERE createdby='claude_sigam_20260910';
-- revert the 926+7 type backfills and the rename:
UPDATE deposits d SET deposit_type_id = b.deposit_type_id,
       deposit_type_local = b.deposit_type_local, modifiedby=b.modifiedby, modifieddate=b.modifieddate
FROM deposits_bak_20260910 b WHERE b.depositid = d.depositid AND d.modifiedby='claude_sigam_20260910';
UPDATE locations SET locationname='Salar de Diabillos' WHERE locationtype='DEPOSIT' AND external_id='24574';
UPDATE sigam_deposits SET nombre_de_yacimiento=replace(nombre_de_yacimiento,'Diablillos','Diabillos') WHERE deposit_id=24574;
COMMIT;
-- then optionally: DROP TABLE deposit_endowment; and the three *_bak_20260910 tables.
```

## Known gaps carried forward

- 358 deposits still untyped (industrial rock — no ore-model type exists).
- `deposit_endowment` units are raw SIGAM text, not normalised; `tonnage` vs contained-metal not disambiguated.
- 3 deposits flagged in `../ls_deposit_extract/review_needs_attention.csv` (depno 25722 / 26259 zero coordinate axis, 25870 no name) were still inserted, with the placeholder value.
- No operator/company data (source has none).
