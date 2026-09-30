-- Complete initial setup for the assignment, in a dedicated empty database.
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
COMMENT ON DATABASE :"database_name" IS 'IRIS-CAND-08 application database';

-- Runtime identities never own database objects or inherit another identity.
CREATE ROLE iris_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE iris_promote_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE contributor_nrw LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'nrw_password';
CREATE ROLE contributor_peat LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'peat_password';
CREATE ROLE promoter LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'promoter_password';
CREATE ROLE app_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'app_password';

-- Login roles are cluster-wide. PUBLIC access to another database would let
-- them bypass the intended database boundary, even when iris itself is locked.
-- This covers existing databases; revoke PUBLIC access when provisioning any new one.
DO $$
DECLARE database_name text;
BEGIN
  FOR database_name IN SELECT datname FROM pg_database
  LOOP
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', database_name);
  END LOOP;
END;
$$;
GRANT CONNECT ON DATABASE :"database_name"
  TO contributor_nrw, contributor_peat, promoter, app_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- Keep extension lookup tables outside the runtime read interface. Functions
-- needing spatial_ref_sys (including ST_Transform and geography area) require
-- additional access and are outside this assignment's supported operations.
-- Also cover image-provided optional extensions.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
DO $$
DECLARE extension_schema text;
BEGIN
  FOR extension_schema IN
    SELECT nspname FROM pg_namespace WHERE nspname IN ('tiger', 'tiger_data', 'topology')
  LOOP
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', extension_schema);
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC', extension_schema);
  END LOOP;
END;
$$;

CREATE SCHEMA iris_staging_nrw AUTHORIZATION iris_owner;
CREATE SCHEMA iris_staging_peat AUTHORIZATION iris_owner;
CREATE SCHEMA iris_core AUTHORIZATION iris_owner;
CREATE SCHEMA iris_ops AUTHORIZATION iris_owner;
CREATE SCHEMA iris_api AUTHORIZATION iris_owner;

-- Global, per-creator defaults: a schema-local revoke cannot remove the built-in
-- PUBLIC EXECUTE grant. Tables/views keep PostgreSQL's deny-by-default behavior.
ALTER DEFAULT PRIVILEGES FOR ROLE iris_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE iris_promote_executor REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
-- Setup runs as this trusted administrator; future admin-created
-- functions must also require explicit grants.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Large objects are outside IRIS's data interface. Restrict every overloaded entry point
-- so PUBLIC function privileges cannot bypass the table grants.
DO $$
DECLARE routine regprocedure;
BEGIN
  FOR routine IN
    SELECT p.oid::regprocedure
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'pg_catalog' AND p.proname IN (
      'lo_create', 'lo_creat', 'lo_from_bytea', 'lo_put', 'lo_get',
      'lo_import', 'lo_export', 'lo_unlink', 'lo_open', 'lo_close',
      'loread', 'lowrite', 'lo_lseek', 'lo_lseek64', 'lo_tell', 'lo_tell64',
      'lo_truncate', 'lo_truncate64'
    )
  LOOP
    EXECUTE format(
      'REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, contributor_nrw, contributor_peat, promoter, app_readonly',
      routine
    );
  END LOOP;
END;
$$;

SET LOCAL ROLE iris_owner;

-- Text must contain a character outside Unicode White_Space, U+200B, and U+FEFF.
-- The explicit character set avoids locale-dependent blank checks. Accepted
-- values are stored unchanged. Dates must also be readable by Python.

