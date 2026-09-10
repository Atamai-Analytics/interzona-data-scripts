-- SIGAM fact-sheet staging schema (criticialmineralsexp), created 2026-09-09.
-- Additive only: no existing table is touched. Populated from sigam_fichas/sigam_fichas.jsonl.
-- Load order: 00_schema.sql, then a00..a14 (parent), then g00..g03 (grades), then x00 (ages).

CREATE TABLE sigam_fichas (
  depno               integer PRIMARY KEY,
  http_status         integer,
  is_ok               boolean,
  fecha_actualizacion text,
  nombre              text,
  lat                 double precision,
  lon                 double precision,
  commodities         text,
  tipo_deposito       text,
  estado_deposito     text,
  n_grades            integer,
  n_ages              integer,
  n_refs              integer,
  url                 text,
  loaded_at           timestamp DEFAULT now()
);

CREATE TABLE sigam_ficha_grades (
  depno       integer REFERENCES sigam_fichas(depno),
  seq         integer,
  kind        text,   -- 'produccion' | 'recurso'
  slot        text,   -- 'grade' | 'amount'
  commodity   text,
  value       text,
  unit_note   text,
  PRIMARY KEY (depno, kind, slot, seq)
);

CREATE TABLE sigam_ficha_ages (
  depno         integer REFERENCES sigam_fichas(depno),
  seq           integer,
  age_ma        text,
  uncertainty   text,
  method        text,
  objeto_datado text,
  concentrado   text,
  origen_roca   text,
  nombre_formal text,
  evento        text,
  referencia    text,
  PRIMARY KEY (depno, seq)
);
