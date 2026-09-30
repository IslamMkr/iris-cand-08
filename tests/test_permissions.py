from concurrent.futures import ThreadPoolExecutor
import secrets
import time

import psycopg
from psycopg import sql
import pytest

from iris.db import (
    DATASETS, RUNTIME_ROLES, connect, execute, fixtures, insert_record,
)


def denied(conn, statement, params=None):
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as caught:
        execute(conn, statement, params)
    assert caught.value.sqlstate == "42501"
    print("  DENIED SQLSTATE=42501")


def promote(conn, record):
    return execute(conn, "SELECT iris_ops.promote(%s, %s, %s)", (
        record["dataset"], record["country_code"], record["source_id"],
    )).fetchone()[0]


@pytest.mark.parametrize("role", RUNTIME_ROLES)
def test_real_login_and_password_authentication(role):
    with connect(role) as conn:
        assert conn.execute("SELECT session_user, current_user").fetchone() == (role, role)
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        connect(role, password="deliberately-incorrect-password")


@pytest.mark.parametrize("role", RUNTIME_ROLES)
def test_runtime_login_is_restricted_to_iris(role, admin, monkeypatch):
    databases = admin.execute(
        "SELECT datname, datallowconn, "
        "has_database_privilege(%s, oid, 'CONNECT'), "
        "has_database_privilege(%s, oid, 'TEMP') "
        "FROM pg_database WHERE datname <> current_database() ORDER BY datname",
        (role, role),
    ).fetchall()
    assert any(name == "postgres" for name, *_ in databases)
    for name, allows_connections, can_connect, can_create_temp in databases:
        if allows_connections:
            monkeypatch.setenv("PGDATABASE", name)
            with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
                with connect(role):
                    pass
            print(f"[{role}] CONNECT {name}: DENIED")
        assert not can_connect, (role, name)
        assert not can_create_temp, (role, name)


def test_roles_are_not_owners_or_privileged(admin):
    rows = admin.execute(
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
        "rolbypassrls, rolinherit FROM pg_roles WHERE rolname = ANY(%s)",
        (list(RUNTIME_ROLES),),
    ).fetchall()
    assert len(rows) == 4
    assert all(not any(row[1:]) for row in rows)
    assert admin.execute(
        "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
        "WHERE r.rolname = ANY(%s)", (list(RUNTIME_ROLES),),
    ).fetchone()[0] == 0
    assert admin.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner "
        "WHERE r.rolname = ANY(%s)", (list(RUNTIME_ROLES),),
    ).fetchone()[0] == 0
    assert admin.execute(
        "SELECT bool_and(NOT rolcanlogin AND NOT rolsuper) FROM pg_roles "
        "WHERE rolname IN ('iris_owner', 'iris_promote_executor')"
    ).fetchone()[0]


@pytest.mark.parametrize("dataset", DATASETS)
def test_contributor_insert_inspect_and_copy(dataset):
    record = next(r for r in fixtures() if r["dataset"] == dataset)
    with connect(f"contributor_{dataset}") as conn:
        assert insert_record(conn, record).rowcount == 1
        table = sql.Identifier(f"iris_staging_{dataset}", "features")
        rows = execute(conn, sql.SQL("SELECT country_code, source_id FROM {}").format(table)).fetchall()
        assert rows == [(record["country_code"], record["source_id"])]
        # Client-side COPY FROM STDIN needs no server filesystem capability.
        statement = sql.SQL(
            "COPY {} (country_code, source_id, geom, source_date, uncertainty) FROM STDIN"
        ).format(table)
        with conn.cursor().copy(statement) as copy:
            copy.write_row((record["country_code"], "copy-002", record["ewkt"],
                            record["source_date"], record["uncertainty"]))
        assert conn.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] == 2


