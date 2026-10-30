"""CLI: python -m skypoints.datagen --out data/landing --days 3 --members 1000 --seed 42"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from skypoints.datagen.generator import generate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic SkyPoints source feeds.")
    parser.add_argument("--out", type=Path, default=Path("data/landing"))
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--members", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-date", default="20240115", help="first feed date, YYYYMMDD")
    parser.add_argument("--defect-rate", type=float, default=0.05)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    start = datetime.strptime(args.start_date, "%Y%m%d").date()
    paths = generate(args.out, args.days, args.members, args.seed, start, args.defect_rate)
    logging.info("wrote %d files to %s", len(paths), args.out)


if __name__ == "__main__":
    main()
