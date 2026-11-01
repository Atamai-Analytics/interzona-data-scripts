# Argentina backfill + Greenland migration — run instructions

Seven phase files, meant to be run **interactively** in one continuous `psql`
session (not via `psql -f`, which exits after each file and would auto-commit
without letting you review first).

## Setup (same pattern as `fdw_setup.sql`)

PowerShell, from `lithosurfer-work\gold_schema`:

```powershell
Get-Content ..\..\..\critical-minerals-ai\.env.local | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2] }
}
$env:PGPASSWORD = $env:PGPASSWORD   # already set by the loop above if present
psql.exe -h $env:PGHOST -p $env:PGPORT -U $env:PGUSER -d $env:PGDATABASE
```

(Use whatever `psql.exe` path you used for `fdw_setup.sql` — the QGIS-bundled one if that's still what's on this machine.)

## Running each phase

Once connected, for each phase in order:

```sql
\i phase0_drop_constraint.sql
```

The file ends with `BEGIN` left **open** and a verification `SELECT` whose
output prints automatically. **Read the output.** If it looks right:

```sql
COMMIT;
```

If it doesn't:

```sql
ROLLBACK;
```

Then stop and let me know what the verification query actually showed —
don't try to patch it live without checking back, since later phases assume
earlier ones succeeded exactly as designed (e.g. Phase 4 looks up Phase 3's
occurrences by `created_by = 'migration_greenland_20260930'`).

Only move to the next `\i` after a successful `COMMIT`.

## Expected verification numbers

| Phase | What it does | Expect |
|---|---|---|
| 0 | Drop `chk_sample_parent` | constraint gone, 0 rows affected |
| 1 | Argentina backfill samples | ~30,700 new standalone samples |
| 2 | Argentina backfill analytical_results | likely 1M+ rows (proportional to the 384,515 tied to the original 8,205 samples) |
| 3 | Greenland occurrences | 28 |
| 4 | Greenland samples | ~49,400 total, ~604 with occurrence_id set |
| 5 | Greenland analytical_results | check the oxide-specific count in the file — this is the number that actually unlocks `alteration_box_plot.py` |
| 6 | Greenland lithology_observations | close to 14,242 |

Phase 2 and 5 will likely take real time (potentially minutes) given the row
counts — that's expected, not a hang.

## If something goes wrong mid-phase

Each phase's own `CREATE TABLE _stage_*` / `_map_*` scratch tables are
dropped at the end of that same phase, after a successful run. If you
`ROLLBACK`, those scratch tables roll back too (they're inside the same
transaction) — safe to just re-run `\i` on the same phase file again.

## After all 6 phases commit

Tell me, and I'll re-run the verification queries myself (read-only, no
permission issue there) to confirm everything end-to-end, update
`schema-context.ts`/`sandbox.ts` to wire in `alteration_box_plot.py` for
real, and update the project memory with the final numbers.
