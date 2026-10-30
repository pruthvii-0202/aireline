from datetime import date

import pytest

from skypoints.silver.current import CURRENT_COLUMNS, check_table_name, merge_sql, sync_sql


@pytest.mark.parametrize("name", ["MEMBER_US", "MEMBER_AU", "MEMBER_UNMAPPED"])
def test_check_table_name_accepts_country_tables(name):
    assert check_table_name(name) == name


@pytest.mark.parametrize("name", ["MEMBER_USA", "member_us", "MEMBER_US; DROP TABLE X", "OTHER"])
def test_check_table_name_rejects_anything_else(name):
    with pytest.raises(ValueError):
        check_table_name(name)


def test_merge_sql_renders_completely():
    sql = merge_sql("DB", "DB.SILVER", date(2024, 1, 16))
    assert "{{" not in sql
    assert "MERGE INTO DB.SILVER.MEMBER_CURRENT" in sql
    assert "DB.SILVER.IS_STALE(LAST_FLIGHT_DATE, '2024-01-16'::DATE, 90)" in sql


def test_sync_sql_deletes_movers_and_merges_all_columns():
    sql = sync_sql("DB.SILVER", "MEMBER_PH", date(2024, 1, 16))
    assert "{{" not in sql
    assert "DELETE FROM DB.SILVER.MEMBER_PH" in sql
    assert "TARGET_TABLE <> 'MEMBER_PH'" in sql
    assert "MEMBER_ID = s.MEMBER_ID," not in sql  # key is matched on, never updated
    assert f"INSERT ({', '.join(CURRENT_COLUMNS)})" in sql
