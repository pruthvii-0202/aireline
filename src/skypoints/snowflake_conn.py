"""Snowflake connection helper and a connectivity check.

Run the check with: python -m skypoints.snowflake_conn
"""

from __future__ import annotations

import logging
from typing import Any

from skypoints.config import SnowflakeSettings

log = logging.getLogger(__name__)


def connect(settings: SnowflakeSettings, use_database: bool = True) -> Any:
    """Open a connection. ``use_database=False`` for bootstrap, before the database exists."""
    import snowflake.connector  # optional extra: keeps unit tests free of the dependency

    return snowflake.connector.connect(
        account=settings.account,
        user=settings.user,
        password=settings.password,
        role=settings.role,
        warehouse=settings.warehouse,
        database=settings.database if use_database else None,
        application="skypoints-pipeline",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = SnowflakeSettings.from_env()
    log.info("connecting with %r", settings)
    with connect(settings, use_database=False) as conn:
        row = (
            conn.cursor()
            .execute(
                "SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), "
                "CURRENT_WAREHOUSE(), CURRENT_REGION(), CURRENT_VERSION()"
            )
            .fetchone()
        )
    labels = ("account", "user", "role", "warehouse", "region", "version")
    for label, value in zip(labels, row, strict=True):
        log.info("%-9s %s", label, value)


if __name__ == "__main__":
    main()
