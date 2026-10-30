"""Simulates the SkyPoints source system: writes daily member + redemption feeds and a manifest.

Day 1 is a full extract of the population; later days are deltas (~10% of members changed,
including country moves, plus ~2% new enrolments). Each day also gets
MANIFEST_<date>.json listing every injected defect and country move.
"""

from __future__ import annotations

import itertools
import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from skypoints.datagen.members import (
    FIRST_MEMBER_ID,
    HEADER_FIELDS,
    Member,
    build_member_feed,
    evolve,
    new_member,
)
from skypoints.datagen.redemptions import build_redemption_feed

log = logging.getLogger(__name__)

DAILY_CHANGE_SHARE = 0.10
DAILY_NEW_MEMBER_SHARE = 0.02
FILE_TIME = "06000000"  # HHMMSSTT: the source system extracts at 06:00


def member_file_name(as_of: date) -> str:
    return f"MEMBER_PROFILE_{as_of:%Y%m%d}_{FILE_TIME}.txt"


def redemption_file_name(as_of: date) -> str:
    return f"REDEMPTIONS_{as_of:%Y%m%d}.json"


def manifest_file_name(as_of: date) -> str:
    return f"MANIFEST_{as_of:%Y%m%d}.json"


def write_member_file(path: Path, records: list[dict[str, str]]) -> None:
    lines = ["|H|" + "|".join(HEADER_FIELDS)]
    lines += ["|D|" + "|".join(rec[f] for f in HEADER_FIELDS) for rec in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_redemption_file(path: Path, docs: list[dict[str, Any]]) -> None:
    body = "".join(json.dumps(d, separators=(",", ":")) + "\n" for d in docs)
    path.write_text(body, encoding="utf-8", newline="\n")


def generate(
    out_dir: Path,
    days: int,
    members: int,
    seed: int,
    start: date,
    defect_rate: float = 0.05,
) -> list[Path]:
    """Write ``days`` daily feeds starting at ``start``. Same seed => identical files."""
    if days < 1 or members < 1:
        raise ValueError("days and members must be >= 1")
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    member_ids = itertools.count(FIRST_MEMBER_ID)
    txn_numbers = itertools.count(10_000)
    population: dict[str, Member] = {}
    known_ids: set[str] = set()
    written: list[Path] = []

    for day in range(days):
        as_of = start + timedelta(days=day)
        moves: list[dict[str, str]] = []
        if day == 0:
            todays = [new_member(rng, next(member_ids), as_of) for _ in range(members)]
        else:
            todays = []
            changed = rng.sample(
                sorted(population), k=max(1, int(len(population) * DAILY_CHANGE_SHARE))
            )
            for mid in changed:
                before = population[mid]
                after, change = evolve(rng, before, as_of)
                todays.append(after)
                if change == "COUNTRY_MOVE":
                    moves.append(
                        {
                            "member_id": mid,
                            "from_country": before.country,
                            "to_country": after.country,
                        }
                    )
            n_new = max(1, int(members * DAILY_NEW_MEMBER_SHARE))
            todays += [new_member(rng, next(member_ids), as_of) for _ in range(n_new)]
        population.update((m.member_id, m) for m in todays)

        moved_ids = {mv["member_id"] for mv in moves}
        records, member_defects, clean_ids = build_member_feed(
            rng, todays, moved_ids, as_of, defect_rate
        )
        known_ids |= clean_ids
        docs, redemption_defects = build_redemption_feed(
            rng, sorted(known_ids), as_of, txn_numbers, defect_rate
        )

        member_path = out_dir / member_file_name(as_of)
        redemption_path = out_dir / redemption_file_name(as_of)
        manifest_path = out_dir / manifest_file_name(as_of)
        write_member_file(member_path, records)
        write_redemption_file(redemption_path, docs)
        manifest = {
            "feed_date": f"{as_of:%Y%m%d}",
            "seed": seed,
            "member_file": member_path.name,
            "member_rows": len(records),
            "redemption_file": redemption_path.name,
            "redemption_lines": len(docs),
            "redemption_txns": sum(len(d["redemptions"]) for d in docs),
            "member_defects": member_defects,
            "redemption_defects": redemption_defects,
            "country_moves": moves,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        written += [member_path, redemption_path, manifest_path]
        log.info(
            "%s: %d member rows (%d defects, %d moves), %d redemption lines (%d defects)",
            as_of,
            len(records),
            len(member_defects),
            len(moves),
            len(docs),
            len(redemption_defects),
        )
    return written
