from datetime import date

import psycopg
from psycopg import sql
import pytest

from iris.db import DATASETS, connect, execute, fixtures, insert_record


@pytest.mark.parametrize("field,value,expected", (
    ("country_code", None, "23502"),
    ("country_code", "de", "23514"),
    ("country_code", "DEU", "23514"),
    ("source_id", None, "23502"),
    ("source_id", " ", "23514"),
    ("source_date", None, "23502"),
    ("uncertainty", None, "23502"),
    ("uncertainty", " ", "23514"),
    ("ewkt", None, "23502"),
    ("ewkt", "SRID=3857;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))", "23514"),
    ("ewkt", "MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))", "23514"),
    ("ewkt", "SRID=4326;POLYGON((0 0,1 0,1 1,0 1,0 0))", "23514"),
    ("ewkt", "SRID=4326;MULTIPOLYGON EMPTY", "23514"),
    ("ewkt", "SRID=4326;MULTIPOLYGON(((0 0,1 1,1 0,0 1,0 0)))", "23514"),
    ("ewkt", "SRID=4326;MULTIPOLYGON Z(((0 0 1,1 0 1,1 1 1,0 1 1,0 0 1)))", "23514"),
))
def test_incomplete_or_invalid_data_is_rejected(field, value, expected, admin):
    record = fixtures()[0] | {field: value}
    with connect("contributor_nrw") as conn:
        with pytest.raises(psycopg.Error) as caught:
            insert_record(conn, record)
        assert caught.value.sqlstate == expected
        print(f"  REJECTED SQLSTATE={expected}")
    assert admin.execute("SELECT count(*) FROM iris_staging_nrw.features").fetchone()[0] == 0


def test_duplicate_country_scoped_key_is_rejected():
    record = fixtures()[0]
    with connect("contributor_nrw") as conn:
        insert_record(conn, record)
        with pytest.raises(psycopg.errors.UniqueViolation) as caught:
            insert_record(conn, record)
        assert caught.value.sqlstate == "23505"


@pytest.mark.parametrize("schema,role", (
    ("iris_staging_nrw", "contributor_nrw"),
    ("iris_staging_peat", "contributor_peat"),
    ("iris_core", "postgres"),
))
@pytest.mark.parametrize("coordinates", (
    pytest.param("-181 0,-180 0,-180 1,-181 1,-181 0", id="longitude-below-minimum"),
    pytest.param("180 0,181 0,181 1,180 1,180 0", id="longitude-above-maximum"),
    pytest.param("0 -91,1 -91,1 -90,0 -90,0 -91", id="latitude-below-minimum"),
    pytest.param("0 90,1 90,1 91,0 91,0 90", id="latitude-above-maximum"),
    pytest.param("179 0,180.00000001 0,180.00000001 1,179 1,179 0", id="just-outside-boundary"),
    pytest.param(
        "500000 5700000,500010 5700000,500010 5700010,500000 5700010,500000 5700000",
        id="projected-coordinates-labelled-4326",
    ),
))
def test_out_of_bounds_geometry_is_rejected(schema, role, coordinates):
    statement = sql.SQL(
        "INSERT INTO {} (country_code, source_id, geom, source_date, uncertainty{}) "
        "VALUES ('DE', 'outside-bounds', public.ST_GeomFromEWKT(%s), "
        "'2026-01-01', 'Synthetic bounds test'{})"
    ).format(
        sql.Identifier(schema, "features"),
        sql.SQL(", dataset" if schema == "iris_core" else ""),
        sql.SQL(", 'nrw'" if schema == "iris_core" else ""),
    )
    with connect(role) as conn:
        with pytest.raises(psycopg.errors.CheckViolation) as caught:
            execute(conn, statement, (f"SRID=4326;MULTIPOLYGON((({coordinates})))",))
        assert caught.value.diag.constraint_name == "features_geom_bounds_check"
        print("  REJECTED SQLSTATE=23514 (coordinate bounds)")


