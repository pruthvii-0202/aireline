"""Build SILVER.MEMBER_STG and SILVER.MEMBER_REJECT for one batch date.

The rules live in sql/transform/silver/member_validate.sql so they run inside Snowflake
(at billions of rows the data must not leave the warehouse). The source table is a
placeholder, so integration tests run the exact same SQL over hand-made edge cases.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from skypoints.sql_runner import render

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[3] / "sql" / "transform" / "silver"

# Business rule settings, kept in one place.
STALE_DAYS = 90  # STALE_MEMBER when the last flight is more than this many days before the batch
MIN_ID_LENGTH = 6  # shorter ids are kept but flagged ID_LENGTH_SUSPECT

BRONZE_MEMBERS = "BRONZE.MEMBER_PROFILE_RAW"


def _variables(database: str, batch_date: date, source: str) -> dict[str, str]:
    return {
        "database": database,
        "batch_date": batch_date.isoformat(),
        "source": source,
        "stale_days": str(STALE_DAYS),
        "min_id_length": str(MIN_ID_LENGTH),
    }


def validate_sql(database: str, batch_date: date, source: str = BRONZE_MEMBERS) -> str:
    """SELECT returning every detail row of the batch with REJECT_REASONS and derived columns."""
    template = (SQL_DIR / "member_validate.sql").read_text(encoding="utf-8")
    return render(template, _variables(database, batch_date, source))


def load_sql(database: str, batch_date: date) -> str:
    template = (SQL_DIR / "member_stg_load.sql").read_text(encoding="utf-8")
    return render(template, _variables(database, batch_date, BRONZE_MEMBERS))


def load_batch(conn: Any, database: str, batch_date: date) -> tuple[int, int]:
    """Replace the batch in MEMBER_STG / MEMBER_REJECT. Returns (staged, rejected)."""
    cur = conn.cursor()
    cur.execute(
        f"CREATE OR REPLACE TEMPORARY TABLE {database}.SILVER.MEMBER_BATCH_TMP AS\n"
        + validate_sql(database, batch_date)
    )
    staged, rejected = cur.execute(
        "SELECT COUNT_IF(ARRAY_SIZE(REJECT_REASONS) = 0), COUNT_IF(ARRAY_SIZE(REJECT_REASONS) > 0) "
        f"FROM {database}.SILVER.MEMBER_BATCH_TMP"
    ).fetchone()
    conn.execute_string(load_sql(database, batch_date))
    log.info("MEMBER_STG %s: %d staged, %d rejected", batch_date, staged, rejected)
    return staged, rejected


def bronze_batch_dates(cur: Any) -> list[date]:
    cur.execute(f"SELECT DISTINCT BATCH_DATE FROM {BRONZE_MEMBERS} ORDER BY 1")
    return [row[0] for row in cur.fetchall()]
