# IRIS-CAND-08 - Contributor Database Isolation

Contributors load their assigned datasets into separate PostgreSQL staging schemas.
A promoter publishes selected records, and the application reads a candidate view.
PostgreSQL enforces the permissions, including for direct SQL connections.

## Run the assignment

Requirements: a running Docker engine with Compose v2 and Python 3.12+ on the
host. PostgreSQL 16.15, PostGIS 3.5.7, and the Python dependencies run in containers.
On Windows, use `python` if `python3` is unavailable; run the Bash examples below
in WSL or Git Bash. On WSL, enable Docker Desktop integration.

From the repository root:

```bash
python3 scripts/verify.py
```

This command generates temporary credentials, builds the image, initializes a fresh
PostgreSQL/PostGIS database, runs the permission and data tests, and demonstrates
loading, publishing, and reading three sample records. It prints the SQL checks
and removes its temporary database and verification image afterward. No manual
database preparation or external credentials are needed.

The database image creates the database, then `scripts/init-db.sh` runs
`sql/setup.sql` to create its roles, schemas, tables, view, and promotion function
in one transaction. Docker images are pinned by digest, and Python dependencies
are pinned with hashes. Tests use real authenticated role connections.

Verification uses `compose.verify.yaml`, a unique Docker project, and a temporary
`iris_test` database without an exposed host port. It does not need a `.env` file.
The optional interactive demo below uses `compose.yaml` and a persistent `iris`
database. Each test clears only the verification database's business tables.

Verified from a clean Git checkout: **257 tests passed**, followed by successful
ingestion, promotion, and application reads of all three sample records.
On success, the command ends with:

```text
Tests and demo passed. Temporary database removed.
```

To save the permission-test transcript in Bash:

```bash
mkdir -p artifacts
set -o pipefail
python3 scripts/verify.py 2>&1 | tee artifacts/permission-tests.txt
```

## Access model

| Role               | Allowed access                                       |
| ------------------ | ---------------------------------------------------- |
| `contributor_nrw`  | `SELECT`, `INSERT` on `iris_staging_nrw.features`    |
| `contributor_peat` | `SELECT`, `INSERT` on `iris_staging_peat.features`   |
| `promoter`         | Read both staging tables; execute `iris_ops.promote` |
| `app_readonly`     | `SELECT` on `iris_api.candidates`                    |

Contributors cannot modify existing rows, alter tables, access another dataset,
write core records, or promote data. Runtime roles cannot assume privileged roles
or use the large-object API. The database cluster is dedicated to this assignment.
Setup revokes runtime access to every other existing database. System metadata
remains visible.

New databases receive PostgreSQL's default public connection privileges. If an
administrator adds one later, create it with connections disabled, revoke public
access, then enable connections and grant access only to its intended users:

```sql
CREATE DATABASE another_database ALLOW_CONNECTIONS false;
REVOKE ALL ON DATABASE another_database FROM PUBLIC;
ALTER DATABASE another_database ALLOW_CONNECTIONS true;
```

These commands require an administrator; none of the runtime roles can create
databases. The supplied Docker configurations create no additional databases
after setup.

Non-login roles own the objects. The promotion function runs as a separate owner
with only the permissions needed to read staging and insert core records. Its
fixed `search_path` and fixed table references protect the publication operation.
The application view exposes published records without granting core-table access.

Promotion identifies a dataset, country, and source ID. Calling the function
approves that record. It preserves staging, returns `1` when inserting and `0`
when already published, and cannot overwrite a published record. Tests cover
concurrent calls with both commit and rollback.

## Data contract

| Field          | Required value                                                    |
| -------------- | ----------------------------------------------------------------- |
| `country_code` | Two uppercase letters; included in record keys and joins          |
| `source_id`    | Identifier containing a nonblank character                        |
| `geom`         | Valid, nonempty 2D MultiPolygon with explicit SRID 4326           |
| `source_date`  | Date from `0001-01-01` through `9999-12-31`, readable by Python   |
| `uncertainty`  | Nonblank description, explicitly stating when accuracy is unknown |

Coordinates are longitude and latitude in degrees, bounded by ±180 and ±90.
Missing CRS, invalid geometry, and incomplete records are rejected; values are
never silently repaired or invented. Blank text means Unicode White_Space plus
zero-width space (U+200B) and BOM (U+FEFF). Accepted text is stored unchanged.

Staging keys are `(country_code, source_id)`; the core key is
`(country_code, dataset, source_id)`.
Access is assigned by dataset, not country. The three synthetic fixtures reuse
one source ID across NRW/DE and peat/DE/NL to verify identity isolation.

The application interface supports reading published geometry and basic GeoJSON
output, for example `ST_AsGeoJSON(geom)`. Runtime roles cannot read PostGIS's
`spatial_ref_sys` reference table, so operations that need it, including
`ST_Transform(geom, ...)` and `ST_Area(geom::geography)`, fail with a permission
error. Spatial calculations are outside this assignment's interface; adding them
would require a deliberate extension of the access model.

## Optional persistent demo

For an interactive database, generate local credentials and run the demo:

```bash
python3 scripts/init_env.py
docker compose up -d --wait db
docker compose run --build --rm demo
```

