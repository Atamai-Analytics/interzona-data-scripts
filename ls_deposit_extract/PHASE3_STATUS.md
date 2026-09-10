# Phase 3 (LithoSurfer load) — status: BLOCKED on cleanup

**2026-09-10.** Two dry runs into package **250875258** ("SEGEMAR: Argentina Deposits & Occurrences")
aborted on API constraints and left **36 orphaned `Deposit` rows** that cannot be removed via the API.
Full list: `ORPHAN_test_deposits_250875258.csv` (deposit ids 252247702–252248705).

## What happened

| Run | Result |
|---|---|
| 1 (`--limit 20`) | aborted at SIGAM:18 — `Deposit.description` > 255 chars. 16 deposits created. |
| `undo_load.cjs` v1 | soft-deleted the 16 DepositInfos but **failed to delete the 16 Deposits** (ran unchecked; `Deposit` delete needs DepositInfo gone *and* children gone first, in order) — left 16 orphans. |
| 2 (`--limit 20`) | completed 20, but 17 names collided with the run-1 orphans and got a ` (SIGAM N)` suffix. |
| cleanup attempt | soft-deleted the 20 DepositInfos; **all 20 `Deposit` deletes returned 400** `fk_deposit_info_deposit_id … still referenced`. |

## Root causes

1. **`Deposit.name` has a global unique constraint** (`ux_deposit_name`), no server-side uniquifier.
   SIGAM names are generic and collide with each other, with existing LithoSurfer deposits, and with
   our own earlier test rows.
2. **API `DELETE` is soft only** (sets `deletedTimestamp`; row stays, FKs stay). Soft-deleted
   `deposit_info` rows still satisfy `fk_deposit_info_deposit_id`, so the parent `Deposit` can never
   be hard-deleted through the API. There is no un-delete (`PUT` on a deleted row → 500
   "Deleted entities can't be updated"). Deleting twice does not purge.
3. Net effect: **every aborted attempt permanently spends the names it created.** SIGAM depno 1–21
   currently have both their plain name and their ` (SIGAM N)` name spent in package 250875258.

Soft-delete *does* free the name for re-use (verified) — but only once the row is actually
soft-deleted, and the 36 orphan `Deposit` rows here are **not** deleted (only their DepositInfos are).

## Deleting the package does NOT help (tested 2026-09-10)

Created a throwaway package (250875259), put one deposit in it, `DELETE`d the package:
- `DELETE /api/management/data-packages/{id}` → 202, and the package is **soft-deleted**
  (`deletedTimestamp` set, still GETtable).
- The contained `Deposit` row was **not touched at all** (`deletedTimestamp` still null) — it just
  becomes an orphan in a soft-deleted package.
- The deposit **name is still spent** — could not recreate it.

So deleting 250875258 would strand its 36 deposits harder and lose the package. Don't.
(That test also left package **250875259** soft-deleted + orphan `Deposit` **252248708** — add both to
the purge list below.)

## To unblock — needs Lithodat / DB admin

Ask Lithodat to **hard-delete** (purge) from the LithoSurfer DB:
- the 36 `deposit` rows in `ORPHAN_test_deposits_250875258.csv` (+ `deposit` 252248708)
- their soft-deleted `deposit_info` rows and any `deposit_style` / `deposit_endowment` /
  `deposit_age` / `deposit_op_status` children
- soft-deleted `data_package` 250875259 (my delete test)

Every row's `sourceId` starts `SIGAM:` (or name contains `ZZ-`), so they're easy to target.
Once purged, the real load into 250875258 is a single clean pass.

## Loader changes made after this (ready for the real run)

- `Deposit.description` is now the compact ≤255 form (`build_extract.py`); full text kept in
  `deposit_description_full.csv`.
- `load_deposits.cjs` now names every deposit **`"<name> (SIGAM <depno>)"`** unconditionally
  (unique by depno, one scheme, spent once) — no more "try plain then fall back".
- `undo_load.cjs` now checks every delete status, deletes children→DepositInfo→Deposit in order,
  and reports what it could not remove.

## Do NOT re-run the loader against 250875258 until the orphans are purged

Re-running now would spend yet more names and add more un-removable rows.