FORBIDDEN_TABLE_ACTIONS = (
    "SELECT * FROM {table}",
    "INSERT INTO {table} (country_code, source_id, geom, source_date, uncertainty) "
    "VALUES ('DE','blocked',public.ST_GeomFromEWKT("
    "'SRID=4326;MULTIPOLYGON(((7 51,8 51,8 52,7 52,7 51)))'),'2026-01-01','synthetic')",
    "UPDATE {table} SET uncertainty = 'changed'",
    "DELETE FROM {table}",
    "TRUNCATE {table}",
    "ALTER TABLE {table} ADD COLUMN forbidden text",
    "DROP TABLE {table}",
)


@pytest.mark.parametrize("dataset", DATASETS)
@pytest.mark.parametrize("statement", FORBIDDEN_TABLE_ACTIONS)
def test_cross_contributor_actions_denied(dataset, statement, seeded, admin):
    other = "peat" if dataset == "nrw" else "nrw"
    table = sql.Identifier(f"iris_staging_{other}", "features")
    with connect(f"contributor_{dataset}") as conn:
        denied(conn, sql.SQL(statement).format(table=table))
    count = admin.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0]
    assert count == sum(r["dataset"] == other for r in seeded)


@pytest.mark.parametrize("role", RUNTIME_ROLES)
@pytest.mark.parametrize("statement", FORBIDDEN_TABLE_ACTIONS)
def test_direct_core_access_denied(role, statement):
    with connect(role) as conn:
        denied(conn, sql.SQL(statement).format(table=sql.Identifier("iris_core", "features")))


@pytest.mark.parametrize("dataset", DATASETS)
@pytest.mark.parametrize("statement", FORBIDDEN_TABLE_ACTIONS[2:])
def test_contributor_cannot_modify_existing_staging(dataset, statement, seeded):
    with connect(f"contributor_{dataset}") as conn:
        denied(conn, sql.SQL(statement).format(
            table=sql.Identifier(f"iris_staging_{dataset}", "features")))


@pytest.mark.parametrize("role", RUNTIME_ROLES)
@pytest.mark.parametrize("statement", (
    "CREATE SCHEMA forbidden",
    "CREATE TABLE public.forbidden (id integer)",
    "CREATE TEMP TABLE forbidden (id integer)",
    "SET ROLE iris_owner",
    "SET ROLE iris_promote_executor",
    "SET ROLE postgres",
    "CREATE ROLE forbidden SUPERUSER",
    "ALTER SYSTEM SET work_mem = '16MB'",
    "COPY (SELECT 1) TO PROGRAM 'true'",
))
def test_elevation_and_object_creation_denied(role, statement):
    with connect(role) as conn:
        denied(conn, statement)


@pytest.mark.parametrize("dataset", DATASETS)
def test_contributor_cannot_create_objects_in_own_schema(dataset):
    with connect(f"contributor_{dataset}") as conn:
        denied(conn, sql.SQL("CREATE TABLE {} (id integer)").format(
            sql.Identifier(f"iris_staging_{dataset}", "forbidden")))
        denied(conn, "SET ROLE promoter")


@pytest.mark.parametrize("role", ("contributor_nrw", "contributor_peat", "app_readonly"))
def test_only_promoter_can_call_promotion(role, seeded):
    with connect(role) as conn:
        denied(conn, "SELECT iris_ops.promote('nrw', 'DE', 'fixture-001')")


def test_promoter_reviews_but_cannot_change_staging(seeded):
    with connect("promoter") as conn:
        for dataset in DATASETS:
            table = sql.Identifier(f"iris_staging_{dataset}", "features")
            assert execute(conn, sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] > 0
            for statement in FORBIDDEN_TABLE_ACTIONS[1:]:
                denied(conn, sql.SQL(statement).format(table=table))