Skip credential generation if `.env` already exists; the script refuses to
overwrite it. Passwords are supplied through the environment and kept outside
Git and container images. The database is available at `127.0.0.1:55432`.
Repeating the demo leaves existing records unchanged. `docker compose down`
stops the containers and retains the demo data for the next run.

Setup runs only on an empty database volume. Editing `sql/setup.sql` or `.env`
and restarting does not migrate an existing database or rotate its passwords.
The SQL is a one-time bootstrap, not a rerunnable migration. The verification
command always tests a fresh database; it does not validate an existing demo volume.

For a disposable demo whose records can be deleted, recreate it explicitly:

```bash
docker compose down --volumes  # Deletes all persistent demo records.
docker compose up -d --wait db
docker compose run --build --rm demo
```

For records that must be retained, use a reviewed migration or backup/restore
procedure. This image pin uses Alpine; a demo volume created with the previous
Debian image should be reset if disposable, or moved with a logical dump/restore
and validation rather than reused across the OS change. Password rotation also
requires `ALTER ROLE ... PASSWORD` and corresponding environment updates.

Open a promoter session:

```bash
docker compose exec db sh -c 'PGPASSWORD="$IRIS_PROMOTER_PASSWORD" psql -X -h 127.0.0.1 -U promoter -d iris'
```

```sql
SELECT * FROM iris_staging_nrw.features;
SELECT iris_ops.promote('nrw', 'DE', 'fixture-001'); -- 0: already published by the demo
```

Open an application session:

```bash
docker compose exec db sh -c 'PGPASSWORD="$IRIS_APP_PASSWORD" psql -X -h 127.0.0.1 -U app_readonly -d iris'
```

```sql
SELECT country_code, dataset, source_id FROM iris_api.candidates; -- allowed
SELECT * FROM iris_core.features;                              -- denied
```

Use `\q` to leave a database session.

## Contributor onboarding and offboarding

These examples use the optional persistent demo above. To add a contributor,
enter a new password in Bash and open an admin session:

```bash
read -rs -p "New contributor password: " IRIS_NEW_PASSWORD
export IRIS_NEW_PASSWORD
docker compose exec -e IRIS_NEW_PASSWORD db psql -X -U postgres -d iris
```

Grant only the assigned dataset:

```sql
\getenv new_password IRIS_NEW_PASSWORD
BEGIN;
CREATE ROLE contributor_example LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'new_password';
GRANT CONNECT ON DATABASE iris TO contributor_example;
GRANT USAGE ON SCHEMA iris_staging_nrw TO contributor_example;
GRANT SELECT, INSERT ON iris_staging_nrw.features TO contributor_example;
COMMIT;
```

Exit with `\q`, run `unset IRIS_NEW_PASSWORD`, and verify the new account:

```bash
docker compose exec db psql -X -h 127.0.0.1 -U contributor_example -d iris
```

```sql
SELECT country_code, source_id FROM iris_staging_nrw.features; -- allowed
SELECT * FROM iris_staging_peat.features;                     -- denied
SELECT * FROM iris_core.features;                             -- denied
```

To remove access, open an admin session with
`docker compose exec db psql -X -U postgres -d iris`, then run:

```sql
BEGIN;
ALTER ROLE contributor_example NOLOGIN PASSWORD NULL;
REVOKE SELECT, INSERT ON iris_staging_nrw.features FROM contributor_example;
REVOKE USAGE ON SCHEMA iris_staging_nrw FROM contributor_example;
REVOKE CONNECT ON DATABASE iris FROM contributor_example;
COMMIT;
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = 'contributor_example' AND pid <> pg_backend_pid();
```

Remove any additional grants or memberships too. Confirm that active sessions end
and new connections fail. Contributed records remain in place.

## Assumptions and limits

The two datasets have fixed layouts, and each supplied login represents one role.
A promotion call constitutes approval; runtime roles cannot change published
records, and there is no separate approval history. Publication does not assert
site suitability.
Country codes are checked for format, and coordinate bounds cannot detect every
incorrect CRS label. Administrators are trusted. Production extensions would
include individual identities, recorded approvals, reviewed corrections, managed
secrets, and source-specific geographic validation.

## Files

| Files                                                                                              | Purpose                                                           |
| -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [sql/setup.sql](sql/setup.sql)                                                                     | Complete initial schema, roles, promotion function, and grants    |
| [scripts/verify.py](scripts/verify.py)                                                             | Single-command tests and demonstration in a fresh database        |
| [scripts/init-db.sh](scripts/init-db.sh)                                                           | Automatic container database setup                                |
| [scripts/init_env.py](scripts/init_env.py)                                                         | Credentials for the optional persistent demo                      |
| [iris/db.py](iris/db.py), [iris/**main**.py](iris/__main__.py)                                     | Database helpers and the sample-data command                      |
| [tests/](tests/), [fixtures/features.json](fixtures/features.json)                                 | Permission/data tests and three synthetic records                 |
| [compose.verify.yaml](compose.verify.yaml), [compose.yaml](compose.yaml), [Dockerfile](Dockerfile) | Verification and persistent-demo containers                       |
| [requirements.txt](requirements.txt), [pyproject.toml](pyproject.toml)                             | Locked dependencies, Python requirement, and pytest configuration |
