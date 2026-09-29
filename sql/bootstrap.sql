-- Run once, as the bootstrap administrator, in a dedicated empty local database.
-- Passwords stay in the process environment; psql safely quotes their SQL values.
\set ON_ERROR_STOP on
\getenv nrw_password IRIS_NRW_PASSWORD
\getenv peat_password IRIS_PEAT_PASSWORD
\getenv promoter_password IRIS_PROMOTER_PASSWORD
\getenv app_password IRIS_APP_PASSWORD
SELECT length(:'nrw_password') >= 16 AND length(:'peat_password') >= 16
   AND length(:'promoter_password') >= 16 AND length(:'app_password') >= 16
   AS passwords_valid \gset
\if :passwords_valid
\else
  \echo 'Set all four IRIS_*_PASSWORD environment variables to at least 16 characters.'
  \quit 1
\endif

BEGIN;
SELECT current_database() AS database_name \gset
CREATE EXTENSION IF NOT EXISTS postgis;
COMMENT ON DATABASE :"database_name" IS 'IRIS-CAND-08 disposable local fixture database';
\ir 001_roles.sql
\ir 002_data.sql
\ir 003_access.sql
\ir 004_hardening.sql
COMMIT;
