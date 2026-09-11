# WA_fossil_age → age_stratigraphic

**Run 2026‑09‑11** against `criticialmineralsexp`. Loads the 563‑row
`WA_fossil_age` table (qualitative biostratigraphy — no number, see
`../wa_age_analysis.md` §1b) into `age_stratigraphic`, linked to
`stratigraphic_age_reference`. Sibling of `../wa_age_extract/`.

## The problem

`reported_age` is free text — *"Probably middle or late Jurassic"*,
*"Refugian (lower Oligocene to upper Eocene)"*, *"Late Fultonian Stage"* — not
a number. It has to be parsed to a `stratigraphic_age_id`, not loaded as-is.

## Approach — `build/parse_ages.py`

1. **Exact match** every whole-word chronostrat term in the text (case-insensitive)
   against all 318 `stratigraphic_age_reference.age_name` values — this alone
   covers plain terms (`Permian`, `Mesozoic`) and the rows that already exist
   as their own entry (`Upper Jurassic`, `Late Cretaceous`, `Guadalupian`,
   `Leonardian`, …).
2. **Early/Late ↔ Lower/Upper aliasing** — the table spells some periods
   "Upper X" and others don't have a modified row at all. Alias early↔lower,
   late↔upper so "Late Jurassic" finds the "Upper Jurassic" row instead of
   silently falling back to bare "Jurassic".
3. **Two-unit ranges** ("Jurassic to Cretaceous", "Eocene to Oligocene") —
   `stratigraphic_age_reference` already has 200 `RANGE`-type rows named
   `"<start>_<end>"` for exactly this; detect two chronostrat mentions and look
   up the matching range row (confidence forced `UNCERTAIN`).
4. **Provincial/informal stage crosswalk** (14 entries) for terms with no
   reference row of their own — West Coast Cenozoic benthic-foram/molluscan
   stages (Zemorrian→Oligocene, Refugian→Eocene_Oligocene range, Narizian/
   Ulatisian/Penutian/Bulitian/Domengine→Eocene, Kummerian→Oligocene),
   Mississippian provincial stages (Fultonian/Ravenian/Chesterian/
   Meramecian→Mississippian), Wolfcampian/Hueco→Permian, Berriasian/
   Hauterivian→Early Cretaceous.
5. **Confidence**: `UNCERTAIN` if the text hedges (*probably*, *possibly*,
   *?*, *or younger*, *as young as*, …) or is a range; else `MEDIUM`. Never
   `HIGH` — every row here is fossil-inferred, not measured.
6. Fixed 2 source typos (`Eocone`→Eocene, `Mississppian`→Mississippian).

**Result: 563 / 563 rows (242 / 242 distinct strings) resolved — 0 unmatched.**
No case needed a hand override beyond the crosswalk above.

| | rows |
|---|---:|
| exact / aliased match | 478 |
| two-unit range | 64 |
| crosswalk → range | 21 |
| **MEDIUM confidence** | 395 |
| **UNCERTAIN confidence** | 168 |

The verbatim source string is **never discarded** — it's kept in
`age_stratigraphic.reported_age_raw` regardless of how (or how coarsely) it
resolved, so any of these can be manually re-reviewed or re-parsed later
without re-touching the source table.

## Files

| File | Rows | Purpose |
|---|---:|---|
| `build/stratigraphic_age_reference.csv`, `build/wa_fossil_age.csv` | 318, 563 | plain exports (psql `\copy`) |
| `build/parse_ages.py` | — | the resolver (also runnable standalone: prints unmatched strings for review) |
| `build/build_crosswalk.py` | — | runs the resolver over the 242 distinct strings → `crosswalk_reported_age.csv` |
| `build/crosswalk_reported_age.csv` | 242 | `reported_age → stratigraphic_age_id` + confidence + method (audit trail) |
| `build/_coverage.json` | — | the counters above |
| `staging/01_load.sql` | — | loads the crosswalk into a temp table, then `locations` + `age_stratigraphic` |

## What was loaded

- **563 new `locations`** — `SURFACE`, `countryid=246`/`divisionid=48`/`adminlevel2`=county
  (same convention as `wa_age_extract`), `external_id='WA-AGE:fossil:<age_analysis_id>'`.
- **563 new `age_stratigraphic`** rows: `stratigraphic_age_id` (resolved),
  `observation_context='POINT_LOCATION'`, `confidence_level`,
  `determination_method='Fossil assemblage: <fossil_type>'`,
  `age_type_id=22` ('Stratigraphic'), `fossil_taxa=fossil_type`,
  `reported_age_raw=reported_age` (verbatim), `age_reference_id` (342 rows —
  matched by `db_source`; 221 rows have no source in the WA table, so NULL).

Tag: `createdby`/`created_by` = `claude_wa_fossil_20260911`. Idempotent
(guards on `locations.external_id` and an `[WA-AGE:fossil:…]` token in
`age_stratigraphic.comments`).

## Verified

563 locations, 563 `age_stratigraphic` rows, **0 orphans** (every row's
`locationid` resolves), 342 with `age_reference_id`, 45 distinct
`stratigraphic_age_id` values used, confidence split 395 MEDIUM / 168 UNCERTAIN.

## Not done

- No LithoSurfer push — LithoSurfer has no biostratigraphy endpoint
  (`../wa_age_analysis.md` §3). This data stays in `criticialmineralsexp` only.
- `WA_carbon_age` (radiocarbon, 1,829), `WA_luminescence_age` (370), and the
  77 `36 Cl` rows remain unloaded — out of scope per the earlier decision.
