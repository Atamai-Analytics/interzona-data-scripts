-- Recreates the 14 indexes dropped from interzona_cm on 2026-11-16 (zero scans since the database was created; about 15 MB in total).
-- Kept on purpose: geochem.idx_ar_analyte_name (802 MB, used by AI-written queries on three surveys), the document-chunk vector index,
-- spatial (GiST) indexes on new tables, core.idx_facility_capacity_commodity.
CREATE INDEX idx_companies_name_trgm ON core.companies USING gin (name gin_trgm_ops);
CREATE INDEX idx_analytes_critical ON geochem.analytes USING btree (is_critical_mineral) WHERE is_critical_mineral;
CREATE INDEX idx_extracted_facts_data ON docs.extracted_facts USING gin (fact_data);
CREATE INDEX idx_geology_summary_observations ON core.geology_summary USING gin (observations);
CREATE INDEX idx_geology_summary_primary_age ON core.geology_summary USING btree (primary_age_ma);
CREATE INDEX idx_chunks_commodity ON docs.document_chunks USING btree (commodity_id);  -- partitioned parent: creates it on every partition
CREATE INDEX idx_lineaments_jurisdiction ON geochem.lineaments USING btree (jurisdiction_id);
CREATE INDEX lo_staging_lithology_id_idx ON geochem.lo_staging USING btree (lithology_id);
CREATE INDEX price_series_commodity_idx ON markets.price_series USING btree (commodity_id);
CREATE INDEX idx_sdc_deposit ON geochem.sample_deposit_context USING btree (deposit_uid);
CREATE INDEX idx_sdc_occ ON geochem.sample_deposit_context USING btree (matched_occurrence_id);
CREATE INDEX idx_drillholes_name ON drilling.drillholes USING btree (lower(hole_name));
CREATE INDEX rmis_recycling_material_idx ON markets.rmis_recycling USING btree (material);
CREATE INDEX eiti_project_production_country_name_year_idx ON markets.eiti_project_production USING btree (country_name, year);
