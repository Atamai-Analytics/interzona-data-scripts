# Bronze DB Entity Audit (`criticialmineralsexp`)

Audit date: 2026-09-11. Read-only inspection of the `public` schema (171 base tables + 18 views; `topology` schema ignored). Purpose: inform a clean "gold" schema design — this document reports facts only, no proposed schema.

---

## (a) Core entity tables — schemas & relationships

### `locations` (3,462,330 rows exact / pg_class est. 3,195,516)
Root spatial entity for everything — samples, deposits, drillholes all hang off a `locationid`.

Columns: `locationid` PK, `locationcode`, `locationname`, `locationtype`, `latitude`/`longitude` (double, NOT NULL), `elevation`, `srid_geographic`, `projectedx`/`projectedy`/`srid_projected`, `geom` (PostGIS geometry), `countryid` → `countries`, `divisionid` → `divisions`, `adminlevel2`, `locationdate`, `datasource`, `datasource_url`, `external_id`, `legacy_id`, `comments`, audit columns (`createdby`/`createddate`/`modifiedby`/`modifieddate`), `isactive`.

Declared FKs: `countryid`→`countries`, `divisionid`→`divisions`, `srid_geographic`/`srid_projected`→`spatial_reference_systems`.

`datasource` free-text field is the real provenance flag (not a lookup table). Top sources by row count: Geological Survey of NSW (2.38M), Geological Survey of Finland (245K), Tasmania DSG (227K), USGS (197K), Resources Victoria (156K), SGU Sweden (137K), SEGEMAR Argentina (41K), Wu/Fang/Ji zircon geochronology DB (31K), GEUS Greenland (27K), Washington DGER (5.4K + 3.5K geochronology compilation), Nigeria/Ireland/Brazil/Saudi/Norway/Spain (single-digit thousands or less). `external_id`/`legacy_id` are populated inconsistently — this is a per-source ad hoc identifier, not a global scheme.

### `deposits` (8,946 rows)
28 columns: `depositid` PK, `locationid` FK→`locations` (NOT NULL — every deposit has exactly one location point), `deposit_type_id`→`deposit_types`, plus a large block of free-text descriptive fields (`deposit_type_local`, `deposit_status`, `size_category`, `geological_province/subprovince/district`, `tectonic_setting`, `regional_structure`, `metallogenic_association`, `deposit_form`, `mineralization_style`, `associated_igneous`, `alteration`, `production_data`, `resource_data`, `grade_info`, `references`, `comments`, `workings_type`, `deposit_group_local`), audit columns, `isactive`.

**Provenance breakdown (`createdby`), verified by querying live data (this corrects/refines prior memory):**
| createdby | count | isactive | country |
|---|---|---|---|
| `AtamaiAdmin` | 3,349 | 3,335 true / 14 false | 100% Argentina (countryid=23) |
| `claude_sigam_20260910` | 179 | all true | Argentina |
| `claude_wa_20260910` | 5,418 | all true | Washington State, USA |

