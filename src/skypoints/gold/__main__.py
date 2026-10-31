"""CLI: python -m skypoints.gold [--as-of YYYYMMDD]   (default: the latest Silver batch)"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from skypoints.config import SnowflakeSettings
from skypoints.gold.build import build_dim_member, build_member_360, latest_batch_date
from skypoints.snowflake_conn import connect


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build Gold tables from Silver.")
    parser.add_argument("--as-of", help="YYYYMMDD; omit to use the latest Silver batch")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("snowflake").setLevel(logging.WARNING)

    settings = SnowflakeSettings.from_env()
    silver, gold = f"{settings.database}.SILVER", f"{settings.database}.GOLD"
    with connect(settings) as conn:
        cur = conn.cursor()
        if args.as_of:
            as_of = datetime.strptime(args.as_of, "%Y%m%d").date()
        else:
            as_of = latest_batch_date(cur, silver)
        if as_of is None:
            sys.exit("Silver is empty: run python -m skypoints.silver first")
        # One transaction, so readers never see a new DIM_MEMBER next to an old MEMBER_360.
        cur.execute("BEGIN")
        try:
            build_dim_member(conn, silver, gold)
            build_member_360(conn, settings.database, as_of, silver, gold)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise


if __name__ == "__main__":
    main()