def test_country_and_dataset_scoped_promotion_is_idempotent(seeded, admin):
    with connect("app_readonly") as app:
        assert execute(app, "SELECT count(*) FROM iris_api.candidates").fetchone()[0] == 0
    with connect("promoter") as conn:
        for index, record in enumerate(seeded, 1):
            assert promote(conn, record) == 1
            assert promote(conn, record) == 0
            assert admin.execute("SELECT count(*) FROM iris_core.features").fetchone()[0] == index
    with connect("app_readonly") as conn:
        rows = execute(conn,
            "SELECT country_code, dataset, source_id FROM iris_api.candidates "
            "ORDER BY country_code, dataset"
        ).fetchall()
    assert rows == [("DE", "nrw", "fixture-001"), ("DE", "peat", "fixture-001"),
                    ("NL", "peat", "fixture-001")]
    for record in seeded:
        table = sql.Identifier(f"iris_staging_{record['dataset']}", "features")
        assert admin.execute(sql.SQL(
            "SELECT c.geom = s.geom AND c.source_date = s.source_date "
            "AND c.uncertainty = s.uncertainty FROM iris_core.features c JOIN {} s "
            "ON c.country_code=s.country_code AND c.source_id=s.source_id "
            "WHERE c.country_code=%s AND c.dataset=%s AND c.source_id=%s"
        ).format(table), (record["country_code"], record["dataset"], record["source_id"])
        ).fetchone()[0]


@pytest.mark.parametrize("first_commits", (True, False), ids=("commit", "rollback"))
def test_concurrent_promotion_inserts_exactly_once(seeded, admin, first_commits):
    with connect("promoter") as first, connect("promoter") as second:
        # A timeout bounds the worker even if an assertion or connection fails.
        second.execute("SET statement_timeout = '10s'")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with first.transaction(force_rollback=not first_commits):
                assert promote(first, seeded[0]) == 1
                future = pool.submit(promote, second, seeded[0])
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    blockers = admin.execute(
                        "SELECT pg_blocking_pids(%s)", (second.info.backend_pid,),
                    ).fetchone()[0]
                    if first.info.backend_pid in blockers:
                        break
                    if future.done():
                        pytest.fail(f"Second promotion did not block: {future.result()}")
                    time.sleep(0.02)
                else:
                    pytest.fail("Second promotion never waited on the first transaction")
                assert not future.done()
            # Commit skips the existing row; rollback lets the waiting caller insert.
            assert future.result(timeout=10) == (0 if first_commits else 1)
    assert admin.execute("SELECT count(*) FROM iris_core.features").fetchone()[0] == 1


def test_promotion_respects_caller_rollback(seeded, admin):
    with connect("promoter") as conn:
        with conn.transaction(force_rollback=True):
            assert promote(conn, seeded[0]) == 1
    assert admin.execute("SELECT count(*) FROM iris_core.features").fetchone()[0] == 0


@pytest.mark.parametrize("args, expected", (
    (("unknown", "DE", "fixture-001"), "22023"),
    (("nrw; DROP SCHEMA iris_core CASCADE", "DE", "fixture-001"), "22023"),
    ((None, "DE", "fixture-001"), "22023"),
    (("nrw", None, "fixture-001"), "22023"),
    (("nrw", "de", "fixture-001"), "22023"),
    (("nrw", "DE", None), "22023"),
    (("nrw", "DE", " "), "22023"),
    (("nrw", "DE", "\t\n"), "22023"),
    (("nrw", "DE", "\u00a0\u200b\ufeff"), "22023"),
    (("nrw", "DE", "missing"), "P0002"),
    (("nrw", "NL", "fixture-001"), "P0002"),
))
def test_bad_promotion_requests_fail_without_writes(args, expected, seeded, admin):
    with connect("promoter") as conn:
        with pytest.raises(psycopg.Error) as caught:
            execute(conn, "SELECT iris_ops.promote(%s, %s, %s)", args)
        assert caught.value.sqlstate == expected
    assert admin.execute("SELECT count(*) FROM iris_core.features").fetchone()[0] == 0


@pytest.mark.parametrize("statement", FORBIDDEN_TABLE_ACTIONS[1:])
def test_app_cannot_write_or_alter_candidate_view(statement):
    # TRUNCATE on a view errors with 42809 before permission checking, so test its
    # missing privilege explicitly; other statements must be rejected by the ACL.
    if statement.startswith("TRUNCATE"):
        with connect("app_readonly") as conn:
            assert not conn.execute(
                "SELECT has_table_privilege(current_user, 'iris_api.candidates', 'TRUNCATE')"
            ).fetchone()[0]
        return
    if statement.startswith("ALTER TABLE"):
        statement = "ALTER VIEW {table} RENAME TO forbidden"
    if statement.startswith("DROP TABLE"):
        statement = "DROP VIEW {table}"
    with connect("app_readonly") as conn:
        denied(conn, sql.SQL(statement).format(table=sql.Identifier("iris_api", "candidates")))


