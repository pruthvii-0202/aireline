from datetime import date

from skypoints.silver.members import load_sql, validate_sql


def test_validate_sql_renders_completely():
    sql = validate_sql("SKYPOINTS_DEV", date(2024, 1, 15), source="MY.TEST_TABLE")
    assert "{{" not in sql
    assert "FROM MY.TEST_TABLE" in sql
    assert "'2024-01-15'::DATE" in sql
    assert "> 90" in sql  # stale threshold


def test_load_sql_replaces_only_its_batch():
    sql = load_sql("SKYPOINTS_DEV", date(2024, 1, 16))
    assert "{{" not in sql
    assert sql.count("WHERE BATCH_DATE = '2024-01-16'::DATE") == 2
    assert sql.strip().startswith("--") and "BEGIN;" in sql and sql.rstrip().endswith("COMMIT;")
