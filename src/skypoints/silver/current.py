"""Apply one batch to MEMBER_CURRENT (latest record wins) and the per-country tables.

All steps for a batch run in one transaction, so a reader never sees a member in two
country tables, or in none, halfway through a move.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from skypoints.silver.members import SQL_DIR, STALE_DAYS
from skypoints.sql_runner import render

log = logging.getLogger(__name__)

UNMAPPED_TABLE = "MEMBER_UNMAPPED"
_COUNTRY_TABLE = re.compile(r"^MEMBER_[A-Z]{2}$")

# Column order of MEMBER_CURRENT; country tables are created LIKE it.
CURRENT_COLUMNS = (
    "MEMBER_ID", "MEMBER_NAME", "ENROLLMENT_DATE", "LAST_FLIGHT_DATE", "TIER_CODE",
    "AGENT_NAME", "STATE", "COUNTRY_RAW", "COUNTRY_ISO", "TARGET_TABLE",
    "PREVIOUS_COUNTRY_ISO", "COUNTRY_CHANGED_DATE", "DOB", "IS_ACTIVE", "AGE",
    "STALE_MEMBER", "NEVER_FLOWN", "DQ_FLAGS", "RECORD_HASH", "FIRST_BATCH_DATE",
    "LAST_BATCH_DATE", "ROW_UPDATED_BATCH", "SOURCE_FILE", "SOURCE_FILE_ROW_NO", "UPDATED_AT",
)  # fmt: skip


def check_table_name(name: str) -> str:
    """Table names come from COUNTRY_MAP data and go into SQL text, so allow only MEMBER_XX."""
    if name != UNMAPPED_TABLE and not _COUNTRY_TABLE.match(name):
        raise ValueError(f"unexpected country table name {name!r}")
    return name


def merge_sql(database: str, silver: str, batch_date: date) -> str:
    template = (SQL_DIR / "member_current_merge.sql").read_text(encoding="utf-8")
    return render(
        template,
        {
            "database": database,
            "silver": silver,
            "batch_date": batch_date.isoformat(),
            "stale_days": str(STALE_DAYS),
        },
    )


def sync_sql(silver: str, table: str, batch_date: date) -> str:
    template = (SQL_DIR / "country_table_sync.sql").read_text(encoding="utf-8")
    return render(
        template,
        {
            "silver": silver,
            "table": check_table_name(table),
            "batch_date": batch_date.isoformat(),
            "update_set": ", ".join(f"{c} = s.{c}" for c in CURRENT_COLUMNS if c != "MEMBER_ID"),
            "columns": ", ".join(CURRENT_COLUMNS),
            "source_columns": ", ".join(f"s.{c}" for c in CURRENT_COLUMNS),
        },
    )


def target_tables(cur: Any, silver: str) -> list[str]:
    cur.execute(f"SELECT DISTINCT TARGET_TABLE FROM {silver}.COUNTRY_MAP ORDER BY 1")
    return [check_table_name(r[0]) for r in cur.fetchall()] + [UNMAPPED_TABLE]


def apply_batch(conn: Any, database: str, batch_date: date, silver: str | None = None) -> None:
    """MERGE the batch into MEMBER_CURRENT, refresh AGE/STALE, then sync every country table."""
    silver = silver or f"{database}.SILVER"
    cur = conn.cursor()
    tables = target_tables(cur, silver)
    # DDL commits implicitly in Snowflake, so create any new country tables before BEGIN.
    for table in tables:
        cur.execute(f"CREATE TABLE IF NOT EXISTS {silver}.{table} LIKE {silver}.MEMBER_CURRENT")

    statements = ["BEGIN;", merge_sql(database, silver, batch_date)]
    statements += [sync_sql(silver, t, batch_date) for t in tables]
    statements.append("COMMIT;")
    try:
        conn.execute_string("\n".join(statements))
    except Exception:
        conn.cursor().execute("ROLLBACK")
        raise

    counts = cur.execute(
        f"SELECT TARGET_TABLE, COUNT(*) FROM {silver}.MEMBER_CURRENT GROUP BY 1 ORDER BY 1"
    ).fetchall()
    log.info("MEMBER_CURRENT %s: %s", batch_date, ", ".join(f"{t}={n}" for t, n in counts))
