"""Apply the idempotent DDL scripts in version order (V001__..., V002__...).

Run with: python -m skypoints.sql_runner [sql/ddl]

Scripts use {{ name }} placeholders (e.g. {{ database }}) so the same files build DEV or PROD.
In production this would be schemachange or Snowflake's native Git integration; a small
runner keeps the dependency count down for this project.
"""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Mapping
from pathlib import Path

from skypoints.config import SnowflakeSettings
from skypoints.snowflake_conn import connect

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_SCRIPT_NAME = re.compile(r"^V(\d+)__\w+\.sql$")


def render(sql: str, variables: Mapping[str, str]) -> str:
    """Fill {{ name }} placeholders; an unknown name is an error, never left in the SQL."""

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"no value for placeholder {{{{ {name} }}}}")
        return variables[name]

    return _PLACEHOLDER.sub(sub, sql)


def ddl_scripts(directory: Path) -> list[Path]:
    """Scripts named V<number>__<name>.sql, ordered by number (V010 after V002)."""
    scripts = [p for p in directory.iterdir() if _SCRIPT_NAME.match(p.name)]
    return sorted(scripts, key=lambda p: int(_SCRIPT_NAME.match(p.name).group(1)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply DDL scripts to Snowflake.")
    parser.add_argument("directory", nargs="?", type=Path, default=Path("sql/ddl"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("snowflake").setLevel(logging.WARNING)

    settings = SnowflakeSettings.from_env()
    variables = {"database": settings.database}
    with connect(settings, use_database=False) as conn:
        for script in ddl_scripts(args.directory):
            sql = render(script.read_text(encoding="utf-8"), variables)
            cursors = conn.execute_string(sql)
            log.info("applied %s (%d statements)", script.name, len(cursors))


if __name__ == "__main__":
    main()
