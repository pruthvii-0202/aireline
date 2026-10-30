"""Build SILVER.REDEMPTION_TXN and SILVER.REDEMPTION_REJECT for one batch date.

Run after the member steps for the same batch, so orphan checks see that day's members.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from skypoints.silver.members import SQL_DIR
from skypoints.sql_runner import render

log = logging.getLogger(__name__)

BRONZE_REDEMPTIONS = "BRONZE.REDEMPTION_RAW"


def _render(name: str, silver: str, batch_date: date, source: str) -> str:
    template = (SQL_DIR / name).read_text(encoding="utf-8")
    return render(
        template, {"silver": silver, "batch_date": batch_date.isoformat(), "source": source}
    )


def validate_sql(silver: str, batch_date: date, source: str = BRONZE_REDEMPTIONS) -> str:
    """SELECT returning one row per transaction (or empty document) with REJECT_REASONS."""
    return _render("redemption_validate.sql", silver, batch_date, source)


def load_sql(silver: str, batch_date: date) -> str:
    return _render("redemption_load.sql", silver, batch_date, BRONZE_REDEMPTIONS)


def load_batch(
    conn: Any,
    database: str,
    batch_date: date,
    silver: str | None = None,
    source: str = BRONZE_REDEMPTIONS,
) -> tuple[int, int]:
    """Replace the batch in REDEMPTION_TXN / REDEMPTION_REJECT. Returns (accepted, rejected)."""
    silver = silver or f"{database}.SILVER"
    cur = conn.cursor()
    cur.execute(
        f"CREATE OR REPLACE TEMPORARY TABLE {silver}.REDEMPTION_BATCH_TMP AS\n"
        + validate_sql(silver, batch_date, source)
    )
    accepted, rejected, orphans = cur.execute(
        "SELECT COUNT_IF(ARRAY_SIZE(REJECT_REASONS) = 0), "
        "COUNT_IF(ARRAY_SIZE(REJECT_REASONS) > 0), "
        "COUNT_IF(ARRAY_SIZE(REJECT_REASONS) = 0 AND ORPHAN_MEMBER) "
        f"FROM {silver}.REDEMPTION_BATCH_TMP"
    ).fetchone()
    conn.execute_string(load_sql(silver, batch_date))
    log.info(
        "REDEMPTION_TXN %s: %d accepted (%d orphan), %d rejected",
        batch_date,
        accepted,
        orphans,
        rejected,
    )
    return accepted, rejected
