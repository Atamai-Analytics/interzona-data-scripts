-- Run this against interzona_cm ("gold") as AtamaiAdmin. Sets up a foreign-data-wrapper
-- connection to criticialmineralsexp ("bronze") on the same RDS instance, so bulk data
-- movement can happen as plain server-side SQL instead of round-tripping through any client.
--
-- The bronze password is injected via psql's -v flag at invocation time (see the PowerShell
-- command below) — it is never written into this file.

CREATE EXTENSION IF NOT EXISTS postgres_fdw;

CREATE SERVER IF NOT EXISTS bronze_server
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'atamaipsql.cyuxrpe6wnv7.us-east-2.rds.amazonaws.com', port '5432', dbname 'criticialmineralsexp');

-- "AtamaiAdmin" must be double-quoted: unquoted identifiers fold to lowercase in Postgres, and
-- an earlier run of this script failed with role "atamaiadmin" does not exist for exactly that
-- reason — the real role is mixed-case.
CREATE USER MAPPING FOR "AtamaiAdmin"
    SERVER bronze_server
    OPTIONS (user 'AtamaiAdmin', password :'bronze_password');

CREATE SCHEMA IF NOT EXISTS bronze;

-- Imports every bronze table as a foreign table under gold's `bronze` schema — cheap (no
-- storage, just a proxy), and avoids a second round-trip later if something not on today's
-- list turns out to be needed. Re-run IMPORT FOREIGN SCHEMA any time to pick up new bronze
-- tables; existing foreign tables are untouched.
IMPORT FOREIGN SCHEMA public
    FROM SERVER bronze_server
    INTO bronze;

-- sanity check
SELECT count(*) AS foreign_tables_imported FROM information_schema.foreign_tables WHERE foreign_table_schema = 'bronze';
