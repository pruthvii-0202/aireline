"""Build GOLD.DIM_MEMBER (SCD Type 2 member history) from Silver.

Gold tables are full rebuilds from Silver: Silver keeps every batch, so a rebuild is
idempotent and replay-safe by construction.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from skypoints.sql_runner import render

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[3] / "sql" / "transform" / "gold"


def dim_member_sql(silver: str, gold: str) -> str:
    template = (SQL_DIR / "dim_member.sql").read_text(encoding="utf-8")
    return render(template, {"silver": silver, "gold": gold})


def build_dim_member(conn: Any, silver: str, gold: str) -> None:
    cur = conn.cursor()
    cur.execute(dim_member_sql(silver, gold))
    versions, members = cur.execute(
        f"SELECT COUNT(*), COUNT_IF(IS_CURRENT) FROM {gold}.DIM_MEMBER"
    ).fetchone()
    log.info("DIM_MEMBER: %d versions for %d members", versions, members)
