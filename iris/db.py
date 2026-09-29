import json
import os
from pathlib import Path

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
PASSWORD_VARS = {
    "postgres": "POSTGRES_PASSWORD",
    "contributor_nrw": "IRIS_NRW_PASSWORD",
    "contributor_peat": "IRIS_PEAT_PASSWORD",
    "promoter": "IRIS_PROMOTER_PASSWORD",
    "app_readonly": "IRIS_APP_PASSWORD",
}
RUNTIME_ROLES = tuple(role for role in PASSWORD_VARS if role != "postgres")
DATASETS = ("nrw", "peat")


def connect(role, *, password=None):
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "55432")),
        dbname=os.environ.get("PGDATABASE", "iris"),
        user=role,
        password=password if password is not None else os.environ[PASSWORD_VARS[role]],
        connect_timeout=5,
        autocommit=True,
        application_name="iris-assignment-verification",
    )


def fixtures():
    return json.loads((ROOT / "fixtures" / "features.json").read_text())


def insert_record(conn, record, *, retry=False):
    dataset = record["dataset"]
    if dataset not in DATASETS:
        raise ValueError("Unsupported fixture dataset")
    statement = sql.SQL(
        "INSERT INTO {} (country_code, source_id, geom, source_date, uncertainty) "
        "VALUES (%s, %s, public.ST_GeomFromEWKT(%s), %s, %s)"
    ).format(sql.Identifier(f"iris_staging_{dataset}", "features"))
    if retry:
        statement += sql.SQL(" ON CONFLICT (country_code, source_id) DO NOTHING")
    return execute(conn, statement, (
        record["country_code"], record["source_id"], record["ewkt"],
        record["source_date"], record["uncertainty"],
    ))


def execute(conn, statement, params=None):
    # Print executable fixture SQL, never connection strings or credentials.
    display = psycopg.ClientCursor(conn).mogrify(statement, params)
    print(f"[{conn.info.user}] {display}")
    return conn.execute(statement, params)
