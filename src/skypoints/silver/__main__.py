"""CLI: python -m skypoints.silver [--batch-date YYYYMMDD]   (default: every Bronze batch)"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from skypoints.config import SnowflakeSettings
from skypoints.silver.current import apply_batch
from skypoints.silver.members import bronze_batch_dates, load_batch
from skypoints.snowflake_conn import connect


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build Silver member tables from Bronze.")
    parser.add_argument("--batch-date", help="YYYYMMDD; omit to process every Bronze batch")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("snowflake").setLevel(logging.WARNING)

    settings = SnowflakeSettings.from_env()
    with connect(settings) as conn:
        if args.batch_date:
            batches = [datetime.strptime(args.batch_date, "%Y%m%d").date()]
        else:
            batches = bronze_batch_dates(conn.cursor())
        for batch_date in batches:  # oldest first, so later batches build on earlier ones
            load_batch(conn, settings.database, batch_date)
            apply_batch(conn, settings.database, batch_date)


if __name__ == "__main__":
    main()
