from skypoints.demo import DEMO_SQL, format_table, parse_queries


def test_parse_queries_splits_on_titles_and_keeps_sql():
    text = (
        "-- Header comment, not a query\n"
        "-- name: First\n"
        "SELECT 1;\n"
        "\n"
        "-- name: Second one\n"
        "-- a comment that belongs to the query\n"
        "SELECT 2\n"
        "FROM t;\n"
    )
    assert parse_queries(text) == [
        ("First", "SELECT 1"),
        ("Second one", "-- a comment that belongs to the query\nSELECT 2\nFROM t"),
    ]


def test_demo_sql_file_is_plain_sql_that_runs_in_snowsight():
    queries = parse_queries(DEMO_SQL.read_text(encoding="utf-8"))
    assert len(queries) >= 8
    assert all(sql for _, sql in queries)
    assert not any("{{" in sql for _, sql in queries)  # no placeholders to fill by hand


def test_format_table_aligns_columns_and_shows_nulls():
    out = format_table(["ID", "COUNTRY"], [("100001", "PH"), ("7", None)])
    assert out.splitlines() == [
        "ID      COUNTRY",
        "------  -------",
        "100001  PH",
        "7       NULL",
    ]
