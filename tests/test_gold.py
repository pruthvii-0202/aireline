from skypoints.gold.build import dim_member_sql


def test_dim_member_sql_renders_completely():
    sql = dim_member_sql("DB.SILVER", "DB.GOLD")
    assert "{{" not in sql
    assert "INSERT OVERWRITE INTO DB.GOLD.DIM_MEMBER" in sql  # atomic full rebuild
    assert "FROM DB.SILVER.MEMBER_STG" in sql  # history comes from every staged batch


def test_dim_member_does_not_version_on_volatile_columns():
    sql = dim_member_sql("DB.SILVER", "DB.GOLD")
    tracked = sql.split("AS attribute_hash")[0].rsplit("SHA2(", 1)[1]
    assert "COUNTRY_ISO" in tracked
    assert "LAST_FLIGHT_DATE" not in tracked  # changes with every flight
    assert "COUNTRY_RAW" not in tracked  # AU / AUS aliases are the same country
