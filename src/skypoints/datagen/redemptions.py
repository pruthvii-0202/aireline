"""Synthetic partner-airline redemption feed (newline-delimited JSON, one member per line)."""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from typing import Any

from skypoints.datagen.defects import TXN_DEFECTS

PARTNERS = ("AeroLink", "SkyPoints", "PacificWings", "EuroJet", "SunAir")
STATUSES = ("COMPLETED", "PENDING", "CANCELLED")
REDEEMING_MEMBER_SHARE = 0.30


def _txn(rng: random.Random, txn_no: int, as_of: date) -> dict[str, Any]:
    return {
        "txn_id": f"RX{txn_no}",
        "txn_date": (as_of - timedelta(days=rng.randint(0, 10))).strftime("%Y%m%d"),
        "partner": rng.choice(PARTNERS),
        "miles_redeemed": rng.randrange(500, 50_001, 500),
        "status": rng.choices(STATUSES, weights=(75, 20, 5))[0],
    }


def build_redemption_feed(
    rng: random.Random,
    member_ids: Sequence[str],
    as_of: date,
    txn_numbers: Iterator[int],
    defect_rate: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one day's redemption documents for members the pipeline will know about.

    ``member_ids`` must be in a deterministic order. ``txn_numbers`` is shared across days
    so txn ids are globally unique unless a DUPLICATE_TXN_ID defect is injected.

    Returns (documents in file order, manifest defect entries).
    """
    if not member_ids:
        return [], []
    feed_date = as_of.strftime("%Y%m%d")

    def doc(member_id: str, n_txns: int) -> dict[str, Any]:
        txns = [_txn(rng, next(txn_numbers), as_of) for _ in range(n_txns)]
        return {"member_id": member_id, "feed_date": feed_date, "redemptions": txns}

    redeemers = rng.sample(
        list(member_ids), k=max(1, int(len(member_ids) * REDEEMING_MEMBER_SHARE))
    )
    docs = [doc(m, rng.randint(1, 3)) for m in redeemers]

    special: list[tuple[str, dict[str, Any]]] = []
    for _ in range(max(1, len(docs) // 100)):
        # 9xxxxx ids are outside the member id range, so these never match a member.
        special.append(("ORPHAN_MEMBER", doc(f"9{rng.randint(0, 99_999):05d}", 1)))
        special.append(("EMPTY_REDEMPTIONS", doc(rng.choice(member_ids), 0)))
    for _, d in special:
        docs.insert(rng.randint(0, len(docs)), d)

    line_no = {id(d): i for i, d in enumerate(docs, start=1)}
    defects: list[dict[str, Any]] = [
        {"defect": name, "line_no": line_no[id(d)], "member_id": d["member_id"]}
        for name, d in special
    ]

    clean: list[tuple[int, int, dict[str, Any]]] = []
    for d in docs:
        for idx, txn in enumerate(d["redemptions"]):
            if rng.random() < defect_rate:
                name = rng.choice(sorted(TXN_DEFECTS))
                defects.append(
                    {
                        "defect": name,
                        "line_no": line_no[id(d)],
                        "txn_index": idx,
                        "txn_id": txn["txn_id"],
                    }
                )
                TXN_DEFECTS[name](txn, rng, as_of)
            else:
                clean.append((line_no[id(d)], idx, txn))

    # Duplicates take ids from the first half, so a source id is never itself overwritten.
    half = len(clean) // 2
    if half:
        for dup_line, idx, txn in rng.sample(clean[half:], k=min(half, max(1, len(clean) // 100))):
            src_line, _, src = rng.choice(clean[:half])
            txn["txn_id"] = src["txn_id"]
            defects.append(
                {
                    "defect": "DUPLICATE_TXN_ID",
                    "line_no": dup_line,
                    "txn_index": idx,
                    "txn_id": src["txn_id"],
                    "duplicate_of_line_no": src_line,
                }
            )

    return docs, defects
