CREATE TABLE core.project_designations (
  project_designation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id integer NOT NULL REFERENCES core.projects(project_id),
  programme varchar(60) NOT NULL,          -- e.g. EU_CRMA_STRATEGIC_PROJECT
  scope varchar(20),                       -- EU / non-EU
  approval_date date,
  decision_ref text,
  value_chain_stage text,
  materials_as_published text,
  promoter_as_published text,
  promoter_factsheet text,
  countries_as_published text,
  unfc_classification text,
  est_start_production text,               -- mostly a year; some dates/quarters as published
  website text,
  eu_benefit text,
  factsheet_doi text,
  factsheet_url text,
  source_document_id bigint REFERENCES docs.documents(document_id),
  is_active boolean NOT NULL DEFAULT true,
  created_by varchar(100) NOT NULL DEFAULT CURRENT_USER,
  created_date timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, programme)
);