@pytest.mark.parametrize("dataset", DATASETS)
def test_app_cannot_read_staging(dataset):
    with connect("app_readonly") as conn:
        denied(conn, sql.SQL("SELECT * FROM {}").format(
            sql.Identifier(f"iris_staging_{dataset}", "features")))


@pytest.mark.parametrize("role", RUNTIME_ROLES)
def test_extension_lookup_table_is_not_a_public_read_interface(role):
    with connect(role) as conn:
        denied(conn, "SELECT * FROM public.spatial_ref_sys")


def test_caller_search_path_cannot_redirect_promotion(seeded, admin):
    with connect("promoter") as conn:
        conn.execute("SET search_path = public, iris_staging_peat, pg_temp")
        assert promote(conn, seeded[0]) == 1
    assert admin.execute("SELECT dataset FROM iris_core.features").fetchall() == [("nrw",)]


def test_new_relations_and_functions_require_explicit_grants(admin):
    # Use the same creator as setup; defaults belong to the creating role.
    try:
        admin.execute("SET ROLE iris_owner")
        admin.execute("CREATE TABLE iris_staging_nrw.unassigned (country_code text NOT NULL)")
        admin.execute("CREATE VIEW iris_api.unassigned AS SELECT * FROM iris_core.features")
        admin.execute("CREATE FUNCTION iris_ops.unapproved() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
        admin.execute("RESET ROLE")
        with connect("contributor_nrw") as conn:
            denied(conn, "SELECT * FROM iris_staging_nrw.unassigned")
            denied(conn, "INSERT INTO iris_staging_nrw.unassigned VALUES ('DE')")
        with connect("app_readonly") as conn:
            denied(conn, "SELECT * FROM iris_api.unassigned")
        with connect("promoter") as conn:
            denied(conn, "SELECT iris_ops.unapproved()")
    finally:
        admin.execute("RESET ROLE")
        admin.execute("DROP TABLE IF EXISTS iris_staging_nrw.unassigned")
        admin.execute("DROP VIEW IF EXISTS iris_api.unassigned")
        admin.execute("DROP FUNCTION IF EXISTS iris_ops.unapproved()")


def test_function_has_minimal_owner_and_fixed_path(admin):
    row = admin.execute(
        "SELECT p.prosecdef, r.rolname, p.proconfig "
        "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
        "WHERE p.oid='iris_ops.promote(text,text,text)'::regprocedure"
    ).fetchone()
    assert row == (True, "iris_promote_executor", ["search_path=pg_catalog, pg_temp"])
    assert admin.execute(
        "SELECT has_table_privilege('iris_promote_executor', 'iris_core.features', 'INSERT'), "
        "has_table_privilege('iris_promote_executor', 'iris_core.features', 'UPDATE'), "
        "has_table_privilege('iris_promote_executor', 'iris_core.features', 'DELETE')"
    ).fetchone() == (True, False, False)
    for column in ("country_code", "dataset", "source_id", "geom", "uncertainty", "source_date"):
        allowed = admin.execute(
            "SELECT has_column_privilege('iris_promote_executor', "
            "'iris_core.features', %s, 'SELECT')", (column,),
        ).fetchone()[0]
        assert allowed == (column in ("country_code", "dataset", "source_id"))
    for role in RUNTIME_ROLES:
        allowed = admin.execute(
            "SELECT has_function_privilege(%s, 'iris_ops.promote(text,text,text)', 'EXECUTE')",
            (role,),
        ).fetchone()[0]
        assert allowed == (role == "promoter")


def test_offboarding_ends_access_without_deleting_data(admin):
    role = "iris_test_offboarding"
    password = secrets.token_hex(24)
    session = None
    # Administrative provisioning uses safe literal quoting, without logging secrets.
    admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
        sql.Identifier(role), sql.Literal(password)))
    try:
        database = admin.info.dbname
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), sql.Identifier(role)))
        admin.execute("GRANT USAGE ON SCHEMA iris_staging_nrw TO iris_test_offboarding")
        admin.execute("GRANT SELECT, INSERT ON iris_staging_nrw.features TO iris_test_offboarding")
        session = connect(role, password=password)
        insert_record(session, fixtures()[0])
        with admin.transaction():
            admin.execute("ALTER ROLE iris_test_offboarding NOLOGIN PASSWORD NULL")
            admin.execute("REVOKE SELECT, INSERT ON iris_staging_nrw.features FROM iris_test_offboarding")
            admin.execute("REVOKE USAGE ON SCHEMA iris_staging_nrw FROM iris_test_offboarding")
            admin.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(database), sql.Identifier(role)))
        denied(session, "SELECT * FROM iris_staging_nrw.features")
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename=%s", (role,))
        with pytest.raises(psycopg.OperationalError):
            session.execute("SELECT 1")
        with pytest.raises(psycopg.OperationalError, match="password authentication failed|not permitted to log in"):
            connect(role, password=password)
        assert admin.execute("SELECT count(*) FROM iris_staging_nrw.features").fetchone()[0] == 1
    finally:
        if session is not None:
            session.close()
        # This role owns no objects; remove grants without deleting any data.
        admin.execute("REVOKE ALL ON iris_staging_nrw.features FROM iris_test_offboarding")
        admin.execute("REVOKE ALL ON SCHEMA iris_staging_nrw FROM iris_test_offboarding")
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
            sql.Identifier(admin.info.dbname), sql.Identifier(role)))
        admin.execute("DROP ROLE iris_test_offboarding")


