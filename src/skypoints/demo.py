"""Print the demo queries in sql/demo/demo_queries.sql as plain-text tables.

Run with: python -m skypoints.demo
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from skypoints.config import SnowflakeSettings
from skypoints.snowflake_conn import connect

DEMO_SQL = Path(__file__).resolve().parents[2] / "sql" / "demo" / "demo_queries.sql"
_TITLE = "-- name:"


def parse_queries(text: str) -> list[tuple[str, str]]:
    """(title, sql) for every block that starts with a '-- name:' line."""
    queries: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith(_TITLE):
            queries.append((line[len(_TITLE) :].strip(), []))
        elif queries:
            queries[-1][1].append(line)
    return [(title, "\n".join(body).strip().rstrip(";")) for title, body in queries]


def format_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    cells = [["NULL" if v is None else str(v) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(columns)]

    def line(values: Sequence[str]) -> str:
        return "  ".join(v.ljust(w) for v, w in zip(values, widths, strict=True)).rstrip()

    return "\n".join([line(columns), line(["-" * w for w in widths]), *map(line, cells)])


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    settings = SnowflakeSettings.from_env()
    print(f"Database: {settings.database}")
    with connect(settings) as conn:
        cur = conn.cursor()
        for title, sql in parse_queries(DEMO_SQL.read_text(encoding="utf-8")):
            cur.execute(sql)
            columns = [c[0] for c in cur.description]
            print(f"\n=== {title}\n{format_table(columns, cur.fetchall())}")


if __name__ == "__main__":
    main()
