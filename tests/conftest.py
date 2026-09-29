import os

import pytest

from iris.db import connect, fixtures, insert_record


@pytest.fixture(scope="session")
def admin():
    if os.environ.get("IRIS_TEST_RESET") != "1":
        pytest.fail("Set IRIS_TEST_RESET=1 to test the disposable local database.")
    with connect("postgres") as conn:
        marker = conn.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname = current_database()"
        ).fetchone()[0]
        assert marker == "IRIS-CAND-08 disposable local fixture database", (
            "Refusing to reset a database without the local test database marker"
        )
        print("\nDatabase:", conn.execute(
            "SELECT current_setting('server_version'), public.PostGIS_Lib_Version()"
        ).fetchone())
        yield conn


@pytest.fixture(autouse=True)
def clean_data(admin):
    statement = (
        "TRUNCATE iris_core.features, iris_staging_nrw.features, "
        "iris_staging_peat.features"
    )
    admin.execute(statement)
    yield
    admin.execute(statement)


@pytest.fixture
def seeded():
    records = fixtures()
    for record in records:
        with connect(f"contributor_{record['dataset']}") as conn:
            insert_record(conn, record)
    return records
