# Conlara-Géminis merge: dry run (2026-10-28). Nothing has been written.

Survivor: occurrence 1412 (holds the 53 analytical results on sample 3485, the Li endowment rows 97/98 and the data-quality flag). Retired: occurrence 1409 (set is_active = false at the end).
Both: Argentina, SEGEMAR/SIGAM, LCT pegmatite, PAST_PRODUCER, SMALL, lat -32.6486 lon -66.0686.

| Table | 1409 has | Action | Why |
|---|---|---|---|
| core.occurrence_commodities | Li (primary), Beryl (870, secondary), Phosphate Rock (953, secondary) | MOVE Beryl and Phosphate Rock to 1412; skip Li | 1412 already has Li primary |
| geochem.age_measured | 354 and 355: K-Ar 536 +/- 27 Ma (355 is a Spanish-labelled copy from the SIGAM load) | MOVE 354; leave 355 behind (identical duplicate of 354) | 1412 has no measured age |
| geochem.age_stratigraphic | 1986 Proterozoico superior - Cámbrico inferior (host) | SKIP | 1987 on 1412 is the same plus the deposit age |
| geochem.lithology_observations | 19052 silicificación (alteration 69) | MOVE | 1412 has no silicification |
| | 19053 country rock, low-grade schist | SKIP | same as 1412's 19058 |
| | 19054 turmalinización | SKIP | same as 1412's 19057 |
| | 19056 moscovitización | SKIP | same as 1412's 19060 |
| | 19055 host rock "intrusiva; suite granítica" | DECISION | conflicts with 1412's host rock 19059 "metamórfica; esquisto metasedimentario (Basamento)". Recommend: do not move; keep the text in the retirement note. |
| geochem.occurrence_mineralogy | ambligonita, berilo, espodumeno, litiofilita (role "Primary mineral"), bermanita (5477) | MOVE bermanita only; skip the other four | 1412 already lists the four. Its role label "Tabular to lensoid" is a morphology term mapped as a role; the two records disagree on roles and this is left as is. |
| core.geology_summary | derived roll-up | none; regenerate for 1412 afterwards | |
| geochem.occurrence_endowment, analytical_results, samples | none | none | already on 1412 |

Then: 1409 is_active = false and comments get a note ("Merged into 1412 on <date>; moved: ...; host rock on this record was: intrusiva; suite granítica"), 1412 comments get one line pointing at the merge.
Backups first: copy the rows to be changed to a backup table or CSV; log every change; rollback = reverse the occurrence_id on the moved rows and reactivate 1409.
