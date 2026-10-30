from datetime import date

from skypoints.silver.redemptions import load_sql, validate_sql


def test_validate_sql_renders_completely():
    sql = validate_sql("DB.SILVER", date(2024, 1, 15), source="DB.X.RAW")
    assert "{{" not in sql
    assert "FROM DB.X.RAW" in sql
    assert "LEFT JOIN DB.SILVER.MEMBER_CURRENT" in sql
    assert "OUTER => TRUE" in sql  # empty documents are not silently dropped


def test_load_sql_replaces_batch_and_rechecks_orphans():
    sql = load_sql("DB.SILVER", date(2024, 1, 16))
    assert "{{" not in sql
    assert sql.count("WHERE BATCH_DATE = '2024-01-16'::DATE") == 2
    assert "SET ORPHAN_MEMBER = FALSE" in sql
