"""Snowflake connection settings, read from environment variables.

A local, git-ignored `.env` file is also read for convenience. Real environment variables
win over `.env`, so CI and production never depend on the file.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")


def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; ignores blanks, comments and surrounding quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    password: str
    role: str
    warehouse: str
    database: str

    def __repr__(self) -> str:  # never leak the password into logs
        return (
            f"SnowflakeSettings(account={self.account!r}, user={self.user!r}, "
            f"role={self.role!r}, warehouse={self.warehouse!r}, database={self.database!r})"
        )

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, env_file: Path | None = Path(".env")
    ) -> SnowflakeSettings:
        values: dict[str, str] = {}
        if env_file is not None and env_file.is_file():
            values.update(parse_env_file(env_file.read_text(encoding="utf-8")))
        values.update(os.environ if environ is None else environ)

        missing = [k for k in REQUIRED if not values.get(k)]
        if missing:
            raise RuntimeError(
                f"missing Snowflake settings: {', '.join(missing)} (see .env.example)"
            )
        return cls(
            account=values["SNOWFLAKE_ACCOUNT"],
            user=values["SNOWFLAKE_USER"],
            password=values["SNOWFLAKE_PASSWORD"],
            role=values.get("SNOWFLAKE_ROLE", "SYSADMIN"),
            warehouse=values.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
            database=values.get("SNOWFLAKE_DATABASE", "SKYPOINTS_DEV"),
        )