@pytest.mark.parametrize("dataset", DATASETS)
@pytest.mark.parametrize("coordinates", (
    pytest.param("-180 -90,-179 -90,-179 -89,-180 -89,-180 -90", id="minimum-boundaries"),
    pytest.param("179 89,180 89,180 90,179 90,179 89", id="maximum-boundaries"),
))
def test_geometry_on_coordinate_boundaries_can_be_published(dataset, coordinates):
    record = fixtures()[0] | {
        "dataset": dataset,
        "ewkt": f"SRID=4326;MULTIPOLYGON((({coordinates})))",
    }
    with connect(f"contributor_{dataset}") as conn:
        assert insert_record(conn, record).rowcount == 1
    with connect("promoter") as conn:
        assert execute(conn, "SELECT iris_ops.promote(%s, %s, %s)", (
            dataset, record["country_code"], record["source_id"],
        )).fetchone()[0] == 1
    with connect("app_readonly") as conn:
        assert execute(conn,
            "SELECT public.ST_Equals(geom, public.ST_GeomFromEWKT(%s)) "
            "FROM iris_api.candidates WHERE country_code=%s AND dataset=%s AND source_id=%s",
            (record["ewkt"], record["country_code"], dataset, record["source_id"]),
        ).fetchone()[0]


@pytest.fixture(params=(
    ("iris_staging_nrw", "contributor_nrw"),
    ("iris_staging_peat", "contributor_peat"),
    ("iris_core", "postgres"),
))
def target(request):
    return request.param


def insert_into_target(target, **overrides):
    schema, role = target
    record = fixtures()[0] | overrides
    statement = sql.SQL(
        "INSERT INTO {} (country_code, source_id, geom, source_date, uncertainty{}) "
        "VALUES (%s, %s, public.ST_GeomFromEWKT(%s), %s, %s{})"
    ).format(
        sql.Identifier(schema, "features"),
        sql.SQL(", dataset" if schema == "iris_core" else ""),
        sql.SQL(", 'nrw'" if schema == "iris_core" else ""),
    )
    with connect(role) as conn:
        execute(conn, statement, (
            record["country_code"], record["source_id"], record["ewkt"],
            record["source_date"], record["uncertainty"],
        ))


@pytest.mark.parametrize("value", ("infinity", "-infinity", "10000-01-01", "0001-01-01 BC"))
def test_dates_unreadable_by_python_are_rejected(target, value):
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        insert_into_target(target, source_date=value)
    assert caught.value.diag.constraint_name == "features_source_date_range_check"


@pytest.mark.parametrize("field", ("source_id", "uncertainty"))
@pytest.mark.parametrize("value", (
    "\t", "\n", "\r\n \v\f", "\u00a0", "\u2003\u202f",
    "\u0085\u1680\u2028\u2029\u205f\u3000", "\u200b\ufeff",
))
def test_blank_metadata_is_rejected_in_every_table(target, field, value):
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        insert_into_target(target, **{field: value})
    assert caught.value.diag.constraint_name == f"features_{field}_text_check"


@pytest.mark.parametrize("dataset", ("nrw", "peat"))
@pytest.mark.parametrize("source_date", (date.min, date.max))
def test_date_boundaries_and_unicode_text_round_trip(dataset, source_date):
    record = fixtures()[0] | {
        "dataset": dataset, "source_date": source_date,
        "source_id": "\tidentifiant-Ω\u00a0",
        "uncertainty": "\nPrécision inconnue — synthetic test.\u2003",
    }
    with connect(f"contributor_{dataset}") as conn:
        insert_record(conn, record)
    with connect("promoter") as conn:
        assert conn.execute("SELECT iris_ops.promote(%s, %s, %s)", (
            dataset, record["country_code"], record["source_id"],
        )).fetchone()[0] == 1
    with connect("app_readonly") as conn:
        assert conn.execute(
            "SELECT source_id, source_date, uncertainty FROM iris_api.candidates"
        ).fetchone() == (record["source_id"], source_date, record["uncertainty"])
