"""CLI: python -m skypoints.bronze --landing data/landing"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from skypoints.bronze.loader import load_landing, reconcile
from skypoints.config import SnowflakeSettings
from skypoints.snowflake_conn import connect

log = logging.getLogger("skypoints.bronze")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load landing files into Bronze.")
    parser.add_argument("--landing", type=Path, default=Path("data/landing"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("snowflake").setLevel(logging.WARNING)

    with connect(SnowflakeSettings.from_env()) as conn:
        cur = conn.cursor()
        entries = load_landing(cur, args.landing)
        log.info("%d file(s) loaded this run", len(entries))
        mismatches = 0
        for name, expected, actual in reconcile(cur, args.landing):
            ok = expected == actual
            mismatches += not ok
            log.info(
                "%-40s file=%6d bronze=%6d %s", name, expected, actual, "OK" if ok else "MISMATCH"
            )
    if mismatches:
        sys.exit(f"{mismatches} file(s) do not reconcile")


if __name__ == "__main__":
    main()
