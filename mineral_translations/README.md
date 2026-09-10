# Spanish→English mineral translations for SEGEMAR deposit_mineralogy

**Run:** 2026-09-10 against `criticialmineralsexp`. Tagged `created_by='claude_mineraltrans_20260910'`.

`deposit_mineralogy.mineral_name_local` for the Argentine (SEGEMAR) deposits had 1,798 rows /
473 distinct names with `mineral_id` NULL. This pass added the safe translations and re-linked.

## What was done

| Step | Detail |
|---|---|
| `gen_candidates.py` | Spanish→English mineral name matcher (irregular map + morphology + fuzzy) → `candidates_ar.csv` (355 names not yet in `mineral_name_translations`, bucketed HIGH / MED / LOW / descriptor / unmatched) |
| `gen_apply.py` → `apply_mineral_translations.sql` | inserted **204 HIGH species + 21 descriptor** rows into `mineral_name_translations`; then re-linked `deposit_mineralogy.mineral_id` from the whole translation table (also picked up ~39 names that were already translated but never linked) |

**Result (this + the two follow-ups below):** 582 `deposit_mineralogy` rows linked. SEGEMAR
mineralogy coverage **78% → 84.9%** (6,834 / 8,050). One row added to `minerals` (Glauconite).

Backup: `deposit_mineralogy_bak_mineraltrans_20260910` (all rows that were NULL pre-run).
Rollback: `rollback.sql`.

## Held back (not applied)

- **10 fuzzy/MED-LOW matches** (galenta→Galena, montmorillenita→Montmorillonite, …) — in `candidates_ar.csv`, `confidence` MED/LOW. Review and add manually.
- **~135 long-tail names / ~160 rows** — rare species, ambiguous, bad typos. `confidence` blank in the CSV.

## Remaining unlinked SEGEMAR mineralogy (1,243 rows) — mostly by design

| cause | names | rows | note |
|---|--:|--:|---|
| `mixture` in `mineral_name_translations` | 10 | 266 | limonita, psilomelano … — genuinely not single minerals |
| `group` | 20 | 243 | granate, turmalina, clorita, serpentina, olivino, apatita … — mineral groups; curator left `mineral_id` NULL |
| `series` | 12 | 196 | biotita, wolframita, illita … — mineral series |
| `descriptor` | 40 | 200 | "óxidos de manganeso" etc. (21 added here) |
| `variety` | 3 | 72 | electrum … |
| not in translations | 135 | 160 | the real remaining gap (long-tail + held fuzzy) |
| `species` **but `mineral_id` NULL** | 10 | 106 | resolved 2026-09-10 — see below |

Nothing here feeds the LithoSurfer load — group 17 has no deposit-mineralogy entity; mineralogy
only appears as free text in `Deposit.description`.

## Deposit-table gap backfill (`apply_deposit_gaps.sql` + `apply_task1_commodities.sql`, 2026-09-10)

Audit of the other AR deposit tables turned up two real gaps:

- **Task 1 — 8 deposits missing metal-commodity links** the Phase-1 parser dropped
  ("W - Sb" ×6 in the San Luis W district, "Pb; Ag; Cu; Zn", "W (Cu-Pb-Zn)"). Added 20
  `deposit_commodities` rows. (The first attempt joined on depno not depositid and did nothing;
  `apply_task1_commodities.sql` is the redo with the right ids.)
- **Task 2 — 245 deposits whose `sigam_deposits.mineralogia` was a plain comma-list** the original
  loader skipped (it only parsed the `(zone / role): mineral` structured form). Parsed and added
  **1,146 `deposit_mineralogy` rows, 1,059 linked (92%)** — including flagship deposits like Bajo de
  la Alumbrera which had zero mineralogy rows. Also added 15 translations surfaced by the parse
  (pirrotina→Pyrrhotite, marcasita→Marcasite, enargita→Enargite, …).

After: AR deposits with no commodity 113→105, with no mineralogy 1,697→1,452, `deposit_mineralogy`
8,050→9,196 rows / 85.8% linked. Tags `claude_deposit_gap_20260910` / `claude_sigam_min_20260910`;
`rollback_deposit_gaps.sql`.

## `locations.divisionid` backfill (`apply_divid_backfill.sql` + `apply_divid_correction.sql`, 2026-09-10)

363 AR deposit locations had `divisionid` (admin province) NULL. SIGAM records a province in the
location text for only ~half; the fact sheet often just says "Argentina".

- **179 from the fact-sheet `ubicacion_politica`** ("Provincia o Estado: X") — authoritative.
- **184 by PostGIS nearest-neighbour** — assigned the `divisionid` of the closest AR deposit that
  already had one (`geom <-> geom`; coordinates are the WFS-fixed set). Spot-checked against
  latitude bands — clean (Chubut ≈ -43, Río Negro ≈ -41, …).

Ran NN for all 363 first, then the correction overwrote 8 where the fact-sheet province disagreed
(3 were the zero-coordinate deposits — Ischilín's lat=0 had put it in Jujuy, now Córdoba).

**All 3,528 AR deposit locations now have a `divisionid`.** Backup `locations_divid_bak_20260910`;
`rollback_divid.sql`.

Not done (low value): `age_measured.mineral_id` (~160 unlinked, no downstream use),
gravel→"Sand and Gravel" commodity mapping (~30).

## Follow-up: the 10 species / `mineral_id` NULL rows (`apply_buckets_1_3.sql`, 2026-09-10)

Not one oversight — three causes:

- **Bucket 1 — group names (tetraedrita ×69, tennantita/tenantita ×10):** "Tetrahedrite" / "Tennantite"
  are group names since the 2019 IMA reform; `minerals` only holds the endmembers
  (Tetrahedrite-(Fe) 5459, -(Zn) 5463, …). Recategorised to `category='group'`, `mineral_id` stays NULL.
- **Bucket 2 — the "missing" 4 (`apply_bucket_2.sql`, 2026-09-10):** turned out **3 already exist**
  in `minerals` under their mindat diacritic spelling — Romanèchite `4776`, Thénardite `5505`,
  Kësterite `3014` — the translation rows just had plain-ASCII `english_text` so they never matched.
  Fixed `english_text` + `mineral_id` on those 3. **Glauconite** was genuinely absent → added as
  `minerals.mineral_id 6205` (mindat 1710, Strunz 9.E.C, mica group, `createdby='claude_...'`).
  16 `deposit_mineralogy` rows linked.
- **Bucket 3 — approximate mappings (11 rows linked):** `andorita` → Senandorite `5022`
  (historical andorite = andorite-VI); `thorogummita`/`torogummita` → Thorite `5497` (discredited =
  hydrous thorite). Both carry a `notes` explaining the approximation.

Backup `mineral_name_translations_bak_20260910b`; rollback covered in `rollback.sql`.