So the "SIGAM/Argentina" cohort is actually 3,349 + 179 = **3,528** deposits (matches prior memory's post-cleanup figure), but the bulk of it (3,349) was loaded under the generic `AtamaiAdmin` tag in an earlier session — only the last 179 incremental/fixed rows carry the `claude_sigam_20260910` tag. Don't rely on `createdby='claude_sigam_20260910'` alone to select "the SIGAM deposits" — filter by country/locationid range or by the `sigam_deposits` join instead.

WA deposits carry their external id embedded as unstructured text inside `comments`, e.g. `"[coal_mine] Operator: Occidental Coking Coal Co. | Location accuracy: section | LithoSurfer sourceId: WA:5173"`. Confirmed **exactly 5,418** deposit rows contain `LithoSurfer sourceId` in comments — a 1:1 match with the WA cohort size, i.e. 100% of WA deposits use this pattern and no other cohort does. This is not a structured column — any consumer needs a regex/LIKE extraction, or better, a real column, in the new schema.

The raw SIGAM staging table `sigam_deposits` (3,351 rows, Spanish-language columns like `numero_de_deposito`, `nombre_de_yacimiento`, `lat`/`lon`) is the untransformed import; no explicit crosswalk column back to `deposits.depositid` was found in either table — the relationship is presumably positional/derived during the load rather than declared via FK or shared key. This should be verified against ETL scripts if lineage matters.

`deposit_group_local` (a coarse deposit-classification bucket like "Epithermal and transitional", "Placer", "Porphyry", "Pegmatitic", "SEDEX and submarine VMS") is populated on only 3,347 of 8,946 rows (the rest NULL) — it is **not** a "project" grouping, just a genetic-classification tag, populated only for the SIGAM/Argentina cohort apparently (Spanish deposit-clan taxonomy carried through).

There is a parallel **`deposits_export`** table (8,932 rows = 8,946 − 14, exactly the `isactive=false` count) plus `deposit_commodities_export` (14,376 vs 14,390 in the base table, same 14-row diff) and `deposit_mineralogy_export` (12,180 vs 14,327 in the base table — a much bigger gap, see mineralogy section below). These `_export` tables look like a materialized "active-only, cleaned" snapshot already used somewhere (likely feeding the live app/API) — i.e. there is already a precedent in this codebase for a filtered/derived serving layer sitting on top of the raw entity tables. Worth checking who/what reads `_export` vs the base tables before assuming the base tables are the only source of truth.

Backup tables `deposits_bak_20260910` and `deposits_bak_wa_20260910` exist — confirmed noise (see section (e)).

### `deposit_commodities` (14,390 rows) / `deposit_mineralogy` (14,327 rows) / `deposit_endowment` (1,399 rows)
All three FK cleanly to `deposits.depositid`.
- `deposit_commodities`: `commodity_id` FK→`commodities`, NOT NULL — always resolved to the canonical commodity table, plus `commodity_role`.
- `deposit_mineralogy`: `mineral_id` FK→`minerals` but **nullable and unresolved in 2,145 of 14,327 rows (15.0%)** — `mineral_name_local` (free text) is always populated but 15% never got matched to the canonical `minerals` table. Real reconciliation backlog.
- `deposit_endowment`: `commodity_id` FK→`commodities`, nullable in schema but **0 of 1,399 rows are actually NULL** — fully resolved in practice. Has `commodity_raw`, `data_type`, `measure`, `value_num`/`value_text`, `unit`, `source` — looks like a structured tonnage/grade-endowment fact table, one row per commodity-measure-source combination per deposit.

Backup tables exist for both `deposit_commodities` and `deposit_mineralogy` (`*_bak_20260910`, `*_bak_wa_20260910`, plus `deposit_mineralogy_bak_mineraltrans_20260910`) — noise, see (e).

### `samples` (4,193,871 rows exact / pg_class est. 4,121,337) and analytical chain
`samples`: `sampleid` PK, `locationid` FK→`locations` (NOT NULL), `collarid` FK→`drillhole_collar` (nullable — drillhole samples only), `sample_type_id` FK→`sample_types`, plus `fieldid`, `samplenumber`/`samplenumberalt`, `sampletypelocal`, `sample_context` (e.g. `DRILLHOLE_POINT`), `depthfrom_m`/`depthto_m`, `sampledate`, `sample_weight_kg`, `sample_depth_m`, `comments`, audit columns.

**Critical finding: `samples` has NO relationship to `deposits` at all — declared or informal.** `samples.locationid` and `deposits.locationid` are drawn from disjoint pools: a direct check (`EXISTS` join on `locationid`) returned **0 matching rows** between the two tables. Samples and deposits are currently two entirely separate location universes in this database. Any "which samples come from which deposit" question would require net-new spatial-proximity or name-matching logic — there is nothing to inherit from bronze on this point. This is probably the single biggest gap for the gold schema to solve deliberately.

Analytical chain (fully FK'd, clean):
```
samples (sampleid)
  → analytical_results (sampleid FK, package_id FK→analytical_packages, analyte_id FK→analytes,
                          unitid FK→units, qualifier_id FK→qualifiers)  [38,011,936 rows, pg_class est.]
      → result_classifications (result_id FK→analytical_results)       [34,246,988 rows, pg_class est.]
      → analytical_result_reviews (result_id FK, run_id FK→audit_runs) [2,720,616 rows exact]
      → lithodat_audit_flags (result_id FK→analytical_results,
                                rule_code FK, run_id FK)                 [149,975 rows exact]
  → sample_properties (sampleid FK, property_def_id FK, unit_id FK)      [91,712 rows exact]
  → fractions (sampleid FK, fraction_type_id FK, size_fraction_id FK)
  → lithology_observations (sampleid FK, lithology_id FK, locationid FK, collarid FK, alterationid FK)
  → age_measured (sampleid FK, collarid FK, locationid FK, + reference/type/mineral/instrument FKs)  [35,736 rows]
  → age_stratigraphic (sampleid FK, collarid FK, locationid FK, + age_reference/age_type FKs)         [289,737 rows]
```
`analytical_packages` (1,379 rows) → `laboratories` (`lab_id`), `preparation_methods` (`prep_method_id`), `analytical_methods` (`method_id`).

`audit_flags` (1,345,911 rows, older/parallel to `lithodat_audit_flags`) → `flag_rules`, `audit_runs` (only 5 runs vs `lithodat_audit_runs` 15 runs) — two parallel QA/flagging subsystems exist (`audit_*` and `lithodat_audit_*`), apparently one legacy and one current; not reconciled.

**A second, wide/denormalized geochemistry pipeline runs in parallel:** `lithodat_datapoint_concentrations` (32,607,738 rows, pg_class est., 20 GB — by far the largest table on disk) and `lithodat_datapoint_export` (3,590,001 rows exact-ish/3.6M). These have **56 and 35 free-text-heavy columns respectively** (`datapointName`, `sampleName`, `analyticalSessionID`, `mineral`, `digestionmethod`, `laboratorycode`, `element_oxide`, `Conc`, `Uncertainty`, `detectionlimit`, etc. — mixed-case column names, clearly a direct export/import from an external "LithoDat" lab-data system) but crucially also carry `result_id`. A 1%-sample check (`TABLESAMPLE SYSTEM(1)`, ~351K rows) found **100% of populated `result_id` values matched an existing row in `analytical_results`** — so this wide table is not an orphaned parallel universe, it is consistently a superset/annotation layer keyed back to the normalized `analytical_results` rows. No declared FK constraint enforces this, though (informal join only). These two `lithodat_*` tables should be treated as the richer/raw source for provenance/method detail per result, while `analytical_results`/`result_classifications` are the normalized numeric-fact layer actually used for computation.

There are also `lithodat_samples`, `lithodat_sample_properties`, `lithodat_sample_properties2` as separate tables from `samples`/`sample_properties` — need follow-up to determine if these are pre-load staging copies or a genuinely separate pipeline (not fully explored in this pass; flagged for follow-up).

### Lookup / reference tables confirmed to exist (contrary to "if exists" uncertainty in the brief)
- **`minerals`** (6,205 rows): full mineralogical reference — `mindat_id`, `mineral_name`, `ima_formula`, `ima_abbreviation`, `ima_status`, Strunz/Dana classification codes, `crystal_system`. This is a real, well-populated canonical vocabulary (looks like an IMA/Mindat import).
- **`commodities`** (287 rows): `commodity_id`, `commodity_name`, `commodity_symbol`, `commodity_category`, `is_critical_mineral` (boolean flag — directly relevant to the app's "critical minerals" purpose), `description`. This is the canonical commodity vocabulary that `deposit_commodities` and `deposit_endowment` both FK into correctly.
- **`deposit_endowment`** exists (see above) — was flagged "if it exists" in the brief; it does, and is small and clean.
- **`company_deposit_links`** exists as a real table with FKs to `companies`/`deposits`, and is confirmed **still empty (0 rows)** — matches prior notes.

---

## (b) Company / project gap analysis

### Company model — exists, is small, and is disconnected from the entity-resolution pipeline that was supposed to feed it
- **`companies`** (41 rows): `id`, `name`, `short_name`, `ticker`, `exchange`, `isin`, `country_incorporation`, `country_operations` (array), `company_type`, `stage`, `primary_commodity`, `commodities` (array), `market_cap_usd`, `employees`, `website`, `is_active`, `type`. This is a hand-curated watchlist of ~41 mining companies (for financial-analysis purposes — tickers, market cap), not derived from the deposit data.
- **`company_deposit_candidates`** (1,749 rows): FK to both `companies` and `deposits`. Has `match_score`, `extraction_method`, `source_table`, `source_chunk_id` (→ document chunks — this table is populated by an NLP/LLM extraction pass over ingested documents), `matched_snippet`, `status`. **100% of rows have `status='pending'`** — none have ever been reviewed/approved.
- **`company_deposit_links`** (0 rows): the "confirmed" table this pipeline was meant to populate once candidates are reviewed. It is empty — the review step never happened (or the mechanism to promote candidate→link was never run). **The company↔deposit relationship is effectively 0% resolved in usable form today.**
- **`company_deposit_candidates_for_review`** is a convenience VIEW joining candidates to company name/ticker/deposit name for a human reviewer — exists but, again, nothing has been reviewed.
- Financial-statement subsystem tied to `companies`: `documents_meta`/`financial_documents_meta` (34 / 14 rows), `chunks`/`financial_chunks` (1,665 / 3,609 rows, both with populated `embedding` — pgvector — columns, 100% of `chunks` rows have a non-null embedding), `balance_sheet`, `cash_flow`, `income_statement`, `financial_ratios` — a full RAG + financial-statement-extraction subsystem exists around `companies`, independent of the deposit/geology side of the schema. This looks like the beginnings of a genuinely separate "financial intelligence" domain that happens to share the `companies` table as its anchor.

### Project concept — does not exist in any form
A search of all table and column names for `%project%` returned **zero hits** anywhere in the schema (only `%compan%` matched anything). There is no `projects` table, no `project_id` column on `deposits`, `locations`, or anywhere else, and no other grouping construct that plays a "project" role except the very coarse, sparsely-populated `deposit_group_local` genetic-classification field on `deposits` (which is a mineral-deposit-type taxonomy, not an operational/corporate project grouping). **The gold schema's `core.projects` concept has to be invented fresh — there is nothing to seed it from in bronze**, beyond possibly deriving candidate project groupings from `company_deposit_candidates`/future `company_deposit_links` (deposits owned by the same company, spatially clustered) once that pipeline is actually resolved.

---

## (c) Commodity / mineral vocabulary reconciliation

Multiple parallel vocabularies exist and are only partially reconciled:

1. **`commodities`** (287 rows) — the canonical lookup, cleanly FK'd from `deposit_commodities` (100% resolved, NOT NULL FK) and `deposit_endowment` (100% resolved in practice).
2. **`minerals`** (6,205 rows) — canonical mineral species lookup (Mindat/IMA-derived), FK'd from `deposit_mineralogy.mineral_id` but only **85% resolved** (2,145 of 14,327 rows have `mineral_id IS NULL`, relying on the free-text `mineral_name_local` instead). Also used by `age_measured.mineral_id` and `mineral_name_translations`.
3. **WA-specific commodity token pipeline** — three tables document what was clearly an ETL reconciliation exercise for the Washington State load, not a live/general vocabulary:
   - `wa_canonical_commodity_tok` (9,334 rows): raw token-level extraction (`canonical_id`, `token`, `role`, `mentions`) — looks like frequency-counted tokens pulled from WA source text.
   - `wa_commodity_xwalk_raw` (124 rows): candidate token→commodity mapping with `n_deposits`, `n_primary`, `commodity_id` (stored as **text**, not integer — a data-quality smell), `commodity_name`, `method` (presumably fuzzy-match/manual/etc.).
   - `wa_commodity_xwalk` (120 rows): the finalized token→`commodity_id` (integer, proper type) crosswalk — this is what actually got applied to produce `deposit_commodities` rows for the WA cohort.
   
   These three are staging/working tables for a one-time ETL job. They're valuable as **documentation of the reconciliation logic** (in case the same messy commodity strings recur in future regional loads) but are not something the gold schema should read from directly — the result of that work is already baked into `deposit_commodities`.
4. **Mineral name translation**: `mineral_name_translations` (+ two `_bak_20260910*` backups) — a table mapping local-language mineral names to canonical `minerals.mineral_id`; parallels the WA commodity crosswalk pattern but for minerals, presumably used across multiple regional loads (not WA-specific by name). Live table appears real; backups are noise.

**Net assessment:** the *commodity* vocabulary is close to fully reconciled (only edge cases outstanding). The *mineral* vocabulary has a real, sizeable (15%) unresolved tail in `deposit_mineralogy` that a gold schema migration will need to either re-run matching on or carry forward as "unmatched, local-name-only" rows.

---

## (d) Entity-resolution / duplicate risks — concrete examples

1. **Deposit name collisions are real and material**, driven mostly by generic historical mining-claim names (this pattern is overwhelmingly from the WA cohort, which inherited literal historical claim names from DGER records):
   - "Last Chance" — 18 deposits sharing the location's name
   - "Eureka" — 16
   - "Summit", "Rainbow", "Copper King", "Keystone", "San Jorge", "Copper Queen", "La Esperanza", "San Antonio" — 8 each
   - "Washington", "Sunset", "Hidden Treasure", "Smith", "Cantera s/n", "Apex" — 7 each
   - Plus explicitly-unnamed placeholders: "Sin nombre" (Spanish "no name") — 66 occurrences, "s/n" — 21 occurrences
   
   None of these are necessarily *wrong* (many historical mining claims genuinely reuse common names like "Eureka" across different districts/states), but a gold schema that wants a "canonical deposit identity" cannot dedupe on name alone — it needs geography (which is available per-row via `locations`) as the disambiguator, and even then two nearby claims named "Eureka" could be the same physical feature recorded twice by different source surveys.

2. **No global external-ID scheme.** Every source uses its own convention:
   - WA: `WA:<numeric>` embedded unstructured inside `deposits.comments` (not a column)
   - SIGAM: presumed positional load from `sigam_deposits.deposit_id`/`numero_de_deposito`, no declared crosswalk column found
   - `locations.external_id`/`legacy_id` exist as real columns but are sparse/inconsistently populated across sources (e.g., the Brazil/Tasmania/Finland sample rows inspected had `external_id = NULL` and only `legacy_id` populated with source-internal numeric strings)
   
   A gold schema needs to mint its own stable global IDs and store per-source natural keys in a structured `(source_system, source_id)` pattern rather than continuing the current mix of "sometimes a column, sometimes free text in comments."

3. **`samples` vs `deposits` total disconnection** (detailed in section (a)) is itself an entity-resolution risk in reverse: there is currently no way to say "these 4.1M samples belong to this deposit" at all, so any future geochemistry-by-deposit rollup requires new spatial/name-matching work, not just a schema rename.

4. **Duplicate/near-duplicate location names at high multiplicity are mostly benign** — the biggest ones (`"NSW - SOIL"` at 948,916 occurrences, `"NSW - STREAM"` at 323,117, `"NSW - ROCKCHIP"` at 120,342, etc.) are clearly **survey/campaign labels reused as a placeholder `locationname`** for hundreds of thousands of individual sample points, not real duplicate-entity collisions — each row still has distinct lat/lon. This is a naming-convention quirk (bulk import didn't always give distinct names) rather than a resolution risk, but it does mean `locationname` cannot be treated as a meaningful location identity/label for a large fraction of rows — geometry is the real identity there.

5. **Parallel `_export` tables silently drift from base tables.** `deposits_export` (8,932) vs `deposits` (8,946), `deposit_mineralogy_export` (12,180) vs `deposit_mineralogy` (14,327) — a ~15% gap consistent with the unresolved-mineral-id rows being excluded from the export. If any downstream consumer reads `_export` while another reads the base table, they are already seeing inconsistent deposit/mineralogy counts today.

---

## (e) Noise tables vs real candidate sources

**Confirmed noise (backups / one-off scratch, safe to exclude from gold migration):**
- `deposits_bak_20260910`, `deposits_bak_wa_20260910`
- `deposit_commodities_bak_20260910`, `deposit_commodities_bak_wa_20260910`
- `deposit_mineralogy_bak_20260910`, `deposit_mineralogy_bak_wa_20260910`, `deposit_mineralogy_bak_mineraltrans_20260910`
- `age_measured_bak_agemin_20260910`
- `mineral_name_translations_bak_20260910b`, `mineral_name_translations_bak_20260910c`
- `locations_deposit_coords_bak_20260909`, `locations_deposit_coords_bak_20260909_r2`, `locations_divid_bak_20260910`, `locations_zerocoord_bak_20260910`
- `sigam_deposits_coords_bak_20260909_r2`
- `lithodat_isactive_updates_log`, `lithodat_value_updates_log` — ETL run logs, not data
- `dupe_resolve_output` style one-off scratch (not DB tables, but noted in the working directory — n/a here)

**Regional raw-source staging (real historical data, but shaped for one-time ETL, not for direct gold consumption — should be re-derived-from, not read live by the app):**
- All `WA_*` tables (metallic, gold_silver, nonmetallic, arsenic, mercury, radon, asbestos, coal_*, iaml_*, argon/carbon/fission_track/luminescence/uranium/fossil/other_analysis `_age` tables, `major_element_chemistry`, `trace_element_chemistry`, `citations`, `preferred_significands`, `shape_division_mapping`, `mining_distircts_wa` [sic, typo in source table name]) — this is the pre-transform Washington DGER extract. Confirmed already fully absorbed into `deposits`/`deposit_commodities`/`deposit_mineralogy`/`age_measured`/`age_stratigraphic` per prior session's completed pipeline (per memory) and cross-checked here via the `createdby='claude_wa_20260910'` counts matching exactly.
- All `GreenlandExternal/Geochron/HeavyMinerals/Rocks/SSSW/Soils/Soils_v2` tables — raw Greenland source import.
- All `NOR_*` tables (`industrimineralforekomst*`, `industrimineralprospekt*`, `industrimineralregistrering*`, `malmforekomst*`, `malmregistrering*`, `natursteinregistrering*`, `geochemNordkinn2011`) — raw Norwegian source import, Norwegian-language columns, not yet confirmed absorbed into core tables (would need a follow-up pass to confirm coverage, since unlike WA there's no equivalent `createdby` tag proving a completed migration).
- `sigam_deposits`, `sigam_fichas`, `sigam_ficha_ages`, `sigam_ficha_grades`, `sigam_deposit_type_mapping` — raw/intermediate SIGAM Argentina extract; `deposits`/`deposit_commodities` etc. for the Argentina cohort are the transformed output.
- `wa_canonical_commodity_tok`, `wa_commodity_xwalk`, `wa_commodity_xwalk_raw`, `wa_dedup_canonical`, `wa_cluster_assignment`, `wa_deposits_staging` (6,035 rows — pre-final-cleanup WA deposit staging, larger than the final 5,418 WA deposits, confirming rows were dropped/merged during cleanup), `wa_load_map`, `wa_fossil_age_crosswalk` — WA ETL working tables, value is as reconciliation-logic documentation only.
- `lithodat_merged_name_map_manual`, `field_mappings`, `source_codes` — small ETL mapping helper tables, not explored in depth this pass; likely low-value scratch but worth a quick look before discarding since "manual" in the name suggests curated human decisions that might not be reproducible.

**Real candidate sources for the gold schema (core, live, actively-referenced tables):**
- `locations`, `deposits`, `deposit_commodities`, `deposit_mineralogy`, `deposit_endowment`, `deposit_types`
- `samples`, `sample_properties`, `sample_types`, `sample_type_categories`, `fractions`, `fraction_types`, `size_fractions`
- `analytical_results`, `result_classifications`, `analytical_result_reviews`, `analytical_packages`, `analytical_methods`, `analytical_method_lithosurfer_digestion_mapping`, `analytes`, `analyte_population_stats`, `units`, `unitconversions`, `qualifiers`, `laboratories`, `preparation_methods`
- `lithodat_datapoint_concentrations`, `lithodat_datapoint_export` (richer per-result detail/provenance, join via `result_id`)
- `audit_flags`/`lithodat_audit_flags`, `flag_rules`/`lithodat_flag_rules`, `audit_runs`/`lithodat_audit_runs` (two parallel QA subsystems — need a decision on which is authoritative going forward)
- `minerals`, `mineral_name_translations`, `commodities`
- `drillhole_collar`, `drilldiameters`, `drilltypes`, `coresizes`
- `age_measured`, `age_stratigraphic`, `age_reference`, `age_type_reference`, `dating_method_reference`, `dating_instruments`, `stratigraphic_age_reference`
- `lithology`, `lithology_categories`, `lithology_observations`, `lithology_mindat_mapping` (+ `_dedup`), `mindat_rocks`, `mindat_lithology_mapping`, `alterationreference`
- `companies`, `company_deposit_candidates`, `company_deposit_links` (empty but structurally real), `company_deposit_candidates_for_review` (view)
- `documents_meta`, `chunks`, `financial_documents_meta`, `financial_chunks`, `balance_sheet`, `cash_flow`, `income_statement`, `financial_ratios` (a fairly complete separate "financial intelligence" domain)
- `countries`, `divisions`, `spatial_reference_systems`
- `estructuras`, `lineaments`, `lineament_ages`, `lineament_types`, `geochron_analysis_standard`, `geochron_isotope_standards`, `geochron_references` — geological-structure/geochronology reference data, not explored in depth this pass but structurally look like real, FK'd, live tables worth carrying forward.
- 7 `vw_samples_*` views and `vw_geus_soil_analytical_results` — pre-built convenience views over `samples`/`analytical_results`, useful as a signal of what query shapes the current app actually needs.

---

## (f) Anything surprising

1. **The schema is much more rigorously FK'd than the brief's framing ("informal joins, matching column names without a declared FK") suggested.** The core sample/analytical chain (`samples`→`analytical_results`→`result_classifications`→reviews/flags) and the deposit chain (`deposits`→`deposit_commodities`/`deposit_mineralogy`/`deposit_endowment`) are both fully backed by real `FOREIGN KEY` constraints, not just naming convention. The genuinely informal joins are narrower than expected: `lithodat_datapoint_concentrations`/`lithodat_datapoint_export`→`analytical_results.result_id` (no FK, but verified 100% consistent on a sample), and the complete absence of any `samples`↔`deposits` link (which isn't "informal" — it's simply absent).

2. **`companies` (41 rows) is tiny and disconnected from the geology side.** Given the app's name ("critical minerals AI web app") one might expect the company/financial domain to be a first-class, richly populated part of the data model; instead it's a small hand-picked watchlist with a stalled (0% resolved) attempt to auto-link it to deposits via NLP extraction (`company_deposit_candidates`, all 1,749 rows still `pending`).

3. **There are two parallel, not-fully-reconciled QA/audit subsystems** (`audit_flags`/`audit_runs`/`flag_rules` vs `lithodat_audit_flags`/`lithodat_audit_runs`/`lithodat_flag_rules`), and **two parallel geochemistry storage shapes** (normalized `analytical_results` vs wide `lithodat_datapoint_concentrations`/`export`) that happen to agree with each other where they overlap, but represent duplicated modeling effort/pipelines rather than one clean lineage.

4. **`_export` tables already exist as a semi-gold layer** (`deposits_export`, `deposit_commodities_export`, `deposit_mineralogy_export`) — apparently `isactive=true`-filtered, resolved-only snapshots of the base tables. This is worth investigating before designing a new gold schema from scratch: something in the current app may already depend on this naming convention, and the gold-schema project could either formalize/replace this pattern or risk creating a third parallel copy.

5. **`wa_deposits_staging` had 6,035 rows but only 5,418 made it into `deposits`** — 617 rows (10%) were dropped or merged during WA cleanup; worth understanding why before assuming any regional load "fully" made it to core tables.

6. **The `lithodat_datapoint_concentrations` table is the single largest object in the database by disk size (20 GB)** despite having fewer rows (32.6M) than `analytical_results` (38.0M, 7 GB) — its wide, mostly-text/free-form column shape (56 columns, many `text` type where a narrower type would do, e.g. `Conc` is `numeric` but `detectionlimit`/`sampleweightgm`/`digestiontempcelsius`/`measuredmass` are stored as `text`) is a likely storage/performance concern worth flagging for the gold design.

7. **Minor data-quality smell in the commodity crosswalk itself**: `wa_commodity_xwalk_raw.commodity_id` is typed `text` while the finalized `wa_commodity_xwalk.commodity_id` is `integer` — the raw table was never cleaned up to match, again suggesting these are disposable working tables rather than anything to build on directly.

8. **Geographic breadth is much wider than the "SIGAM + Washington" framing in the task brief implied** — the `locations.datasource` breakdown shows substantial coverage from New South Wales/Tasmania/Victoria (Australia), Finland, Sweden, Ireland, Norway, Nigeria, Saudi Arabia, Ireland, Ireland again via GSI, Spain, Brazil, plus a global zircon U-Th-Pb geochronology compilation (Wu, Fang & Ji) layered on top. The gold schema needs to be source-agnostic by design, not tuned to just the two most recently worked cohorts.

---

## Row-count summary (for reference)

| Table | Rows | Method |
|---|---|---|
| analytical_results | 38,011,936 | pg_class estimate |
| result_classifications | 34,246,988 | pg_class estimate |
| lithodat_datapoint_concentrations | 32,607,738 | pg_class estimate |
| samples | 4,193,871 | exact COUNT(*) |
| lithodat_datapoint_export | 3,596,339 | exact COUNT(*) |
| locations | 3,462,330 | exact COUNT(*) |
| analytical_result_reviews | 2,720,616 | exact COUNT(*) |
| audit_flags | 1,345,911 | exact COUNT(*) |
| lithodat_audit_flags | 149,975 | exact COUNT(*) |
| sample_properties | 91,712 | exact COUNT(*) |
| deposits | 8,946 | exact COUNT(*) |
| minerals | 6,205 | exact COUNT(*) |
| wa_deposits_staging | 6,035 | exact COUNT(*) |
| deposit_commodities | 14,390 | exact COUNT(*) |
| deposit_mineralogy | 14,327 | exact COUNT(*) |
| wa_canonical_commodity_tok | 9,334 | exact COUNT(*) |
| deposit_endowment | 1,399 | exact COUNT(*) |
| company_deposit_candidates | 1,749 | exact COUNT(*) |
| company_deposit_links | 0 | exact COUNT(*) |
| companies | 41 | exact COUNT(*) |
| commodities | 287 | exact COUNT(*) |
| sigam_deposits | 3,351 | exact COUNT(*) |
| age_stratigraphic | 289,737 | exact COUNT(*) |
| age_measured | 35,736 | exact COUNT(*) |
| chunks | 1,665 | exact COUNT(*) |
| financial_chunks | 3,609 | exact COUNT(*) |
| analytical_packages | 1,379 | exact COUNT(*) |
