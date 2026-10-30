"""Integration tests run against Snowflake DEV. Opt in with: pytest -m integration"""

import pytest

from skypoints.config import SnowflakeSettings


@pytest.fixture(scope="session")
def sf_settings() -> SnowflakeSettings:
    try:
        return SnowflakeSettings.from_env()
    except RuntimeError as exc:
        pytest.skip(f"no Snowflake credentials: {exc}")


@pytest.fixture(scope="session")
def sf_conn(sf_settings):
    pytest.importorskip("snowflake.connector")
    from skypoints.snowflake_conn import connect

    conn = connect(sf_settings)
    yield conn
    conn.close()