@pytest.mark.parametrize("role", RUNTIME_ROLES)
@pytest.mark.parametrize("statement", (
    "SELECT pg_catalog.lo_create(0)",
    "SELECT pg_catalog.lo_creat(-1)",
    "SELECT pg_catalog.lo_from_bytea(0, 'blocked'::bytea)",
))
def test_runtime_roles_cannot_create_large_objects(role, statement, admin):
    before = admin.execute("SELECT count(*) FROM pg_largeobject_metadata").fetchone()[0]
    with connect(role) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            execute(conn, statement)
    assert admin.execute("SELECT count(*) FROM pg_largeobject_metadata").fetchone()[0] == before


@pytest.mark.parametrize("role", RUNTIME_ROLES)
@pytest.mark.parametrize("statement", (
    "SELECT pg_catalog.lo_put(%s, 0, 'blocked'::bytea)",
    "SELECT pg_catalog.lo_unlink(%s)",
    "SELECT pg_catalog.lo_open(%s, 131072)",
))
def test_even_preexisting_owned_large_objects_cannot_be_changed(role, statement, admin):
    # Object ownership must not grant access to the disabled large-object API.
    oid = admin.execute("SELECT lo_from_bytea(0, 'preserve'::bytea)").fetchone()[0]
    try:
        admin.execute(sql.SQL("ALTER LARGE OBJECT {} OWNER TO {}").format(
            sql.Literal(oid), sql.Identifier(role)))
        with connect(role) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                execute(conn, statement, (oid,))
        assert admin.execute("SELECT lo_get(%s)", (oid,)).fetchone()[0] == b"preserve"
    finally:
        admin.execute("SELECT lo_unlink(%s)", (oid,))


def test_all_large_object_function_overloads_are_restricted(admin):
    routines = admin.execute(
        "SELECT p.oid, p.oid::regprocedure::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='pg_catalog' AND "
        "(p.proname LIKE 'lo\\_%' ESCAPE '\\' OR p.proname IN ('loread','lowrite'))"
    ).fetchall()
    assert len(routines) >= 20
    for oid, name in routines:
        for role in RUNTIME_ROLES:
            assert not admin.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, oid),
            ).fetchone()[0], (role, name)