CREATE TABLE iris_staging_nrw.features (
  country_code text NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
  source_id text NOT NULL CONSTRAINT features_source_id_text_check
    CHECK (length(btrim(source_id, U&'\0009\000A\000B\000C\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\200B\FEFF')) > 0),
  -- A geometry(...,4326) typmod silently labels SRID=0 input as 4326. Explicit
  -- checks preserve the contract: unknown CRS must be rejected, never invented.
  geom public.geometry NOT NULL
    CHECK (public.ST_SRID(geom) = 4326)
    CHECK (public.ST_GeometryType(geom) = 'ST_MultiPolygon')
    CHECK (public.ST_NDims(geom) = 2)
    CHECK (NOT public.ST_IsEmpty(geom) AND public.ST_IsValid(geom))
    CONSTRAINT features_geom_bounds_check CHECK (
      public.ST_XMin(geom::public.box3d) >= -180
      AND public.ST_XMax(geom::public.box3d) <= 180
      AND public.ST_YMin(geom::public.box3d) >= -90
      AND public.ST_YMax(geom::public.box3d) <= 90
    ),
  source_date date NOT NULL CONSTRAINT features_source_date_range_check
    CHECK (source_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
  uncertainty text NOT NULL CONSTRAINT features_uncertainty_text_check
    CHECK (length(btrim(uncertainty, U&'\0009\000A\000B\000C\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\200B\FEFF')) > 0),
  PRIMARY KEY (country_code, source_id)
);

CREATE TABLE iris_staging_peat.features
  (LIKE iris_staging_nrw.features INCLUDING ALL);

CREATE TABLE iris_core.features (
  LIKE iris_staging_nrw.features INCLUDING CONSTRAINTS,
  dataset text NOT NULL CHECK (dataset IN ('nrw', 'peat')),
  PRIMARY KEY (country_code, dataset, source_id)
);

CREATE VIEW iris_api.candidates AS
  SELECT country_code, dataset, source_id, geom, source_date, uncertainty
  FROM iris_core.features;

COMMENT ON VIEW iris_api.candidates IS
  'Published feature records available to read-only application clients.';

CREATE FUNCTION iris_ops.promote(
  p_dataset text, p_country_code text, p_source_id text
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  blank_characters constant text := U&'\0009\000A\000B\000C\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\200B\FEFF';
  staged record;
  inserted integer;
BEGIN
  IF p_dataset IS NULL OR p_dataset NOT IN ('nrw', 'peat')
     OR p_country_code IS NULL OR p_country_code !~ '^[A-Z]{2}$'
     OR p_source_id IS NULL OR length(pg_catalog.btrim(p_source_id, blank_characters)) = 0 THEN
    RAISE EXCEPTION 'Expected dataset nrw/peat, uppercase country code, and source ID'
      USING ERRCODE = '22023';
  END IF;

  -- No caller-controlled identifiers or dynamic SQL. Contributors cannot modify
  -- an existing row, so selecting a specific key identifies the reviewed data.
  IF p_dataset = 'nrw' THEN
    SELECT country_code, source_id, geom, source_date, uncertainty INTO staged
    FROM iris_staging_nrw.features
    WHERE country_code = p_country_code AND source_id = p_source_id;
  ELSE
    SELECT country_code, source_id, geom, source_date, uncertainty INTO staged
    FROM iris_staging_peat.features
    WHERE country_code = p_country_code AND source_id = p_source_id;
  END IF;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Staging record not found' USING ERRCODE = 'P0002';
  END IF;

  INSERT INTO iris_core.features
    (country_code, dataset, source_id, geom, source_date, uncertainty)
  VALUES
    (staged.country_code, p_dataset, staged.source_id, staged.geom,
     staged.source_date, staged.uncertainty)
  ON CONFLICT (country_code, dataset, source_id) DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  RETURN inserted;
END;
$$;

RESET ROLE;
ALTER FUNCTION iris_ops.promote(text, text, text) OWNER TO iris_promote_executor;

GRANT USAGE ON SCHEMA iris_staging_nrw TO contributor_nrw;
GRANT USAGE ON SCHEMA iris_staging_peat TO contributor_peat;
GRANT SELECT, INSERT ON iris_staging_nrw.features TO contributor_nrw;
GRANT SELECT, INSERT ON iris_staging_peat.features TO contributor_peat;

GRANT USAGE ON SCHEMA iris_staging_nrw, iris_staging_peat, iris_ops TO promoter;
GRANT SELECT ON iris_staging_nrw.features, iris_staging_peat.features TO promoter;

GRANT USAGE ON SCHEMA iris_staging_nrw, iris_staging_peat, iris_core
  TO iris_promote_executor;
GRANT SELECT ON iris_staging_nrw.features, iris_staging_peat.features
  TO iris_promote_executor;
GRANT INSERT ON iris_core.features TO iris_promote_executor;
-- An explicit ON CONFLICT target requires SELECT on its indexed columns.
GRANT SELECT (country_code, dataset, source_id) ON iris_core.features
  TO iris_promote_executor;

REVOKE ALL ON FUNCTION iris_ops.promote(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION iris_ops.promote(text, text, text) TO promoter;

GRANT USAGE ON SCHEMA iris_api TO app_readonly;
GRANT SELECT ON iris_api.candidates TO app_readonly;

COMMIT;
