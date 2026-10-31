"""Build GOLD.DIM_MEMBER (SCD Type 2 member history) and GOLD.MEMBER_360 from Silver.

Gold tables are full rebuilds from Silver: Silver keeps every batch, so a rebuild is
idempotent and replay-safe by construction.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from skypoints.silver.members import STALE_DAYS
from skypoints.sql_runner import render

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[3] / "sql" / "transform" / "gold"

# Business rule settings, kept in one place.
ACTIVE_DAYS = 30  # flew within this many days: ACTIVE; up to STALE_DAYS: AT_RISK
RECENT_REDEMPTION_DAYS = 30  # stale members who redeemed this recently are DORMANT_REDEEMER


def dim_member_sql(silver: str, gold: str) -> str:
    template = (SQL_DIR / "dim_member.sql").read_text(encoding="utf-8")
    return render(template, {"silver": silver, "gold": gold})


def member_360_sql(database: str, silver: str, gold: str, as_of: date) -> str:
    template = (SQL_DIR / "member_360.sql").read_text(encoding="utf-8")
    return render(
        template,
        {
            "database": database,
            "silver": silver,
            "gold": gold,
            "as_of": as_of.isoformat(),
            "stale_days": str(STALE_DAYS),
            "active_days": str(ACTIVE_DAYS),
            "recent_redemption_days": str(RECENT_REDEMPTION_DAYS),
        },
    )


def build_dim_member(conn: Any, silver: str, gold: str) -> None:
    cur = conn.cursor()
    cur.execute(dim_member_sql(silver, gold))
    versions, members = cur.execute(
        f"SELECT COUNT(*), COUNT_IF(IS_CURRENT) FROM {gold}.DIM_MEMBER"
    ).fetchone()
    log.info("DIM_MEMBER: %d versions for %d members", versions, members)


def build_member_360(conn: Any, database: str, as_of: date, silver: str, gold: str) -> None:
    cur = conn.cursor()
    cur.execute(member_360_sql(database, silver, gold, as_of))
    members, miles = cur.execute(
        f"SELECT COUNT(*), COALESCE(SUM(COMPLETED_MILES), 0) FROM {gold}.MEMBER_360"
    ).fetchone()
    log.info("MEMBER_360 as of %s: %d members, %d completed miles", as_of, members, miles)

