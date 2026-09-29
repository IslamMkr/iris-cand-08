# Test results

The Docker checks completed on 2026-09-29 using Python 3.12.14, PostgreSQL 16.9,
and PostGIS 3.5.2.

- **171 tests passed** using real role logins on both an upgraded disposable
  database (13.62 seconds) and a fresh disposable database (13.75 seconds).
- Before applying the fix, the new regression cases produced 22 expected failures:
  out-of-bounds coordinates were accepted in all three tables, and all four runtime
  roles could connect to another database. Four valid-boundary cases already passed.
- The hardening migration rolled back all permission and constraint changes when
  an existing row had invalid coordinates. The invalid record remained unchanged.
- With valid existing data, the migration succeeded and the complete staging/core
  record checksum stayed unchanged.
- The migration was also applied to the existing local IRIS database. Its one NRW
  staging row, two peat staging rows, and three core rows were preserved unchanged.
  The destructive test suite ran only against the disposable databases.
- The image built successfully, and bootstrap applied the hardening migration on
  a fresh volume.
- The sample-data command published three records in the fresh disposable
  database. Running it again added none.
- The test container ran as a non-root user and contained no `.env` file.
- The image's code, tests, fixtures, and dependency files matched the workspace
  when checked.

Before the hardening changes, the native run passed the original 145 tests on
PostgreSQL 16.15/PostGIS 3.4.2.

Hardening regression output, migration checks, full SQL test output, build logs,
and sample-run output are saved locally in `artifacts/hardening-*.txt`. Earlier
Docker logs remain in `artifacts/docker-*.txt`. This folder is ignored by Git.

See [Run tests](README.md#run-tests) to repeat the checks. Tests clear the staging
and core tables, so use a local test database.
