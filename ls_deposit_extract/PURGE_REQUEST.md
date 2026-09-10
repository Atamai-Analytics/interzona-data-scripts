# LithoSurfer purge request — SEGEMAR deposit test rows (2026-09-10)

Two aborted test loads into data package **250875258** ("SEGEMAR: Argentina Deposits & Occurrences") created the rows below. The API only soft-deletes, and a soft-deleted `deposit_info` row still satisfies `fk_deposit_info_deposit_id`, so the parent `deposit` rows cannot be removed through the API (`DELETE /api/deposit/Deposit/{id}` -> 400). Deleting the data package doesn't help either (that delete is also soft and leaves the deposits untouched).

**Please hard-delete the following from the LithoSurfer database**, then let us know — then we run the real load as one clean pass.

## 1. `deposit` rows (38)

Delete these, plus every dependent `deposit_info` (and its `data_point`), `deposit_style`, `deposit_endowment`, `deposit_age`, `deposit_op_status` row.

| deposit.id | source_id | name |
|---|---|---|
| 252247702 | SIGAM:1 | Pumahuasi; Veta Pumahuasi Vieja |
| 252247703 | SIGAM:2 | Chaussette; Veta Chaussette Sur |
| 252247704 | SIGAM:3 | Sol de Mayo; Veta Sol de Mayo |
| 252247705 | SIGAM:4 | La Bélgica; Veta la Bélgica |
| 252247706 | SIGAM:5 | Pulpera; Veta La Pulpera; Veta La Cuchara |
| 252247707 | SIGAM:6 | Veta General Leman; Leman; General Leman |
| 252247708 | SIGAM:7 | La Blanquita |
| 252247709 | SIGAM:9 | Veta Cerro Colorado |
| 252247710 | SIGAM:10 | Veta San Marcial; Veta Cumbre |
| 252247711 | SIGAM:11 | Veta La Perla |
| 252247712 | SIGAM:12 | Veta Cangrejillos ; Rosa de Oro |
| 252247713 | SIGAM:13 | La Providencia |
| 252247714 | SIGAM:14 | Casa Colorada |
| 252247715 | SIGAM:15 | El Oculto (Prospecto) |
| 252247716 | SIGAM:16 | La Italiana |
| 252247717 | SIGAM:17 | El Porvenir |
| 252247720 | SIGAM:1 | Pumahuasi; Veta Pumahuasi Vieja (SIGAM 1) |
| 252247722 | SIGAM:2 | Chaussette; Veta Chaussette Sur (SIGAM 2) |
| 252247724 | SIGAM:3 | Sol de Mayo; Veta Sol de Mayo (SIGAM 3) |
| 252247726 | SIGAM:4 | La Bélgica; Veta la Bélgica (SIGAM 4) |
| 252247728 | SIGAM:5 | Pulpera; Veta La Pulpera; Veta La Cuchara (SIGAM 5) |
| 252247730 | SIGAM:6 | Veta General Leman; Leman; General Leman (SIGAM 6) |
| 252247732 | SIGAM:7 | La Blanquita (SIGAM 7) |
| 252247734 | SIGAM:9 | Veta Cerro Colorado (SIGAM 9) |
| 252247736 | SIGAM:10 | Veta San Marcial; Veta Cumbre (SIGAM 10) |
| 252247738 | SIGAM:11 | Veta La Perla (SIGAM 11) |
| 252247740 | SIGAM:12 | Veta Cangrejillos ; Rosa de Oro (SIGAM 12) |
| 252247742 | SIGAM:13 | La Providencia (SIGAM 13) |
| 252247744 | SIGAM:14 | Casa Colorada (SIGAM 14) |
| 252247746 | SIGAM:15 | El Oculto (Prospecto) (SIGAM 15) |
| 252247748 | SIGAM:16 | La Italiana (SIGAM 16) |
| 252247750 | SIGAM:17 | El Porvenir (SIGAM 17) |
| 252248702 | SIGAM:18 | La Candelaria (SIGAM 18) |
| 252248703 | SIGAM:19 | Chinchillas |
| 252248704 | SIGAM:20 | Bonanza |
| 252248705 | SIGAM:21 | Chocaya; Rachaite |
| 252248707 |  | ZZ-uniqtest-1789039050312 |
| 252248708 |  | ZZ-pkgdel-probe-1789039549552 |

`deposit.id` IN: 252247702, 252247703, 252247704, 252247705, 252247706, 252247707, 252247708, 252247709, 252247710, 252247711, 252247712, 252247713, 252247714, 252247715, 252247716, 252247717, 252247720, 252247722, 252247724, 252247726, 252247728, 252247730, 252247732, 252247734, 252247736, 252247738, 252247740, 252247742, 252247744, 252247746, 252247748, 252247750, 252248702, 252248703, 252248704, 252248705, 252248707, 252248708

## 2. Known child ids

From the second run's log (the first run's log was lost — please also sweep any children / `deposit_info` still attached to the deposit ids above).

- `deposit_info`.id (20): 252247768, 252247769, 252247770, 252247771, 252247772, 252247773, 252247774, 252247775, 252247776, 252247777, 252247778, 252247779, 252247780, 252247781, 252247782, 252247783, 252247784, 252247785, 252247786, 252247787
- `deposit_style`.id (20): 252248117, 252248118, 252248119, 252248120, 252248121, 252248122, 252248123, 252248124, 252248125, 252248126, 252248127, 252248128, 252248129, 252248130, 252248131, 252248132, 252248133, 252248134, 252248135, 252248136
- `deposit_endowment`.id (65): 252248402, 252248403, 252248404, 252248405, 252248406, 252248407, 252248408, 252248409, 252248410, 252248411, 252248412, 252248413, 252248414, 252248415, 252248416, 252248417, 252248418, 252248419, 252248420, 252248421, 252248422, 252248423, 252248424, 252248425, 252248426, 252248427, 252248428, 252248429, 252248430, 252248431, 252248432, 252248433, 252248434, 252248435, 252248436, 252248437, 252248438, 252248439, 252248440, 252248441, 252248442, 252248443, 252248444, 252248445, 252248446, 252248447, 252248448, 252248449, 252248450, 252248751, 252248752, 252248753, 252248754, 252248755, 252248756, 252248757, 252248758, 252248759, 252248760, 252248761, 252248762, 252248763, 252248764, 252248765, 252248766
- `deposit_age`.id (3): 252247806, 252247807, 252247808
- `deposit_op_status`.id (16): 252248164, 252248165, 252248166, 252248167, 252248168, 252248169, 252248170, 252248171, 252248172, 252248173, 252248174, 252248175, 252248176, 252248177, 252248178, 252248179

## 3. Data package

- Hard-delete soft-deleted package **250875259** (created only to test whether package deletion frees deposit names — it doesn't).
- Keep **250875258** — it's the real target and should end up empty.

## Targeting

Every `deposit.source_id` here starts `SIGAM:` (two rows have `name` starting `ZZ-`). All `deposit_info` rows are in package 250875258. Nothing else in the DB uses that prefix.
