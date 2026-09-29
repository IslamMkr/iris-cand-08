"""Load, publish, and read sample records using the contributor and app roles."""

from iris.db import connect, execute, fixtures, insert_record


def main():
    for record in fixtures():
        with connect(f"contributor_{record['dataset']}") as conn:
            insert_record(conn, record, retry=True)
        with connect("promoter") as conn:
            result = execute(conn, "SELECT iris_ops.promote(%s, %s, %s)", (
                record["dataset"], record["country_code"], record["source_id"],
            )).fetchone()[0]
            print(f"  inserted={result}")
    with connect("app_readonly") as conn:
        rows = execute(conn,
            "SELECT country_code, dataset, source_id, source_date, uncertainty "
            "FROM iris_api.candidates ORDER BY country_code, dataset, source_id"
        ).fetchall()
        for row in rows:
            print(f"  {row}")


if __name__ == "__main__":
    main()
