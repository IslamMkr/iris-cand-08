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

REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name"
  TO contributor_nrw, contributor_peat, promoter, app_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- PostGIS types/functions remain usable, but extension lookup tables are not
-- application read interfaces. Also cover image-provided optional extensions.
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
-- Bootstrap scripts run as this trusted administrator; future admin-created
-- functions must also require explicit grants.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
